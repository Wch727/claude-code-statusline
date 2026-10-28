import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import time

import statusline_store as store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def catalog(self, input_price=2):
        return {'openai': {'models': {'demo': {'id': 'demo', 'name': 'Demo',
                'cost': {'input': input_price, 'output': 10, 'cache_read': 0.2}}}}}

    def test_sync_updates_usd_but_preserves_native_peak_and_manual_prices(self):
        base = {'demo': {'currency': 'USD', 'input': 1, 'output': 5},
                'native': {'currency': 'CNY', 'peak': {'input': 2}},
                'manual': {'currency': 'USD', 'input': 7, 'sync': False}}
        data = self.catalog()
        for name in ('native', 'manual'):
            data['openai']['models'][name] = {'id': name, 'cost': {'input': 99, 'output': 99}}
        snapshot = store.build_price_snapshot(data, base, lambda name, _: name, now=1000)
        merged = store.merge_online_prices(base, snapshot, lambda name, _: name)
        self.assertEqual(merged['demo']['input'], 2)
        self.assertEqual(merged['native'], base['native'])
        self.assertEqual(merged['manual'], base['manual'])
        self.assertEqual(merged['demo']['currency'], 'USD')

    def test_invalid_remote_catalog_does_not_replace_last_good_snapshot(self):
        path = self.root / 'prices.json'
        path.write_text('{"keep":1}')
        with self.assertRaises(ValueError):
            store.sync_prices({}, lambda name, _: name, path, fetcher=lambda: {'openai': {'models': {}}})
        self.assertEqual(json.loads(path.read_text()), {'keep': 1})

    def test_unchanged_sync_reports_no_fake_updates(self):
        path = self.root / 'prices.json'
        base = {'demo': {'input': 1, 'output': 5}}
        store.sync_prices(base, lambda name, _: name, path, fetcher=self.catalog)
        summary = store.sync_prices(base, lambda name, _: name, path, fetcher=self.catalog)
        self.assertEqual((summary['updated'], summary['added']), (0, 0))

    def test_truncated_remote_json_is_retried_once(self):
        with patch.object(store, '_fetch_catalog_once', side_effect=[ValueError('truncated'), self.catalog()]):
            self.assertEqual(store.fetch_catalog(), self.catalog())

    def test_total_fetch_deadline_bounds_slow_dns_or_download(self):
        def stalled():
            time.sleep(0.5)
            return self.catalog()
        with patch.object(store, '_fetch_catalog_once', side_effect=stalled):
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                store.fetch_catalog(timeout=0.03)
            self.assertLess(time.monotonic() - start, 0.4)

    def test_missing_long_context_tier_does_not_erase_local_tier(self):
        base = {'demo': {'currency': 'USD', 'input': 1, 'long_threshold': 200,
                         'long': {'input': 2}}}
        snapshot = store.build_price_snapshot(self.catalog(), base, lambda name, _: name)
        self.assertEqual(store.merge_online_prices(base, snapshot, lambda name, _: name)['demo'], base['demo'])

    def row(self, cost=2, tokens=1000000):
        return {'request_key': 'message-1', 'session_key': 'session-a',
                'timestamp': '2026-10-27T02:00:00+00:00', 'model': 'demo', 'raw_model': 'Demo',
                'segment': 'peak', 'currency': 'CNY', 'tokens': {'input': tokens, 'output': 0},
                'rates': {'input': cost}, 'cost': tokens / 1e6 * cost,
                'source': 'curated', 'unpriced_reason': ''}

    def test_request_rows_deduplicate_and_keep_original_rate_after_sync(self):
        db = self.root / 'usage.sqlite3'
        store.record_requests(db, [self.row()])
        store.record_requests(db, [self.row(cost=99)])
        rows = store.read_requests(db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['cost'], 2)
        self.assertEqual(rows[0]['rates']['input'], 2)

    def test_later_usage_snapshot_recomputes_cost_with_original_price(self):
        db = self.root / 'usage.sqlite3'
        store.record_requests(db, [self.row()])
        store.record_requests(db, [self.row(cost=99, tokens=2000000)])
        row = store.read_requests(db)[0]
        self.assertEqual(row['cost'], 4)
        self.assertEqual(row['tokens']['input'], 2000000)

    def test_previously_unpriced_row_can_be_priced_after_sync(self):
        db = self.root / 'usage.sqlite3'
        missing = self.row();missing.update(cost=None, rates={}, unpriced_reason='价格未配置')
        store.record_requests(db, [missing])
        store.record_requests(db, [self.row()])
        self.assertEqual(store.read_requests(db)[0]['cost'], 2)

    def test_ledger_does_not_keep_prompts_or_claim_a_provider(self):
        db = self.root / 'usage.sqlite3'
        row = self.row();row['prompt'] = 'PRIVATE CONTENT'
        store.record_requests(db, [row])
        saved = store.read_requests(db)[0]
        self.assertNotIn('prompt', saved)
        self.assertEqual(saved['provider'], '会话日志')

    def test_report_escapes_embedded_json(self):
        html = store.report_html([dict(self.row(), model='</script><script>alert(1)</script>')], {})
        self.assertNotIn('</script><script>alert(1)</script>', html)
        self.assertIn('请求日志', html)


if __name__ == '__main__':
    unittest.main()
