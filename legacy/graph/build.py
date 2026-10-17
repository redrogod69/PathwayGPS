from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    canonical_path = repo_root / 'data' / 'canonical' / 'quick_graph.json'
    payload = {'genes_loaded': 0, 'proteins_loaded': 0, 'pathways_loaded': 0, 'reactions_loaded': 0, 'variants_loaded': 0, 'relationships_loaded': 0, 'status': 'no_data'}
    if canonical_path.exists():
        with canonical_path.open('r', encoding='utf-8') as handle:
            real_data = json.load(handle)
        payload = {
            'genes_loaded': len(real_data.get('genes', [])),
            'proteins_loaded': len({item.get('protein_accession') for item in real_data.get('genes', []) if item.get('protein_accession')}),
            'pathways_loaded': len({item.get('source_id') for item in real_data.get('relationships', []) if item.get('relationship') == 'PARTICIPATES_IN'}),
            'reactions_loaded': 0,
            'variants_loaded': len(real_data.get('variants', [])),
            'relationships_loaded': len(real_data.get('relationships', [])),
            'status': 'real_data_loaded',
        }
    (repo_root / 'data' / 'metadata').mkdir(parents=True, exist_ok=True)
    (repo_root / 'data' / 'metadata' / 'build_summary.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print(json.dumps(payload, indent=2))


if __name__ == '__main__':
    main()
