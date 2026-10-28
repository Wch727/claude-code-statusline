"""Python adaptations of CC Switch's MIT-licensed pricing/session functions.

Copyright (c) 2025 Jason Young. See vendor/cc-switch/LICENSE (distributed as
CC_SWITCH_LICENSE alongside installed modules). Upstream sources and pinned
revision are documented in vendor/cc-switch/PROVENANCE.md.
"""
from datetime import datetime, timezone
from decimal import Decimal
import math
import uuid

NON_TEXT_MODEL_MARKERS = ('audio', 'deprecated', 'embedding', 'image', 'moderation',
                          'realtime', 'transcribe', 'tts', 'video')
COMMON_FAMILY_RULES = (
    ('anthropic', ('claude-',)), ('openai', ('gpt-', 'o1-', 'o3-', 'o4-')),
    ('google', ('gemini-',)), ('xai', ('grok-',)), ('deepseek', ('deepseek-',)),
    ('alibaba', ('qwen',)), ('xiaomi', ('mimo-',)), ('longcat', ('longcat-',)),
    ('moonshotai', ('kimi-',)), ('minimax-cn', ('minimax-m',)), ('zai', ('glm-',)),
)


def normalize_models_dev_model_id(model_id):
    normalized = model_id.rsplit('/', 1)[-1].split(':', 1)[0].strip().replace('@', '-').lower()
    return normalized[:-4].strip() if normalized.endswith('[1m]') else normalized


def is_text_pricing_model(model_id, model):
    if str(model.get('status', '')).lower() == 'deprecated':
        return False
    modalities = model.get('modalities') or {}
    outputs = [v.lower() for v in modalities.get('output', []) if isinstance(v, str)] if isinstance(modalities, dict) else []
    if outputs and ('text' not in outputs or any(v in outputs for v in ('audio', 'image', 'video'))):
        return False
    searchable = f"{model_id} {model.get('name', '')}".lower()
    return not any(marker in searchable for marker in NON_TEXT_MODEL_MARKERS)


def flatten_models(data):
    entries = []
    for provider_id, provider in data.items():
        if not isinstance(provider, dict):
            continue
        models = provider.get('models') or {}
        if not isinstance(models, dict):
            continue
        for model_id, model in models.items():
            if not isinstance(model, dict) or not is_text_pricing_model(model_id, model):
                continue
            cost = model.get('cost') or {}
            if not isinstance(cost, dict):
                continue
            values = [cost.get(k) for k in ('input', 'output')]
            if not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                continue
            normalized = normalize_models_dev_model_id(model_id)
            if not normalized:
                continue
            prices = {k: cost.get(k, 0) for k in ('input', 'output', 'cache_read', 'cache_write')}
            if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in prices.values()):
                continue
            entries.append({'key': f'{provider_id}/{model_id}', 'providerId': provider_id,
                            'modelId': model_id, 'normalizedId': normalized,
                            'modelName': model.get('name') or model_id,
                            'releaseDate': model.get('release_date') or '', 'cost': prices,
                            'rawModel': model})
    # Same order: release descending, then model name ascending.
    entries.sort(key=lambda e: e['modelName'])
    entries.sort(key=lambda e: e['releaseDate'], reverse=True)
    return entries


def get_common_model_keys(entries):
    keys = set()
    for provider, prefixes in COMMON_FAMILY_RULES:
        count = 0
        for entry in entries:
            if entry['providerId'] == provider and entry['modelId'].lower().startswith(prefixes):
                keys.add(entry['key'])
                count += 1
                if count >= 6:
                    break
    return keys


def resolve_models_dev_selection(entries, config):
    explicit = set(config.get('selectedModelKeys', []))
    excluded = set(config.get('excludedCommonModelKeys', []))
    common = get_common_model_keys(entries) if config.get('includeCommonModels', True) else set()
    return [e for e in entries if e['key'] in explicit or (e['key'] in common and e['key'] not in excluded)]


def prefer_usage_snapshot(previous, tokens, stop_reason):
    """Port of session_usage.rs should_replace: finished first, then max output."""
    if previous is None:
        return True
    finished = stop_reason is not None
    was_finished = previous.get('stop_reason') is not None
    if finished and not was_finished:
        return True
    return finished == was_finished and tokens.get('output', 0) > previous['tokens'].get('output', 0)


def timestamp_millis(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return int(parsed.timestamp() * 1000) if parsed.tzinfo else None
    except (TypeError, ValueError, AttributeError):
        return None


def _uuid(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        return None


def record_chain_node(chain, value):
    key = _uuid(value.get('uuid'))
    if key:
        chain[key] = {'parent': _uuid(value.get('parentUuid')),
                      'timestamp_ms': timestamp_millis(value.get('timestamp')),
                      'is_attachment': value.get('type') == 'attachment'}


def record_block_timing(timings, value, message_id):
    end = timestamp_millis(value.get('timestamp'))
    if message_id not in timings:
        first = value.get('apiBlockIndex', 0) == 0
        duration = value.get('thinkingDurationMs')
        content = (value.get('message') or {}).get('content') or []
        thinking = bool(content and isinstance(content[0], dict) and content[0].get('type') == 'thinking')
        output = end - duration if first and thinking and end is not None and isinstance(duration, int) and duration > 0 else None
        timings[message_id] = {'first_parent': _uuid(value.get('parentUuid')),
                              'starts_at_first_block': first, 'first_output_ms': output, 'end_ms': None}
    timing = timings[message_id]
    if end is not None:
        timing['end_ms'] = max(end, timing.get('end_ms') or end)


def resolve_request_start_ms(chain, first_parent):
    cursor = first_parent
    for _ in range(32):
        node = chain.get(cursor)
        if node is None:
            return None
        if not node['is_attachment']:
            return node['timestamp_ms']
        cursor = node['parent']
    return None


def estimated_timing(chain, timing, finished):
    if not timing or not finished or not timing['starts_at_first_block']:
        return {}
    start = resolve_request_start_ms(chain, timing['first_parent'])
    end = timing.get('end_ms')
    if start is None or end is None or not 100 <= end - start <= 3_600_000:
        return {}
    latency = end - start
    first = timing.get('first_output_ms')
    first_token = first - start if first is not None and 0 < first - start <= latency else None
    return {'start_ms': start, 'latency_ms': latency, 'first_token_ms': first_token}


def calculate_cost(tokens, rates, input_includes_cache=False):
    """Port of CostCalculator.calculate_with_cache_semantics; explicit 1h rate extension."""
    dec = lambda value: Decimal(str(value))
    fresh = tokens.get('input', 0)
    if input_includes_cache:
        fresh = max(0, fresh - tokens.get('cache_read', 0) - tokens.get('cache_write', 0))
    hour = min(tokens.get('cache_write', 0), tokens.get('cache_write_1h', 0))
    write_rate = dec(rates.get('cache_write', rates.get('input', 0)))
    hour_rate = dec(rates.get('cache_write_1h', write_rate * Decimal('1.6')))
    amounts = {'cost_in': dec(fresh) * dec(rates.get('input', 0)),
               'cost_out': dec(tokens.get('output', 0)) * dec(rates.get('output', 0)),
               'cost_cr': dec(tokens.get('cache_read', 0)) * dec(rates.get('cache_read', 0)),
               'cost_cw': dec(tokens.get('cache_write', 0) - hour) * write_rate + dec(hour) * hour_rate}
    result = {key: float(value / Decimal(1_000_000)) for key, value in amounts.items()}
    result['cost'] = float(sum(amounts.values()) / Decimal(1_000_000))
    return result
