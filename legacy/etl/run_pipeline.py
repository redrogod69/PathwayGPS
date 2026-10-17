from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
backend_root = repo_root / 'backend'
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.services.real_pipeline import RealDataPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='PathwayGPS ETL runner')
    parser.add_argument('--profile', choices=['quick', 'full'], default='quick')
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    pipeline = RealDataPipeline(repo_root)
    data = pipeline.run_quick() if args.profile == 'quick' else pipeline.run_quick()
    print(json.dumps({
        'profile': args.profile,
        'genes_loaded': len(data.get('genes', [])),
        'variants_loaded': len(data.get('variants', [])),
        'relationships_loaded': len(data.get('relationships', [])),
    }, indent=2))


if __name__ == '__main__':
    main()
