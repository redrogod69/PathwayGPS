# Data licensing and attribution

| Source | Licence / terms | How PathwayGPS uses it |
|---|---|---|
| ClinVar (NCBI) | Public data; NCBI E-utilities usage policy (≤3 req/s without API key, `tool`/`email` parameters) — https://www.ncbi.nlm.nih.gov/books/NBK25497/ | Live queries, cached; submissions preserved individually |
| PubMed (NCBI) | Citation metadata public; abstracts may be under publisher copyright | Metadata cached; abstracts fetched only on user request, shown with a PubMed link, never written to exports |
| Ensembl REST / VEP | Open, no restrictions; fair-use rate limits | Live queries, cached |
| UniProtKB | CC BY 4.0 — attribute UniProt | Live queries, cached; entry links kept |
| Reactome | Data CC0; diagrams/icons CC BY 4.0 — https://reactome.org/license | Live queries, cached; links to Pathway Browser. The Reactome Functional Interaction network (contains restricted KEGG-derived data) is not used |
| IntAct (via Reactome static interactors) | CC BY 4.0 | Live queries, cached; IntAct evidence links kept |
| Open Targets Platform | CC0 1.0 (upstream sources retain own licences) — https://platform-docs.opentargets.org/licence | Live GraphQL queries, cached |
| CIViC | CC0 1.0 | Live GraphQL queries, cached |
| KEGG | Academic web use free; API/data require a licence for commercial use or redistribution — https://www.kegg.jp/kegg/legal.html | **Not integrated.** Outbound link only |
| Claude API (optional) | Anthropic terms | Server-side only, disabled unless `ANTHROPIC_API_KEY` is set; receives only the retrieved evidence ledger |

The recorded replay fixtures in `backend/tests/fixtures/replay` contain responses from the sources above (no KEGG data,
no PubMed abstracts). Review each source's current terms before commercial redistribution.
