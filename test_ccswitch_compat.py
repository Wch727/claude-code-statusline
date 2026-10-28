"""Ported CC Switch cases plus adapter integration assertions; see PROVENANCE.md."""
import unittest
from ccswitch_compat import calculate_cost, flatten_models, get_common_model_keys, resolve_models_dev_selection


class UpstreamCompatibilityTests(unittest.TestCase):
    def test_upstream_decimal_cost_example(self):
        result = calculate_cost({'input': 1000, 'output': 500, 'cache_read': 200, 'cache_write': 100},
                                {'input': 3, 'output': 15, 'cache_read': 0.3, 'cache_write': 3.75})
        self.assertEqual(result['cost'], 0.010935)

    def test_upstream_one_hour_cache_case(self):
        result = calculate_cost({'cache_write': 1000, 'cache_write_1h': 600},
                                {'input': 5, 'output': 25, 'cache_read': 0.5, 'cache_write': 6.25})
        self.assertEqual(result['cost_cw'], 0.0085)

    def test_openai_cache_inclusive_input_is_not_double_charged(self):
        result = calculate_cost({'input': 1000, 'cache_read': 800}, {'input': 2, 'cache_read': 0.2}, True)
        self.assertEqual(result['cost'], 0.00056)

    def test_non_text_and_deprecated_models_are_excluded(self):
        data = {'openai': {'models': {
            'gpt-chat': {'cost': {'input': 1, 'output': 2}},
            'gpt-audio': {'cost': {'input': 1, 'output': 2}},
            'gpt-old': {'status': 'deprecated', 'cost': {'input': 1, 'output': 2}},
            'gpt-picture': {'modalities': {'output': ['image']}, 'cost': {'input': 1, 'output': 2}}}}}
        self.assertEqual([e['modelId'] for e in flatten_models(data)], ['gpt-chat'])

    def test_common_selection_is_bounded_and_honors_explicit_exclusions(self):
        data = {'openai': {'models': {f'gpt-{i}': {'release_date': f'2026-10-{i+1:02}',
                      'cost': {'input': 1, 'output': 2}} for i in range(9)}}}
        entries = flatten_models(data)
        self.assertEqual(len(get_common_model_keys(entries)), 6)
        selected = resolve_models_dev_selection(entries, {
            'selectedModelKeys': ['openai/gpt-0'], 'excludedCommonModelKeys': ['openai/gpt-8']})
        self.assertIn('openai/gpt-0', [e['key'] for e in selected])
        self.assertNotIn('openai/gpt-8', [e['key'] for e in selected])


if __name__ == '__main__':
    unittest.main()
