import ast
import contextlib
import concurrent.futures
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).with_name('status-line.py')


def load_helpers():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.If) and 'sys.argv' in ast.unparse(node.test):
            break
        nodes.append(node)
    ns = {'__file__': str(SOURCE), '_re2': re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), ns)
    return ns


class StatusLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=SOURCE.parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ns = load_helpers()
        self.ns['USAGE_CACHE'] = str(self.root / 'usage.json')
        self.ns['USD_CNY_CACHE'] = str(self.root / 'fx.json')
        self.transcript = self.root / 'session.jsonl'

    def record(self, tokens=100, model='known'):
        return json.dumps({'type': 'assistant', 'message': {
            'model': model, 'usage': {'input_tokens': tokens, 'output_tokens': 20}}}) + '\n'

    def read(self):
        return self.ns['get_cumulative_usage'](str(self.transcript), {})

    def render(self, payload):
        (self.root / 'usd_cny.json').write_text(json.dumps({'ts': time.time(), 'rate': 7.1}))
        output = io.StringIO()
        with patch('sys.stdin', io.StringIO(json.dumps(payload))), patch('sys.argv', [str(SOURCE)]), \
                patch('os.path.expanduser', side_effect=lambda p: str(self.root / Path(p).name)), \
                patch.dict('os.environ', {'STATUSLINE_DISABLE_PRICE_SYNC': '1'}), contextlib.redirect_stdout(output):
            try:
                exec(compile(SOURCE.read_text(encoding='utf-8'), str(SOURCE), 'exec'), {'__file__': str(SOURCE)})
            except SystemExit as e:
                self.assertEqual(e.code, 0)
        return re.sub(r'\x1b\[[0-9;]*m', '', output.getvalue())

    def test_split_message_usage_counted_once_across_refreshes(self):
        rec = json.loads(self.record())
        rec['message']['id'] = 'same-api-message'
        self.transcript.write_text(json.dumps(rec)+'\n', encoding='utf-8')
        self.read()
        with self.transcript.open('a', encoding='utf-8') as f:
            f.write(json.dumps({**rec, 'uuid': 'different-content-block'})+'\n')
        usage = self.read()[0]['known']
        self.assertEqual(self.ns['_usage_total'](usage, 'input'), 100)
        self.assertEqual(self.ns['_usage_total'](usage, 'output'), 20)

    def test_same_message_updated_usage_replaces_previous_snapshot(self):
        rec = json.loads(self.record());rec['message']['id'] = 'streamed'
        self.transcript.write_text(json.dumps(rec)+'\n', encoding='utf-8')
        self.read()
        rec['message']['usage']['output_tokens'] = 35
        with self.transcript.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec)+'\n')
        usage = self.read()[0]['known']
        self.assertEqual(self.ns['_usage_total'](usage, 'input'), 100)
        self.assertEqual(self.ns['_usage_total'](usage, 'output'), 35)

    def test_cc_switch_finished_snapshot_wins_over_later_partial_block(self):
        rec = json.loads(self.record());rec['message'].update(id='one', stop_reason='end_turn')
        self.transcript.write_text(json.dumps(rec)+'\n', encoding='utf-8');self.read()
        rec['message'].update(stop_reason=None);rec['message']['usage']['output_tokens'] = 1
        with self.transcript.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec)+'\n')
        self.assertEqual(self.ns['_usage_total'](self.read()[0]['known'], 'output'), 20)

    def test_parent_chain_request_start_selects_peak_bucket_and_is_logged(self):
        parent = {'type': 'user', 'uuid': '00000000-0000-0000-0000-000000000001',
                  'timestamp': '2026-10-27T08:59:58+08:00'}
        rec = json.loads(self.record(1000000, 'deepseek-flash'))
        rec.update(uuid='00000000-0000-0000-0000-000000000002', parentUuid=parent['uuid'],
                   timestamp='2026-10-27T09:00:05+08:00')
        rec['message'].update(id='cross-boundary', stop_reason='end_turn')
        self.transcript.write_text(json.dumps(parent)+'\n'+json.dumps(rec)+'\n', encoding='utf-8')
        prices = {'deepseek-flash': {'currency': 'CNY', 'peak': {'input': 2}, 'offpeak': {'input': 1}}}
        usage = self.ns['get_cumulative_usage'](str(self.transcript), prices)[0]
        self.assertIn('offpeak', usage['deepseek-flash'])
        import statusline_store
        rows = statusline_store.read_requests(self.root / 'usage_ledger.sqlite3')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['segment'], 'offpeak')
        self.assertEqual(rows[0]['latency_ms'], 7000)

    def test_bad_transcript_record_does_not_repeat_earlier_usage(self):
        self.transcript.write_text(self.record()+'null\n'+self.record(50), encoding='utf-8')
        self.read()
        self.assertEqual(self.ns['_usage_total'](self.read()[0]['known'], 'input'), 150)

    def test_long_context_includes_cached_prompt_tokens(self):
        rec = json.loads(self.record(10, 'claude-haiku-5.5'))
        rec['message']['usage']['cache_read_input_tokens'] = 100000
        self.transcript.write_text(json.dumps(rec)+'\n', encoding='utf-8')
        prices = {'claude-haiku-5.5': {'input': 0.1, 'long_threshold': 100000, 'long': {'input': 0.5}}}
        usage = self.ns['get_cumulative_usage'](str(self.transcript), prices)[0]
        self.assertEqual(usage['claude-haiku-5.5']['long']['cache_read'], 100000)

    def test_claude_model_id_resolves_to_price_entry(self):
        usd, _, detail = self.ns['cumulative_cost'](
            {'claude-sonnet-5-5': {'flat': {'input': 1000000}}},
            {'claude-sonnet-5.5': {'input': 2, 'provider': 'anthropic'}})
        self.assertEqual(usd, 2)
        self.assertEqual(detail['claude-sonnet-5-5']['cost'], 2)

    def test_desktop_model_names_resolve_to_canonical_prices(self):
        prices = json.loads(SOURCE.with_name('model_prices.json').read_text(encoding='utf-8'))
        for name, expected in (
            ('DeepSeek-V4.1-Flash', 'deepseek-flash'),
            ('deepseek-v4.1-flash-1017', 'deepseek-flash'),
            (' DEEPSEEK-FLASH[1M] ', 'deepseek-flash'),
            ('Qwen3.8-Flash', 'qwen3.8-flash'),
            ('qwen3-8-flash', 'qwen3.8-flash'),
            ('GLM-5.3-Flash', 'glm-5.3-flash'),
            ('GLM-5-3-Flash', 'glm-5.3-flash')):
            with self.subTest(model=name):
                self.assertEqual(self.ns['price_key'](name, prices), expected)

    def test_every_catalog_model_resolves_common_spelling_variants(self):
        prices = json.loads(SOURCE.with_name('model_prices.json').read_text(encoding='utf-8'))
        for name in prices:
            if name.startswith('_'):
                continue
            variants = (name.upper(), name.replace('.', '-').upper(),
                        name.replace('-', ' ').replace('.', ' '),
                        f'gateway/{name.upper()}[1M]', name+'-20261027')
            for variant in variants:
                with self.subTest(model=name, variant=variant):
                    self.assertEqual(self.ns['price_key'](variant, prices), name)

    def test_alias_configuration_works_for_any_provider(self):
        prices = {'arbitrary-canonical': {'input': 1, 'aliases': ['Vendor Model Rev A']},
                  'another-canonical': {'input': 2, 'aliases': ['Second Brand Alias']}}
        self.assertEqual(self.ns['price_key']('vendor_model_rev_a', prices), 'arbitrary-canonical')
        self.assertEqual(self.ns['price_key']('SECOND-BRAND-ALIAS', prices), 'another-canonical')

    def test_ambiguous_alias_and_unlisted_model_are_not_guessed(self):
        prices = {'model-a': {'input': 1, 'aliases': ['shared-name']},
                  'model-b': {'input': 9, 'aliases': ['SHARED NAME']}}
        self.assertEqual(self.ns['price_key']('Shared Name', prices), 'Shared Name')
        self.assertEqual(self.ns['price_key']('model-a-pro', prices), 'model-a-pro')

    def test_cc_switch_documented_model_wrappers(self):
        prices = {'step-3.5-flash': {'input': 1}, 'kimi-k2-0905': {'input': 1},
                  'gpt-5.2-codex-low': {'input': 1}, 'gpt-5.5': {'input': 1},
                  'claude-opus-4.8': {'input': 1}, 'claude-haiku-4-5-20251001': {'input': 1}}
        for raw, canonical in (
            ('stepfun-ai/step-3.5-flash', 'step-3.5-flash'),
            ('moonshotai/kimi-k2-0905:exa', 'kimi-k2-0905'),
            ('gpt-5.2-codex@low', 'gpt-5.2-codex-low'),
            ('OpenAI/GPT-5.5-2026-05-14', 'gpt-5.5'),
            ('anthropic/claude-opus-4.8', 'claude-opus-4.8'),
            ('global.anthropic.claude-opus-4-8-v1:0', 'claude-opus-4.8'),
            ('claude-haiku-4-5', 'claude-haiku-4-5-20251001')):
            with self.subTest(raw=raw):
                self.assertEqual(self.ns['price_key'](raw, prices), canonical)

    def test_ambiguous_dated_short_name_is_not_guessed(self):
        prices = {'demo-20261001': {'input': 1}, 'demo-20261020': {'input': 8}}
        self.assertEqual(self.ns['price_key']('demo', prices), 'demo')

    def test_alias_usage_is_grouped_under_one_model(self):
        prices = json.loads(SOURCE.with_name('model_prices.json').read_text(encoding='utf-8'))
        self.transcript.write_text(self.record(100, 'DeepSeek-V4.1-Flash') +
                                   self.record(200, 'deepseek-flash') +
                                   self.record(300, 'deepseek-v4.1-flash-1017'), encoding='utf-8')
        usage = self.ns['get_cumulative_usage'](str(self.transcript), prices)[0]
        self.assertEqual(set(usage), {'deepseek-flash'})
        self.assertEqual(self.ns['_usage_total'](usage['deepseek-flash'], 'input'), 600)

    def test_desktop_names_are_priced_in_full_renderer(self):
        prices = json.loads(SOURCE.with_name('model_prices.json').read_text(encoding='utf-8'))
        (self.root / 'model_prices.json').write_text(json.dumps(prices))
        rows = []
        for model in ('DeepSeek-V4.1-Flash', 'Qwen3.8-Flash', 'GLM-5.3-Flash'):
            rec = json.loads(self.record(1000000, model))
            rec['timestamp'] = '2026-10-27T05:00:00Z'  # 13:00 Beijing, offpeak.
            rows.append(json.dumps(rec)+'\n')
        self.transcript.write_text(''.join(rows), encoding='utf-8')
        text = self.render({'model': {'id': 'deepseek-flash'}, 'transcript_path': str(self.transcript)})
        self.assertNotIn('价格未配置', text)
        self.assertNotIn('仅已知部分', text)
        self.assertIn('¥2.200', text)
        for model in ('deepseek-flash', 'qwen3.8-flash', 'glm-5.3-flash'):
            self.assertIn(model+' · in 1.0M', text)

    def test_full_renderer_keeps_recorded_tariff_after_price_changes(self):
        self.transcript.write_text(self.record(1000000, 'demo'), encoding='utf-8')
        path = self.root / 'model_prices.json'
        path.write_text(json.dumps({'demo': {'input': 2, 'output': 0}}))
        payload = {'model': {'id': 'demo'}, 'transcript_path': str(self.transcript)}
        self.assertIn('$2.000', self.render(payload))
        path.write_text(json.dumps({'demo': {'input': 99, 'output': 0}}))
        text = self.render(payload)
        self.assertIn('$2.000', text)
        self.assertNotIn('$99.000', text)

    def test_model_id_drives_provider_when_display_name_is_friendly(self):
        (self.root / 'model_prices.json').write_text(json.dumps({
            'claude-opus-5.5': {'input': 4, 'provider': 'anthropic'}}))
        text = self.render({'model': {'id': 'claude-opus-5-5', 'display_name': 'Opus'}})
        self.assertIn('[Opus@anthropic]', text)

    def test_null_model_and_non_object_payload_do_not_crash(self):
        self.assertIn('[?]', self.render({'model': None}))
        self.assertIn('invalid input', self.render([]))

    def test_missing_remaining_percentage_is_derived(self):
        text = self.render({'context_window': {'context_window_size': 200000, 'used_percentage': 95}})
        self.assertIn('5% left', text)
        self.assertNotIn('None', text)

    def test_one_hour_cache_write_uses_its_own_price(self):
        rec = json.loads(self.record(0, 'claude-sonnet-5.5'))
        rec['message']['usage'].update(output_tokens=0, cache_creation_input_tokens=1000000,
                                      cache_creation={'ephemeral_1h_input_tokens': 600000,
                                                      'ephemeral_5m_input_tokens': 400000})
        self.transcript.write_text(json.dumps(rec)+'\n', encoding='utf-8')
        prices = {'claude-sonnet-5.5': {'provider': 'anthropic', 'input': 2, 'cache_write': 2.5}}
        usage = self.ns['get_cumulative_usage'](str(self.transcript), prices)[0]
        usd, _, detail = self.ns['cumulative_cost'](usage, prices)
        # 0.6M * $4 + 0.4M * $2.5 = $3.4.
        self.assertAlmostEqual(usd, 3.4)
        self.assertEqual(detail['claude-sonnet-5.5']['cache_write'], 1000000)

    def test_usage_rebuild_preserves_duration_from_previous_format(self):
        self.transcript.write_text(self.record(), encoding='utf-8')
        self.ns['get_cumulative_usage'](str(self.transcript), {}, 10000, 5000)
        path = Path(self.ns['USAGE_CACHE']);cache = json.loads(path.read_text())
        cache[str(self.transcript)].pop('usage_version')
        path.write_text(json.dumps(cache))
        usage, duration, api, _ = self.ns['get_cumulative_usage'](str(self.transcript), {}, 11000, 6000)
        self.assertEqual((duration, api), (11000, 6000))
        self.assertEqual(self.ns['_usage_total'](usage['known'], 'input'), 100)

    def test_append_is_counted_once(self):
        self.transcript.write_text(self.record(), encoding='utf-8')
        self.read()
        with self.transcript.open('a', encoding='utf-8') as f:
            f.write(self.record(50))
        self.read()
        self.assertEqual(self.ns['_usage_total'](self.read()[0]['known'], 'input'), 150)

    def test_truncation_rebuilds_usage_and_title(self):
        self.transcript.write_text(self.record() * 3, encoding='utf-8')
        self.read()
        self.transcript.write_text(self.record(7), encoding='utf-8')
        self.assertEqual(self.ns['_usage_total'](self.read()[0]['known'], 'input'), 7)

    def test_replacement_with_larger_file_rebuilds(self):
        self.transcript.write_text(self.record(), encoding='utf-8')
        self.read()
        replacement = self.root / 'replacement.jsonl'
        replacement.write_text(self.record(7) * 2, encoding='utf-8')
        replacement.replace(self.transcript)
        self.assertEqual(self.ns['_usage_total'](self.read()[0]['known'], 'input'), 14)

    def test_partial_line_is_retried(self):
        text = self.record()
        self.transcript.write_text(text[:30], encoding='utf-8')
        self.read()
        with self.transcript.open('a', encoding='utf-8') as f:
            f.write(text[30:])
        self.assertEqual(self.ns['_usage_total'](self.read()[0]['known'], 'input'), 100)

    def test_missing_price_preserves_known_subtotal_and_unknown_usage(self):
        usage = {'known': {'flat': {'input': 1000000}},
                 'unknown': {'flat': {'input': 100}}}
        usd, cny, detail = self.ns['cumulative_cost'](usage, {'known': {'input': 2}})
        self.assertEqual((usd, cny), (2, 0))
        self.assertEqual(detail['known']['cost'], 2)
        self.assertIsNone(detail['unknown']['cost'])
        self.assertEqual(detail['unknown']['input'], 100)

    def test_known_native_currencies(self):
        usage = {'a': {'flat': {'input': 1000000}}, 'b': {'flat': {'output': 1000000}}}
        usd, cny, _ = self.ns['cumulative_cost'](usage, {
            'a': {'input': 2}, 'b': {'currency': 'CNY', 'output': 8}})
        self.assertEqual((usd, cny), (2, 8))

    def test_stale_fx_does_not_wait_for_network(self):
        Path(self.ns['USD_CNY_CACHE']).write_text(json.dumps({'ts': 0, 'rate': 7.1}))
        def slow_fetch():
            time.sleep(0.5)
            raise OSError('offline')
        self.ns['_fetch_sina_fx'] = slow_fetch
        self.ns['_fetch_er_api'] = slow_fetch
        with patch('subprocess.Popen'):
            start = time.monotonic()
            self.assertEqual(self.ns['get_usd_cny'](), 7.1)
            self.assertLess(time.monotonic() - start, 0.2)

    def test_renderer_shows_known_subtotal_and_unknown_model(self):
        self.transcript.write_text(self.record(1000000) + self.record(40, 'mystery'), encoding='utf-8')
        (self.root / 'model_prices.json').write_text(json.dumps({'known': {'input': 2, 'output': 0}}))
        (self.root / 'usd_cny.json').write_text(json.dumps({'ts': time.time(), 'rate': 7.1}))
        payload = {'model': {'id': 'mystery'}, 'transcript_path': str(self.transcript),
                   'cost': {'total_cost_usd': 999}}
        output = io.StringIO()
        with patch('sys.stdin', io.StringIO(json.dumps(payload))), patch('sys.argv', [str(SOURCE)]), \
                patch('os.path.expanduser', side_effect=lambda p: str(self.root / Path(p).name)), \
                contextlib.redirect_stdout(output):
            exec(compile(SOURCE.read_text(encoding='utf-8'), str(SOURCE), 'exec'), {'__file__': str(SOURCE)})
        text = re.sub(r'\x1b\[[0-9;]*m', '', output.getvalue())
        self.assertIn('$2.000', text)
        self.assertIn('仅已知部分', text)
        self.assertIn('mystery · in 40', text)
        self.assertIn('价格未配置，未计入费用', text)
        self.assertNotIn('999', text)

    def test_background_refresh_updates_cache(self):
        self.ns['_fetch_sina_fx'] = lambda: 7.05
        self.assertEqual(self.ns['get_usd_cny'](refresh=True), 7.05)
        saved = json.loads(Path(self.ns['USD_CNY_CACHE']).read_text())
        self.assertEqual(saved['rate'], 7.05)

    def test_offline_refresh_keeps_stale_rate(self):
        Path(self.ns['USD_CNY_CACHE']).write_text(json.dumps({'ts': 0, 'rate': 7.1}))
        def offline():
            raise OSError('offline')
        self.ns['_fetch_sina_fx'] = offline
        self.ns['_fetch_er_api'] = offline
        self.assertEqual(self.ns['get_usd_cny'](refresh=True), 7.1)

    def test_concurrent_sessions_keep_both_caches(self):
        # Delay each write to make overlapping read/modify/write operations
        # reproducible without relying on machine speed.
        paths = [self.root / f'{i}.jsonl' for i in range(2)]
        for p in paths:
            p.write_text(self.record(), encoding='utf-8')
        original = json.dump
        def delayed_dump(*args, **kwargs):
            time.sleep(0.05)
            return original(*args, **kwargs)
        with patch('json.dump', side_effect=delayed_dump):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda p: self.ns['get_cumulative_usage'](str(p), {}), paths))
        cache = json.loads(Path(self.ns['USAGE_CACHE']).read_text())
        for p in paths:
            self.assertEqual(cache[str(p)]['usage']['known']['flat']['input'], 100)

    def test_separate_processes_keep_all_session_caches(self):
        paths = [self.root / f'process-{i}.jsonl' for i in range(4)]
        for p in paths:
            p.write_text(self.record(), encoding='utf-8')
        code = ('import sys; from test_status_line import load_helpers; '
                'ns=load_helpers(); ns["USAGE_CACHE"]=sys.argv[1]; '
                'ns["get_cumulative_usage"](sys.argv[2], {}, 1000, 500)')
        children = [subprocess.Popen([sys.executable, '-c', code, self.ns['USAGE_CACHE'], str(p)],
                                    cwd=SOURCE.parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    for p in paths]
        for child in children:
            _, err = child.communicate(timeout=15)
            self.assertEqual(child.returncode, 0, err.decode(errors='replace'))
        cache = json.loads(Path(self.ns['USAGE_CACHE']).read_text())
        for p in paths:
            self.assertEqual(cache[str(p)]['usage']['known']['flat']['input'], 100)
            self.assertEqual(cache[str(p)]['dur_last'], 1000)

    def test_resume_duration_survives_price_cache_rebuild(self):
        self.transcript.write_text(self.record(), encoding='utf-8')
        self.ns['get_cumulative_usage'](str(self.transcript), {}, 10000, 5000)
        _, duration, api_duration, _ = self.ns['get_cumulative_usage'](
            str(self.transcript), {'known': {'input': 2}}, 2000, 1000)
        self.assertEqual((duration, api_duration), (12000, 6000))

    def test_default_fx_is_explicitly_labeled(self):
        with patch('subprocess.Popen'):
            self.assertEqual(self.ns['get_usd_cny'](), 7.2)
        self.assertIn('暂用', self.ns.get('FX_STATUS', ''))

    def test_invalid_fx_cache_is_not_displayed(self):
        Path(self.ns['USD_CNY_CACHE']).write_text(json.dumps({'ts': time.time(), 'rate': 'NaN'}))
        with patch('subprocess.Popen'):
            self.assertEqual(self.ns['get_usd_cny'](), 7.2)

    def test_missing_holiday_year_is_not_silently_billed_at_peak(self):
        prices = {'deepseek-flash': {'peak': {'input': 2}, 'offpeak': {'input': 1}}}
        segment = self.ns['classify_segment']('2027-01-01T10:00:00+08:00', 'deepseek-flash', 100, prices)
        usd, cny, detail = self.ns['cumulative_cost'](
            {'deepseek-flash': {segment: {'input': 1000000}}}, prices)
        self.assertEqual((usd, cny), (0, 0))
        self.assertEqual(detail['deepseek-flash']['input'], 1000000)
        self.assertIn('2027', detail['deepseek-flash'].get('unpriced_reason', ''))

    def test_configured_holiday_year_is_used(self):
        prices = {'_holidays': {'2027': ['2027-01-01']},
                  'deepseek-flash': {'peak': {'input': 2}, 'offpeak': {'input': 1}}}
        self.assertEqual(self.ns['classify_segment'](
            '2027-01-01T10:00:00+08:00', 'deepseek-flash', 100, prices), 'offpeak')

    def test_price_tier_changes_reclassify_cached_usage(self):
        self.transcript.write_text(self.record(100), encoding='utf-8')
        prices = {'known': {'input': 1, 'long_threshold': 200, 'long': {'input': 2}}}
        self.ns['get_cumulative_usage'](str(self.transcript), prices)
        prices['known']['long_threshold'] = 50
        usage = self.ns['get_cumulative_usage'](str(self.transcript), prices)[0]
        self.assertEqual(usage['known']['long']['input'], 100)

    def test_retired_alias_uses_historical_and_current_prices(self):
        prices = json.loads(SOURCE.with_name('model_prices.json').read_text(encoding='utf-8'))
        model = 'deepseek-v4-flash'
        usage = {}
        for ts in ('2026-09-10T11:59:59+08:00', '2026-09-10T12:00:00+08:00'):
            seg = self.ns['classify_segment'](ts, model, 1000000, prices)
            usage[seg] = {'input': 1000000}
        _, cny, _ = self.ns['cumulative_cost']({model: usage}, prices)
        # Before switch: old peak 3; after switch: new offpeak 1.
        self.assertEqual(cny, 4)


if __name__ == '__main__':
    unittest.main()
