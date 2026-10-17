# PathwayGPS — Project Audit

Audit date: 2026-10-17. Scope: the Copilot-built project in
`copilot-worktrees/PathwayGPS/redrogod69-miniature-waffle` (the most recent
copy; `PathwayGPS.zip` at the repository parent is an older snapshot of the same
code without `algorithms/`, `verification/` or the KEGG stub). The product
specification is `PathwayGPS PPT1.pptx` / `.pdf` (12 slides, "From mutation to
mechanism").

## 0. What the PPT asks for

| Slide | Requirement |
|---|---|
| 2–3 | Fix fragmentation across ClinVar, UniProt, Reactome, KEGG; a unified graph with "edge-by-edge evidence" and cascade propagation. |
| 4 | Variant → Gene → Pathway mapping, interactive graphs, downstream effects, coverage of VUS. |
| 5 | Process: (1) variant input such as EGFR L858R / BRAF V600E, (2) map to UniProt domain and functional change, (3) traverse Reactome/KEGG, (4) interactive map with highlighted impacted sub-paths. Automated harmonisation of UniProt / ClinVar identifiers. **Evidence overlay: clicking any edge shows PubMed abstract, snippets and experimental methods.** |
| 7 | Variant-to-gene mapping, route variant → gene → protein → pathway → biological effect, graph navigation, node-level exploration, evidence and provenance per relationship, AI-assisted relationship prediction (planned). |
| 8–10 | Multi-database integration, scalability toward diseases and drugs, AI-assisted interpretation and real-time literature as future scope. |
| 6, 12 | "TECH" and "GANTT" slides are empty — no requirements were inferred from them. |

## 1. Architecture and technology stack (as found)

```
React 18 + Vite 5 + Tailwind 3 + React Flow 11   (frontend/src/App.tsx, one 16 KB file)
        │  /api proxy (vite)
FastAPI 0.115 + pydantic 2.9 + httpx 0.27        (backend/app, Python 3.9 venv)
        │  synchronous httpx calls, no cache, no timeouts beyond 20–30 s
ClinVar E-utilities · Ensembl lookup · UniProt search · Reactome Content Service
Optional Neo4j (docker-compose) — client exists but is never used by any route
ETL scripts (etl/, graph/) writing data/canonical/quick_graph.json
```

* Entry points: `backend/app/main.py` (FastAPI), `frontend/src/main.tsx`.
* Services: `backend/app/services/{clinvar,ensembl,uniprot,reactome,variant_resolver,real_pipeline,kegg}_service.py`.
* Graph assembly: `backend/app/graph.py::GraphService.analyze`.
* Algorithms: `backend/app/algorithms/` (BFS, DFS, Dijkstra, adjacency) — correct and tested.
* Tests: 8 pytest tests (all pass, network-mocked); no frontend tests; `tsc` strict mode off.
* Secrets: `.env.example` contains only a Neo4j default password; no API keys. `.env` is git-ignored. No secrets found in source.
* Git: worktree of `~/.copilot/repos/PathwayGPS`, single "Initial commit"; almost every file is untracked.

## 2. What already works

* `POST /api/analyze` performs live lookups: ClinVar esearch/esummary → Ensembl gene lookup → UniProt search → Reactome `mapping/UniProt/{acc}/pathways` → `containedEvents` for each pathway.
* Unknown input such as `ZZZFAKEGENE X999Y` returns `status: not_resolved` instead of fabricated data.
* Nodes and edges carry `source_database`, `source_id`, `source_url`, `retrieved_at`.
* React Flow renders a layered graph; clicking a node or edge opens a small metadata card.
* BFS/DFS/Dijkstra implementations are correct for the toy graphs they are tested on.
* `npm run build` succeeds; `pytest` passes (8/8).

## 3. Missing or broken requirements

| # | Problem | Evidence in code | Severity |
|---|---|---|---|
| B1 | **Silent variant substitution.** A gene-only query (`TP53`) picks the first ClinVar record that mentions the gene and presents it as the variant (verification/04_negative.txt shows `TP53` → `p.His214fs`). `RealDataPipeline.resolve_variant_record` also falls back to `records[0]`. | `graph.py::_pick_record`, `real_pipeline.py:~205` | Critical (scientific integrity) |
| B2 | **Traverse, Best path and Search buttons operate on the wrong graph.** `/api/traverse`, `/api/path`, `/api/search`, `/api/stats` read the static `data/canonical/quick_graph.json`, not the analysis on screen. "Best path" targets an `effect` node type that is never produced. | `main.py::_current_graph` | Critical (UI controls do not do what they advertise) |
| B3 | No evidence overlay: edges have no PubMed IDs, abstracts, methods or evidence category. The PPT's headline feature is absent. | `graph.py::_provenance` | Critical |
| B4 | No protein-level mapping: the variant is never mapped to a UniProt residue, domain or functional site, and the reference residue is never checked. | — | High |
| B5 | ClinVar classification handling discards information: only the first non-empty of germline / somatic impact / oncogenicity is kept; submissions, review status, conditions, origin and conflicts are not retrieved. Output often shows `source_recorded`. | `clinvar_service.py::extract_clinical_significance` | High |
| B6 | No VEP: transcript consequence, HGVS, SIFT/PolyPhen are not retrieved, even though Ensembl is "integrated" (only a gene lookup). | `ensembl_service.py` | High |
| B7 | "Downstream" consists of the first four `containedEvents` of each pathway, unrelated to the protein of interest; edges are labelled `CONTAINS` with an evidence summary but no record of whether the protein takes part in that reaction. | `reactome_service.py::fetch_reactions_for_pathway` | High |
| B8 | No diseases, drugs, interactions, literature, Open Targets or CIViC. `candidate_drugs` is always `[]`. | — | High |
| B9 | No per-source status: any exception in Ensembl or UniProt aborts the whole analysis with `not_resolved`, destroying data already retrieved from ClinVar. | `graph.py::analyze` try/except blocks | High |
| B10 | No input-type detection: rsIDs, HGVS c./g., VCV accessions and protein accessions are not supported; `normalize()` extracts the first capitalised word as the gene, so `rs121434568` or `NM_005228.5:c.2573T>G` produce nonsense. `L858R` without a gene is rejected without explanation. | `variant_resolver.py` | High |
| B11 | Gene-symbol ambiguity is unhandled: UniProt `gene:` search is used with `hits[0]`, which can return a different or unreviewed entry. | `uniprot_service.py` | Medium |
| B12 | No caching, rate limiting, timeouts or retries: NCBI's 3 requests/s limit can be exceeded; repeated demos hit public APIs every time. `PATHWAYGPS_OFFLINE` reads cache files that nothing writes in the normal flow. | services | Medium |
| B13 | Interactive graph features missing: no expand-node, filter by source/type/evidence, hide secondary edges, path highlighting from the variant, or search within the current graph. | `App.tsx` | High |
| B14 | No export, report, snapshot, comparison, conflict or gap view, hypothesis notes. | — | Medium |
| B15 | Duplicated, dead or misleading code: `real_pipeline.py` duplicates `graph.py`; `neo4j_client.py` and docker-compose are unused; `graph_backend.py` serves stale demo data to live endpoints; `seed_data/egfr_seed.json` is unused; `scoring.py` returns a "confidence" that is 1.0 for every edge because no edge has an `evidence_score`. | — | Medium |
| B16 | Metadata is hard-coded: every source reports `version: "unknown"` although the APIs expose release numbers (Reactome 97, Ensembl 116, UniProt 2026_03, ClinVar build date). | `graph.py::_source_metadata` | Low |

## 4. Scientific and data-integration limitations

* Gene-only queries are treated as variants (B1) — the most serious integrity problem.
* `PARTICIPATES_IN` is used both for protein→pathway membership (curated) and pathway→reaction containment (structural), with the same "database_fact" label; there is no distinction between curated, experimental, computational and inferred evidence.
* No distinction between germline and somatic classifications; ClinVar's three classification types are collapsed.
* Reaction nodes are not linked to the queried protein, so the graph implies downstream involvement it has not established.
* KEGG is correctly not integrated (licensing), but no outbound link is provided.
* `path_confidence` is presented as a "confidence" with no definition; it is constant.

## 5. UI/UX deficiencies

* Single-page, single-file component; no landing or explanation; no sample queries.
* Graph is a fixed vertical layered layout with 205 px nodes; with 30+ pathways it becomes an unreadable horizontal strip.
* Node detail shows only database, accession and retrieval time; no biology (function, domain, consequence).
* Legend lists node colours only; edges are coloured by source but this is not explained.
* Error states: one generic red banner; the not-resolved state is just "not resolved / insufficient source data" with no explanation of why or what to do.
* Header stats (NODES/EDGES) come from the static demo graph, not the current analysis.

## 6. Improvement plan (ordered by impact)

1. **Correct the resolution pipeline** (B1, B4, B10, B11): typed input detection; ClinVar + Ensembl VEP + UniProt resolution with residue validation, explicit ambiguity and alternative-record reporting; gene-level mode that never invents a variant.
2. **Source-adapter layer with an async HTTP client** (B9, B12, B16): timeouts, bounded retries, per-host rate limits (NCBI ≤3 rps without key), memory + disk cache, offline replay mode, per-source status and release metadata.
3. **Canonical model + evidence ledger** (B3, B5, B7): typed entities and edges; every edge carries one or more evidence records with source, record URL, PMIDs, category (curated / experimental / computational / inferred), source classification, review status, retrieval time and PathwayGPS inference notes.
4. **Expand integrations** (B5, B6, B8): ClinVar submissions (SCV level), VEP consequences, UniProt features, Reactome pathways/reactions/participants/literature/following-events/IntAct interactors, PubMed metadata and abstracts, Open Targets associations and drug mechanisms, CIViC evidence items.
5. **Rebuild the graph workspace** (B2, B13): Cytoscape.js (needed for automatic layouts, selectors-based filtering and graph algorithms at 100+ nodes; React Flow is retained nowhere else, so the swap removes one dependency and adds one), analysis-scoped endpoints for expansion and path explanation.
6. **Scientific UI**: landing with samples, variant overview, evidence explorer, conflict and gap explorer, impact summary, source status, literature explorer.
7. **Differentiators**: variant comparison, Markdown/HTML/JSON report export, reproducible snapshots, hypothesis workbench, grounded synthesis (rule-based by default, optional LLM with citation validation), Reactome gene-list enrichment used correctly.
8. **Clean-up**: remove the static-graph endpoints and dead code paths from the request flow (files kept where harmless), tests for resolver/graph/evidence invariants, updated README.

The existing stack (FastAPI + React + Vite + Tailwind, Python 3.9 venv) is kept.
Neo4j stays optional and unused: the per-analysis graphs are small (≤ a few
hundred nodes), so an in-memory model is the smallest sound design.
