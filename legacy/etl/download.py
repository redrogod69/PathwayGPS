from __future__ import annotations

import argparse
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
backend_root = repo_root / 'backend'
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.services.real_pipeline import RealDataPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description='Download a real-data source for PathwayGPS')
    parser.add_argument('dataset', choices=['reactome', 'uniprot', 'ensembl', 'clinvar', 'kegg', 'all'])
    args = parser.parse_args()
    pipeline = RealDataPipeline(repo_root)
    if args.dataset == 'all':
        pipeline.run_quick()
    else:
        module_map = {
            'reactome': lambda: pipeline.reactome.cache_pathways(),
            'uniprot': lambda: pipeline.uniprot.cache_gene('EGFR'),
            'ensembl': lambda: pipeline.ensembl.cache_gene('EGFR'),
            'clinvar': lambda: pipeline.clinvar.cache_variant('EGFR', 'L858R'),
            'kegg': lambda: {'status': 'not_configured_yet', 'source': 'KEGG'},
        }
        print(module_map[args.dataset]())


if __name__ == '__main__':
    main()
