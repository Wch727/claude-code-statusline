"""Public price snapshots and a local per-request usage ledger (stdlib only)."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import urllib.request
from ccswitch_compat import (calculate_cost, flatten_models, resolve_models_dev_selection)

PRICE_URL = 'https://models.dev/api.json'
OFFICIAL_PROVIDERS = {
    'anthropic': 'anthropic', 'openai': 'openai', 'google': 'google', 'xai': 'xai',
    'deepseek': 'deepseek', 'alibaba': 'qwen', 'moonshotai': 'moonshot',
    'minimax': 'minimax', 'minimax-cn': 'minimax', 'zhipuai': 'zhipu', 'zai': 'zhipu',
    'xiaomi': 'xiaomi', 'stepfun': 'stepfun', 'tencent': 'tencent', 'longcat': 'longcat',
}


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {} if default is None else default


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as f:
            name = f.name
            json.dump(value, f, ensure_ascii=False, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _price(value):
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError('invalid unit price')
    return result


def build_price_snapshot(data, base, resolver, now=None):
    if not isinstance(data, dict):
        raise ValueError('models.dev response is not an object')
    prices = {}
    invalid = 0
    entries = flatten_models(data)
    selected = {e['key'] for e in resolve_models_dev_selection(entries, base.get('_sync', {}))}
    for flat in entries:
        provider, raw_id, model = flat['providerId'], flat['modelId'], flat['rawModel']
        vendor = OFFICIAL_PROVIDERS.get(provider)
        if not vendor:
            continue
        if flat['key'] not in selected and resolver(raw_id, base) not in base:
            continue
        # Adapted CC Switch selection/conversion; extend it with native tariff guards.
        try:
            cost = model['cost']
            entry = {'currency': 'USD', 'provider': vendor,
                     'input': _price(cost['input']), 'output': _price(cost['output']),
                     'source': 'models.dev', 'source_provider': provider, 'source_model': raw_id}
            for field in ('cache_read', 'cache_write'):
                if field in cost:
                    entry[field] = _price(cost[field])
            # Omitted cache write means this category is not priced by this
            # source; do not invent the input-price surcharge.
            entry.setdefault('cache_write', 0)
            entry.setdefault('cache_read', 0)
            tiers = [t for t in cost.get('tiers', [])
                     if t.get('tier', {}).get('type') == 'context']
            if len(tiers) == 1:
                tier = tiers[0]
                entry['long_threshold'] = int(tier['tier']['size'])
                entry['long'] = {k: _price(tier.get(k, entry.get(k, 0)))
                                 for k in ('input', 'output', 'cache_read', 'cache_write')}
            elif len(tiers) > 1:
                # A two-tier renderer cannot represent a multi-tier tariff.
                invalid += 1
                continue
            name = str(model.get('name') or raw_id)
            entry['aliases'] = [raw_id, name]
            canonical = resolver(raw_id, base)
            # A gateway's copy must not replace a different manufacturer's entry.
            local_vendor = base.get(canonical, {}).get('provider')
            if local_vendor and local_vendor != vendor:
                continue
            if canonical in prices and prices[canonical]['source_provider'] != provider:
                continue
            prices[canonical] = entry
        except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
            invalid += 1
    if not prices:
        raise ValueError('models.dev returned no usable official model prices')
    return {'version': 1, 'synced_at': time.time() if now is None else now,
            'source_url': PRICE_URL, 'prices': prices, 'invalid_entries': invalid}


def merge_online_prices(base, snapshot, resolver):
    result = deepcopy(base)
    if not isinstance(snapshot, dict) or snapshot.get('version') != 1:
        return result
    for raw_id, remote in snapshot.get('prices', {}).items():
        key = resolver(raw_id, result)
        local = result.get(key, {})
        if (local.get('sync') is False or local.get('currency', 'USD').upper() != 'USD'
                or any(k in local for k in ('peak', 'offpeak', 'legacy', 'revisions'))
                or ('long' in local and 'long' not in remote)):
            continue
        combined = {**local, **deepcopy(remote)}
        combined['aliases'] = sorted(set(local.get('aliases', []) + remote.get('aliases', []) + [raw_id]))
        result[key] = combined
    return result


def _fetch_catalog_once():
    req = urllib.request.Request(PRICE_URL, headers={'User-Agent': 'claude-code-statusline/1.0'})
    with urllib.request.urlopen(req, timeout=10) as response:
        raw = response.read(30_000_001)
    if len(raw) > 30_000_000:
        raise ValueError('price response exceeds 30 MB')
    return json.loads(raw)


def fetch_catalog(timeout=15):
    # CC Switch's browser fetch uses AbortController with a 15-second total
    # timeout. urllib's socket timeout does not bound DNS or the whole download;
    # a daemon worker provides that total deadline without blocking rendering.
    import queue
    import threading
    error = None
    for _ in range(2):
        result = queue.Queue(maxsize=1)
        def worker(destination=result):
            try:
                destination.put((True, _fetch_catalog_once()))
            except Exception as exc:
                destination.put((False, exc))
        threading.Thread(target=worker, daemon=True).start()
        try:
            ok, value = result.get(timeout=timeout)
            if ok:
                return value
            error = value
        except queue.Empty:
            error = TimeoutError(f'models.dev exceeded {timeout:g}s total timeout')
    raise error


def sync_prices(base, resolver, path, fetcher=None):
    path = Path(path)
    status_path = path.with_name('price_sync_status.json')
    try:
        snapshot = build_price_snapshot((fetcher or fetch_catalog)(), base, resolver)
        effective = merge_online_prices(base, snapshot, resolver)
        previous = read_json(path)
        before = merge_online_prices(base, previous, resolver)
        candidates = set(snapshot['prices'])
        protected = [k for k in candidates if k in base and effective.get(k) == base[k]]
        snapshot['summary'] = {'received': len(candidates), 'protected': len(protected),
                               'added': sum(k not in before for k in effective if not k.startswith('_')),
                               'updated': sum(k in before and effective[k] != before[k]
                                              for k in effective if not k.startswith('_')),
                               'invalid': snapshot['invalid_entries']}
        if previous:
            atomic_json(path.with_suffix('.previous.json'), previous)
        atomic_json(path, snapshot)
        atomic_json(status_path, {'last_attempt': time.time(), 'last_success': snapshot['synced_at'],
                                  'summary': snapshot['summary'], 'error': None})
        return snapshot['summary']
    except Exception as exc:
        status = read_json(status_path)
        status.update(last_attempt=time.time(), error=f'{type(exc).__name__}: {exc}')
        atomic_json(status_path, status)
        raise


def _amount(tokens, rates):
    return calculate_cost(tokens, rates)['cost']


def record_requests(db, requests):
    if not requests:
        return
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db, timeout=5)) as con, con:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('''CREATE TABLE IF NOT EXISTS requests (
            session_key TEXT NOT NULL, request_key TEXT NOT NULL, timestamp TEXT NOT NULL,
            model TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(session_key,request_key))''')
        con.execute('CREATE INDEX IF NOT EXISTS requests_time ON requests(timestamp)')
        for request in requests:
            # Whitelist billing metadata. Never retain prompt, response, keys or headers.
            row = {key: request.get(key) for key in (
                'request_key', 'session_key', 'timestamp', 'model', 'raw_model', 'segment',
                'currency', 'tokens', 'rates', 'cost', 'source', 'unpriced_reason', 'price_entry')}
            for key in ('latency_ms', 'first_token_ms', 'timestamp_source', 'response_timestamp'):
                if key in request:
                    row[key] = request[key]
            row.update(provider='会话日志', app='Claude Code', price_captured_at=time.time(),
                       timestamp_source=row.get('timestamp_source') or '会话记录')
            if not row['timestamp']:
                row['timestamp'] = datetime.now(timezone.utc).isoformat()
                row['timestamp_source'] = '导入时间（记录未提供时间）'
            try:
                ts = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                row['timestamp'] = ts.astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                row['timestamp'] = datetime.now(timezone.utc).isoformat()
                row['timestamp_source'] = '导入时间（原时间无效）'
            existing = con.execute('SELECT payload FROM requests WHERE session_key=? AND request_key=?',
                                   (row['session_key'], row['request_key'])).fetchone()
            if existing:
                previous = json.loads(existing[0])
                if previous['cost'] is not None:
                    updated_tokens = row['tokens']
                    row = previous
                    row['tokens'] = updated_tokens
                    for field in ('latency_ms', 'first_token_ms'):
                        if request.get(field) is not None:
                            row[field] = request[field]
                    # Later streaming snapshots keep the original tariff, even
                    # if an online refresh happened in between snapshots.
                    entry = row.get('price_entry') or {}
                    if 'long' in entry:
                        prompt = sum(updated_tokens.get(k, 0) for k in ('input', 'cache_read', 'cache_write'))
                        row['segment'] = 'long' if prompt > entry['long_threshold'] else 'short'
                        row['rates'] = dict(entry['long'] if row['segment'] == 'long' else entry)
                        if entry.get('provider') == 'anthropic':
                            row['rates'].setdefault('cache_write_1h', row['rates'].get('input', 0) * 2)
                    row['cost'] = _amount(updated_tokens, row['rates'])
                elif row['cost'] is None:
                    row['timestamp'] = previous['timestamp']
                    row['price_captured_at'] = previous['price_captured_at']
            con.execute('INSERT OR REPLACE INTO requests VALUES(?,?,?,?,?)',
                        (row['session_key'], row['request_key'], row['timestamp'], row['model'],
                         json.dumps(row, ensure_ascii=False, allow_nan=False)))


def read_requests(db, limit=5000):
    path = Path(db)
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as con:
        try:
            return [json.loads(r[0]) for r in con.execute(
                'SELECT payload FROM requests ORDER BY timestamp DESC LIMIT ?', (limit,))]
        except sqlite3.OperationalError as exc:
            if 'no such table' in str(exc):
                return []
            raise


def session_costs(db, key):
    if not Path(db).exists():
        return None
    with closing(sqlite3.connect(db, timeout=5)) as con:
        rows = [json.loads(r[0]) for r in con.execute('SELECT payload FROM requests WHERE session_key=?', (key,))]
    if not rows:
        return None
    totals = {'USD': 0.0, 'CNY': 0.0}
    detail = {}
    for row in rows:
        model = row['model']
        d = detail.setdefault(model, {k: 0 for k in ('input', 'output', 'cache_read', 'cache_write',
                                                     'cost_in', 'cost_out', 'cost_cr', 'cost_cw')})
        d.setdefault('cost', None)
        d['currency'] = row['currency']
        for field in ('input', 'output', 'cache_read', 'cache_write'):
            d[field] += row['tokens'].get(field, 0)
        if row['cost'] is not None:
            d['cost'] = (d['cost'] or 0) + row['cost']
            totals[row['currency']] = totals.get(row['currency'], 0) + row['cost']
            amounts = calculate_cost(row['tokens'], row['rates'])
            for field in ('cost_in', 'cost_out', 'cost_cr', 'cost_cw'):
                d[field] += amounts[field]
        if row.get('unpriced_reason'):
            d['unpriced_reason'] = row['unpriced_reason']
    return totals['USD'], totals['CNY'], detail


def report_html(rows, status, token=''):
    template = Path(__file__).with_name('usage_report.html').read_text(encoding='utf-8')
    payload = json.dumps({'rows': rows, 'status': status, 'token': token}, ensure_ascii=False)
    payload = payload.replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    return template.replace('/*__INITIAL_DATA__*/', payload)


def serve_report(db, status_path, sync_callback, port=0):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import secrets
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, value, content_type='application/json; charset=utf-8', code=200):
            body = value.encode('utf-8') if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def allowed_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.allowed_host():
                return self.send({'error': 'Invalid host'}, code=403)
            if self.path == '/':
                return self.send(report_html(read_requests(db), read_json(status_path), token), 'text/html; charset=utf-8')
            if self.path == '/api/usage':
                return self.send({'rows': read_requests(db), 'status': read_json(status_path)})
            self.send({'error': 'Not found'}, code=404)

        def do_POST(self):
            if not self.allowed_host() or self.headers.get('X-Statusline-Token') != token:
                return self.send({'error': 'Invalid token'}, code=403)
            if self.path != '/api/sync':
                return self.send({'error': 'Not found'}, code=404)
            try:
                return self.send({'summary': sync_callback()})
            except Exception as exc:
                return self.send({'error': str(exc)}, code=502)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'Usage report: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
