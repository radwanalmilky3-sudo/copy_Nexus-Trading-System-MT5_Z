"""Explicitly audit stored groups through the owner API, never opening its database."""
import argparse
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Persist audit reports (does not change market data)')
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    base = os.getenv('NEXUS_DATA_URL', 'http://127.0.0.1:9001').rstrip('/')
    headers = {'X-Nexus-Internal-Secret': os.environ['NEXUS_INTERNAL_API_SECRET']}
    with httpx.Client(timeout=60, trust_env=False) as client:
        datasets = []
        offset = 0
        while True:
            response = client.post(base + '/api/data/query', headers=headers, json={
                'operation': 'research_collection', 'params': dict(resource='datasets', limit=100, offset=offset, query=None)})
            response.raise_for_status()
            page, = response.json()['rows']
            if page['status'] != 'available':
                raise RuntimeError('Stored dataset catalog unavailable')
            datasets.extend(page['items'])
            offset += len(page['items'])
            if not page['items'] or offset >= page['total']:
                break
        for dataset in datasets:
            prefix, symbol, timeframe, source = dataset['dataset_id'].split(':', 3)
            if prefix != 'ohlcv':
                raise ValueError('Unexpected dataset identity')
            if not args.run:
                print('DRY_RUN', dataset['dataset_id'], dataset['row_count'])
                continue
            response = client.post(base + '/api/data/research/quality', headers=headers,
                                   json=dict(symbol=symbol, timeframe=timeframe, source=source))
            response.raise_for_status()
            report = response.json()
            print(json.dumps({key: report[key] for key in ('quality_run_id', 'dataset_id', 'status', 'rows_checked',
                'content_hash', 'checks', 'issues', 'warnings', 'metrics', 'checked_at', 'scope')}, ensure_ascii=True), flush=True)
        print('GROUPS', len(datasets), 'REPORTS_PERSISTED' if args.run else 'DRY_RUN_ONLY')


if __name__ == '__main__':
    main()
