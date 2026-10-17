# PathwayGPS — Research Notes

All endpoints below were exercised live on 2026-10-17 from the development
machine (responses inspected, not assumed). Release numbers observed that day:
Reactome **97**, Ensembl **116** (GRCh38), UniProt **2026_03**, Open Targets
API **26.9.0** / data **26.09**, ClinVar build **Build260914**.

## 1. Which source provides what

| Need | Source and endpoint actually used | Nature of the data |
|---|---|---|
| Variant record, aggregate and per-submission classifications, conditions, review status, origin, citations | ClinVar via NCBI E-utilities: `esearch db=clinvar` (`GENE[gene] AND L858R[varname]`, rsID, HGVS, VCV), `esummary` (germline / somatic clinical impact / oncogenicity classifications, SPDI, GRCh38 location, dbSNP + UniProt VAR xrefs), `efetch rettype=vcv&is_variationid` (SCV submissions with submitter, classification, review status, origin, method, PubMed citations) | Curated submissions; aggregate classifications are ClinVar's computation over submissions |
| Transcript consequence, HGVS, protein position, SIFT, PolyPhen | Ensembl VEP REST: `/vep/human/region/{chr}:{pos}-{pos}:1/{alt}`, `/vep/human/hgvs/{transcript-hgvs}`, `/vep/human/id/{rsid}` with `canonical, mane, hgvs, uniprot, numbers, variant_class, protein` | Consequence = rule-based annotation against Ensembl gene models; SIFT/PolyPhen = computational predictions |
| Gene identity, alias handling | Ensembl `/lookup/symbol/homo_sapiens/{symbol}`, `/xrefs/symbol/homo_sapiens/{alias}` (e.g. `HER2` → ENSG00000141736) | Reference annotation |
| Protein function, sequence, domains/sites, known variants, mutagenesis | UniProt REST `/uniprotkb/search?query=gene_exact:{sym} AND organism_id:9606 AND reviewed:true` with `cc_function, ft_domain, ft_region, ft_act_site, ft_binding, ft_mod_res, ft_motif, ft_topo_dom, ft_transmem, ft_variant, ft_mutagen, sequence, xref_reactome` | Swiss-Prot curated; each feature carries ECO evidence codes (ECO:0000269 experimental, ECO:0000255 sequence-model, ECO:0007744 combinatorial, ECO:0000250 by similarity) |
| Pathways, reactions, participants, ordering, literature | Reactome Content Service `/data/mapping/UniProt/{acc}/pathways` and `/reactions`, `/data/query/{stId}` (input, output, catalystActivity, regulatedBy, precedingEvent, literatureReference with PMIDs, summation, isInDisease, isInferred), `/data/query/{stId}/followingEvent`, `/data/query/ids` (POST), `/data/event/{stId}/ancestors`, `/data/pathway/{stId}/containedEvents` | Expert-curated; `isInferred=true` marks orthology-inferred events |
| Protein–protein interactions | Reactome `/interactors/static/molecule/{acc}/details` (IntAct static set, MI score, evidence count, IntAct URL) | Experimental interaction evidence (IntAct); not pathway-curated |
| Gene-list pathway analysis | Reactome Analysis Service `POST /AnalysisService/identifiers/projection` | Statistical over-representation — only meaningful for gene lists, never for one variant |
| Literature metadata and abstracts | NCBI `esummary db=pubmed`, `efetch db=pubmed retmode=xml`, `esearch db=pubmed` | Bibliographic; abstracts fetched on demand |
| Target–disease association, drug mechanisms | Open Targets GraphQL `target.associatedDiseases` (score + datatype scores), `target.drugAndClinicalCandidates` (replaced `knownDrugs`; MoA rows list the actual targets) | Association scores are aggregated evidence summaries (0–1), **not probabilities**; drug MoA from ChEMBL curation |
| Cancer variant clinical evidence | CIViC GraphQL `molecularProfiles(name:)`, `evidenceItems(molecularProfileId:, status: ACCEPTED)` | Curated evidence items with type, level (A–E), direction, significance, origin, PMID |

## 2. Identifier reconciliation (harmonisation strategy)

* **Variant**: ClinVar VariationID/VCV is the anchor when a record exists; GRCh38 SPDI → VEP region input; dbSNP rsID and UniProt `VAR_` xrefs are taken from ClinVar's own `variation_xrefs`; protein change normalised to both `p.L858R` and `p.Leu858Arg`.
* **Gene**: HGNC-approved symbol ↔ Ensembl gene ID via Ensembl lookup; alias symbols resolved through Ensembl xrefs and reported as a warning; multiple hits ⇒ ambiguity, never a guess.
* **Protein**: reviewed UniProt accession for the gene (`gene_exact:` + `reviewed:true`); the reference residue at the variant position is checked against the canonical sequence.
* **Pathways / reactions / entities**: Reactome stable IDs (`R-HSA-…`), linked from the UniProt accession.
* **Diseases**: ClinVar trait xrefs (MONDO, MedGen, MeSH, HPO), Open Targets IDs (MONDO/EFO with `dbXRefs`), CIViC DOID. Nodes are merged **only on a shared ontology identifier** (e.g. MONDO from ClinVar and Open Targets, DOID from CIViC and Open Targets `dbXRefs`); the merge is recorded on the node.
* **Drugs**: ChEMBL (Open Targets), NCIt (CIViC). Merged only on exact case-insensitive name equality, recorded on the node.

