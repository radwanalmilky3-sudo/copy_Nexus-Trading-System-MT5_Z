"""Read-only live verification. Credentials, if supplied, stay out of output."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env', override=False)
    data_url = os.getenv('NEXUS_DATA_URL', 'http://127.0.0.1:9001').rstrip('/')
    api_url = os.getenv('NEXUS_CHECK_API_URL', 'http://127.0.0.1:9000').rstrip('/')
    with httpx.Client(timeout=30, trust_env=False) as client:
        health = client.get(f'{data_url}/health')
        health.raise_for_status()
        state = health.json()
        print('DATA', {key: state.get(key) for key in ('ready', 'mt5', 'data_mode', 'synthetic_fallback')})
        for resource in ('datasets', 'import_jobs', 'quality_runs', 'news', 'artifacts'):
            response = client.post(f'{data_url}/api/data/query',
                headers={'X-Nexus-Internal-Secret': os.environ['NEXUS_INTERNAL_API_SECRET']},
                json={'operation': 'research_collection', 'params': dict(resource=resource, limit=50, offset=0, query=None)})
            response.raise_for_status()
            result, = response.json()['rows']
            print('OWNER', resource, result['status'], result['source'], result['total'])
        for path in ('/api/research-lab/datasets', '/api/audit/progress'):
            response = client.get(api_url + path)
            assert response.status_code in (401, 403), (path, response.status_code)
        password = os.getenv('NEXUS_CHECK_PASSWORD')
        if not password:
            print('AUTHENTICATED_GATEWAY_CHECK skipped: no NEXUS_CHECK_PASSWORD')
            return
        login = client.post(api_url + '/api/v2/auth/login', json={
            'username': os.getenv('NEXUS_CHECK_USERNAME', 'ridwan'), 'password': password})
        login.raise_for_status()
        headers = {'Authorization': f"Bearer {login.json()['token']}"}
        for resource in ('datasets', 'import-jobs', 'quality-runs', 'strategies', 'backtests', 'news', 'artifacts'):
            response = client.get(f'{api_url}/api/research-lab/{resource}', headers=headers)
            response.raise_for_status()
            result = response.json()
            print('GATEWAY', resource, result['status'], result['source'], result['total'])
            if resource == 'datasets':
                for item in result['items']:
                    assert item['source'] and item['status'] == 'stored'
                if result['items']:
                    dataset_id = result['items'][0]['dataset_id']
                    detail = client.get(f'{api_url}/api/research-lab/datasets/{quote(dataset_id, safe="")}', headers=headers)
                    detail.raise_for_status()
                    assert detail.json()['item']['dataset_id'] == dataset_id
                    print('DATASET_EXACT_DETAIL_OK')
        response = client.get(api_url + '/api/audit/progress', headers=headers)
        response.raise_for_status()
        result = response.json()
        actual = hashlib.sha256((root / 'project_audit/DASHBOARD_STATE.json').read_bytes()).hexdigest()
        assert result['state']['sha256'] == actual
        print('AUDIT', result['status'], result['evidence']['count'], 'state_sha256_matches_disk=True')
        mode = client.get(api_url + '/api/system/mode', headers=headers)
        mode.raise_for_status()
        assert mode.json()['auto_trade'] is False
        print('AUTO_TRADE_DISABLED=True')


if __name__ == '__main__':
    main()
