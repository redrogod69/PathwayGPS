# PathwayGPS architecture

## Request flow

```
POST /api/analyze {query}
  └─ VariantResolver.resolve            pipeline/resolver.py
       parse_query (domain/notation)     → input type
       Ensembl lookup / alias xrefs      → gene (ambiguity → candidates)
       UniProt reviewed entry            → protein, reference-residue check      (speculatively in parallel with Ensembl)
       ClinVar esearch/esummary          → exact records only; alternatives listed
       VEP (region from SPDI / HGVS / rsID)  (deferred: runs in parallel with the builder)
  └─ AnalysisBuilder.build               pipeline/builder.py
       concurrent: ClinVar VCV submissions · Reactome pathways/reactions · IntAct · Open Targets · CIViC · releases
       graph: variant → gene → protein → UniProt features → Reactome mutant entity → pathways → reactions → following events → outputs
              + diseases (ClinVar, CIViC, Open Targets; merged only on shared ontology IDs) + drugs (CIViC, ClinVar, ChEMBL MoA)
  └─ PubMed esummary for cited PMIDs
  └─ insights: conflicts, gaps, impact summary, explainable paths, deterministic evidence-cited summary
  └─ payload (graph + evidence ledger + overview + per-source status) stored in memory under analysis_id
```

Follow-up endpoints act on the stored analysis: `/expand` (pathway reactions, downstream events, entity consumers, all
pathways), `/path`, `/report`, `/export/graph`, `/snapshot`, `/synthesis`. `/compare`, `/literature/search`,
`/publications/{pmid}/abstract`, `/enrichment` and `/snapshots*` are stateless helpers.

## Data model (`domain/model.py`)

* **Node**: `id`, `type` (variant, gene, protein, protein_region, reactome_entity, pathway, reaction, physical_entity,
  interactor, disease, drug), `label`, `source`, `xrefs[]` (original identifiers + URLs), `attributes`, `role`, `secondary`, `flags`.
* **Edge**: typed relationship (`VARIANT_IN_GENE`, `GENE_ENCODES_PROTEIN`, `VARIANT_ALTERS_PROTEIN`, `VARIANT_IN_PROTEIN_REGION`,
  `PROTEIN_HAS_REGION`, `VARIANT_REPRESENTED_AS`, `MUTANT_ENTITY_IN_PATHWAY`, `PROTEIN_PARTICIPATES_IN_PATHWAY`,
  `PROTEIN_PARTICIPATES_IN_REACTION`, `REACTION_PART_OF_PATHWAY`, `REACTION_PRECEDES`, `REACTION_PRODUCES`,
  `ENTITY_INPUT_OF_REACTION`, `PROTEIN_INTERACTS_WITH_PROTEIN`, `VARIANT_ASSOCIATED_WITH_CONDITION`,
  `VARIANT_PREDICTIVE_FOR_THERAPY`, `TARGET_ASSOCIATED_WITH_DISEASE`, `DRUG_TARGETS_PROTEIN`), `evidence[]` (IDs into the
  ledger), `category` (best supporting category) and `categories`.
* **Evidence**: one source assertion — see the field list in the README. Categories: curated, experimental, association,
  computational, inferred, hypothesis. An edge cannot be created without evidence and both endpoints.

Evidence strength (category), source scores (IntAct MI-score, Open Targets association score, CIViC rating, SIFT/PolyPhen),
clinical classifications (ClinVar, CIViC level/significance) and graph relevance (display order, path rank) are stored in
separate fields and never combined into one number.

## Path ranking (`pipeline/insights.py`)

`cost = Σ (1 + penalty[best category of the edge])` with penalties curated 0, experimental 0.1, association 0.25,
computational 0.3, inferred 0.5, hypothesis 0.9, minus 0.001 per supporting record (tie-break). Because every penalty
is < 1, shorter paths always win. The verdict reports the weakest category on the chosen path. It is a navigation aid,
not a probability.

## Display limits (`pipeline/builder.py`)

12 pathways initially (gene-named first, then disease pathways when the variant has a pathogenic/oncogenic/somatic
classification, then Reactome order; pathways containing the variant's curated entity are always shown), a cascade of
≤6 reactions × ≤3 following events for one focus pathway, ≤10 IntAct partners (MI ≥ 0.6, hidden by default), ≤6 Open
Targets diseases and drugs, ≤8 CIViC therapies, and diseases beyond the 12 best-supported hidden as secondary.
Everything hidden is one click away; nothing is dropped silently.

## Reliability

`core/http.py` enforces per-source rate limits (NCBI shared limiter 3 req/s, 10 with key), concurrency caps, timeouts,
two bounded retries on 429/5xx/network errors (honouring `Retry-After`), a memory LRU and on-disk cache (TTL 7 days), a
stale-cache fallback (labelled), and offline replay. Every call is recorded per analysis and summarised as per-source
status (ok / partial / failed). Any adapter failure is caught at the builder boundary so other sources still contribute.

## Not used

Neo4j: per-analysis graphs are tens to a few hundred nodes; an in-memory model is simpler and sufficient. The original
Neo4j client and docker-compose file are kept in `legacy/`.