## 3. Curated vs predicted vs indirect

| Category in PathwayGPS | Examples |
|---|---|
| `curated` | Reactome reaction participation and event ordering, ClinVar submissions, UniProt features with experimental ECO codes, CIViC accepted evidence, ChEMBL drug mechanisms |
| `experimental` | IntAct interactions (via Reactome), UniProt mutagenesis annotations |
| `computational` | VEP consequence, SIFT, PolyPhen, UniProt features with ECO:0000255/0000256 |
| `association` | Open Targets target–disease scores (aggregate, gene-level) |
| `inferred` | Steps PathwayGPS derives itself — e.g. variant falls inside a UniProt feature (coordinate overlap), Reactome orthology-inferred events |
| `hypothesis` | User-marked hypotheses and optional AI suggestions; never rendered as evidence |

## 4. Reliability of public APIs (observed)

* ClinVar / PubMed E-utilities: fast (≈1 s); hard limit 3 req/s without key, 10 with `NCBI_API_KEY`. `tool` and `email` parameters are sent.
* Ensembl VEP: region and transcript-HGVS input answer in 3–10 s; **gene-symbol protein HGVS (`BRAF:p.Val600Glu`) and `variant_recoder` timed out or returned 503** — therefore protein-change input is resolved through ClinVar coordinates first, and the recoder is only a bounded fallback.
* Reactome Content Service: reliable (≈1.5 s). **Reactome search (Solr) returned HTTP 500 for every query** on the test date, so variant-specific Reactome entity lookup is optional and degrades gracefully.
* Open Targets GraphQL: reliable; schema changed (`knownDrugs` removed) — queries use the current schema.
* CIViC GraphQL: reliable (POST only; GET returns 404).

## 5. Licensing and attribution

| Source | Terms (summary) | Effect on PathwayGPS |
|---|---|---|
| ClinVar / NCBI | Public data; follow E-utilities usage policy (rate limits, `tool`/`email`) — [NCBI E-utilities guidelines](https://www.ncbi.nlm.nih.gov/books/NBK25497/) | Cache allowed; rate-limited client |
| PubMed abstracts | Bibliographic data is public, but abstracts may be under publisher copyright | Abstracts are fetched on demand for display with a PubMed link; they are **not** written into exported reports (titles/metadata only) |
| Ensembl | Open data, no restrictions; REST fair use (≈15 req/s) | Cache allowed |
| UniProt | CC BY 4.0 | Attribute UniProt; links kept |
| Reactome | Data CC0; illustrations CC BY 4.0 — [reactome.org/license](https://reactome.org/license). The Reactome FI network contains KEGG-derived, restricted data and is **not used** | Cache allowed; links to Pathway Browser |
| IntAct (via Reactome) | CC BY 4.0 | Attribute IntAct |
| Open Targets | CC0 1.0 (upstream sources keep their own licences) — [licence](https://platform-docs.opentargets.org/licence) | Cache allowed |
| CIViC | CC0 1.0 — [CIViC docs](https://civic.readthedocs.io/) | Cache allowed |
| KEGG | Academic web use free; API and data for commercial use or redistribution require a licence (Pathway Solutions) — [kegg.jp/kegg/legal.html](https://www.kegg.jp/kegg/legal.html) | **Not integrated.** Only an outbound link to the KEGG gene page is shown |

## 6. Smallest sound architecture

FastAPI backend with an async source-adapter layer (one module per source),
a shared HTTP client (timeouts, retries, per-host rate limits, memory + disk
cache, offline replay), a pure-Python graph builder producing a typed graph and
evidence ledger, and an in-memory analysis store plus JSON snapshots on disk.
React frontend renders the graph with Cytoscape.js. No graph database: each
analysis graph is tens to a few hundred nodes.

## 7. High-value features chosen

1. Residue validation against UniProt and mapping to annotated features (PPT slide 5, step 2).
2. Edge-level evidence ledger with PubMed metadata and on-demand abstracts (slide 5, "evidence overlay").
3. Reactome event-order traversal (`precedingEvent`/`followingEvent`) for downstream cascades with literature per reaction (slide 3 "cascade propagation").
4. Evidence conflict and gap explorer (ClinVar submission disagreements, CIViC opposing evidence, SIFT/PolyPhen disagreement).
5. Explainable path view from variant to any node, with per-hop evidence category.
6. Variant comparison, report export, snapshots, hypothesis workbench.
7. Optional grounded LLM synthesis whose claims must cite evidence-ledger IDs (validated server side); a deterministic summary is used when no key is configured.

## 8. Interpretation guidance applied

* ACMG/AMP (Richards et al. 2015, [PMC4544753](https://pmc.ncbi.nlm.nih.gov/articles/PMC4544753/)): computational predictions (PP3/BP4) are supporting-level evidence only; VUS must not drive clinical decisions. PathwayGPS shows SIFT/PolyPhen as computational, never as classification, and keeps VUS labelled as uncertain.
* Somatic (AMP/ASCO/CAP tiers, oncogenicity) and germline classifications are reported separately, as ClinVar does.
* Association ≠ mechanism: Open Targets edges are gene-level associations; CIViC predictive evidence is shown with disease context and is labelled "not a treatment recommendation".
