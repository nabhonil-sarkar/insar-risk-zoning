"""Bounded metadata-only retrieval for the exploratory Day 1 access check."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/output/building_change_explore_v1'


def retrieve(url, name, max_bytes=5_000_000):
    """Meter bodies, including failed/partial reads; never fetch raster pixels."""
    if not name.endswith(('.json', '.ipynb', '.csv', '.html')):
        raise ValueError('Metadata/documentation files only')
    ledger_path = OUT / 'resource_accounting.json'
    ledger = json.loads(ledger_path.read_text())
    used = ledger['measured_response_body_bytes'] + ledger['unmetered_web_documentation_allowance_bytes']
    if used + max_bytes > ledger['cap_bytes']:
        raise RuntimeError('Download cap would be exceeded')
    target = OUT / name
    if target.exists():
        raise FileExistsError(target)
    record = {'url': url, 'name': name, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'body_bytes': 0, 'complete': False}
    try:
        request = urllib.request.Request(url, headers={'Accept-Encoding': 'identity'})
        with urllib.request.urlopen(request, timeout=45) as response, target.open('xb') as dest:
            record['status'] = response.status
            record['etag'] = response.headers.get('ETag')
            record['generation'] = response.headers.get('x-goog-generation')
            length = response.headers.get('Content-Length')
            if length and int(length) > max_bytes:
                raise RuntimeError('Metadata body exceeds per-request bound')
            while record['body_bytes'] < max_bytes:
                chunk = response.read(min(65536, max_bytes - record['body_bytes']))
                if not chunk:
                    record['complete'] = True
                    break
                record['body_bytes'] += len(chunk)
                dest.write(chunk)
            if not record['complete']:
                raise RuntimeError('Response reached byte limit; marked incomplete')
        record['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    except Exception as exc:
        record['error'] = str(exc)
        raise
    finally:
        ledger['measured_response_body_bytes'] += record['body_bytes']
        ledger['requests'].append(record)
        ledger_path.write_text(json.dumps(ledger, indent=2) + '\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('name')
    parser.add_argument('--max-bytes', type=int, default=5_000_000)
    args = parser.parse_args()
    print(json.dumps(retrieve(args.url, args.name, args.max_bytes), indent=2))
