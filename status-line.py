#!/usr/bin/env python3
"""Claude Code Status Line — 模型 / 输入输出Token / 上下文 / 目录 / 时长 / 时钟"""

import json
import sys
import os
import re as _re2
from contextlib import contextmanager
from functools import wraps
from datetime import datetime, timezone, timedelta
from pathlib import Path
import statusline_store as usage_store
from ccswitch_compat import (prefer_usage_snapshot, record_chain_node,
                             record_block_timing, estimated_timing)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

# ── 辅助 ──────────────────────────────────────────────
def fmt(n):
    if n is None: return "?"
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000: return f"{n/1_000:.1f}K"
    return str(n)

def fmt_duration(ms):
    if ms is None or ms == 0: return None
    if ms < 1000: return f"{ms}ms"
    if ms < 60_000: return f"{ms/1000:.1f}s"
    h, m = divmod(ms / 60_000, 60)
    return f"{int(h)}h{int(m)}m"

def bar(pct, width=14):
    """进度条：█ 已用 / ░ 剩余，按百分比填色块。"""
    if pct is None:
        return "░" * width
    filled = max(0, min(width, int(round(pct / 100 * width))))
    return "█" * filled + "░" * (width - filled)

# ── 价格库 / 汇率 ─────────────────────────────────────
def data_path(name):
    root = os.environ.get('STATUSLINE_HOME')
    return os.path.join(root, name) if root else os.path.expanduser('~/.claude/' + name)


PRICE_DB = data_path('model_prices.json')
USD_CNY_CACHE = data_path('usd_cny.json')
USD_CNY_TTL = 1800  # 汇率缓存 30 分钟（新浪实时源，日内可见变动）
FX_STATUS = "暂用值，后台刷新"


def _valid_fx(value):
    rate = float(value)
    if not 4.0 < rate < 10.0:
        raise ValueError("invalid USD/CNY rate")
    return rate

def _base_prices():
    try:
        with open(PRICE_DB, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_prices():
    base = _base_prices()
    snapshot = usage_store.read_json(Path(PRICE_DB).with_name('prices_online.json'))
    try:
        return usage_store.merge_online_prices(base, snapshot, price_key)
    except (ValueError, TypeError, AttributeError, KeyError):
        return base


def maybe_sync_prices(prices):
    """Spawn at most one updater; rendering never waits for the network."""
    import time
    import subprocess
    if os.environ.get('STATUSLINE_DISABLE_PRICE_SYNC') == '1':
        return
    config = prices.get('_sync', {})
    if not config.get('autoSyncEnabled', False):
        return
    root = Path(PRICE_DB).parent
    status = usage_store.read_json(root / 'price_sync_status.json')
    interval = max(3600, float(config.get('intervalHours', 6)) * 3600)
    if time.time() - status.get('last_success', 0) < interval:
        return
    if time.time() - status.get('last_attempt', 0) < 300:
        return
    lock = root / 'price_sync_start.lock'
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > 300:
            lock.unlink()
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except OSError:
        return
    try:
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        subprocess.Popen([sys.executable, os.path.abspath(__file__), '--sync-prices'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
    except OSError:
        pass


def _normalized_model_name(value):
    import unicodedata
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    text = text.replace("–", "-").replace("—", "-")
    text = _re2.sub(r"[\s_.]+", "-", text)
    text = _re2.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", "-", text)
    return _re2.sub(r"-+", "-", text).strip("-")


def price_key(model, prices):
    """One resolver for every provider; semantic aliases live in the price DB.

    Exact IDs win. Formatting/date variants must resolve uniquely; a family
    prefix alone never selects a version, tier or provider.
    """
    key = _re2.sub(r"\[\w+\]", "", str(model or "")).strip()
    if not key.startswith("_") and isinstance(prices.get(key), dict):
        return key
    key = key.rsplit("/", 1)[-1].strip()
    if not key.startswith("_") and isinstance(prices.get(key), dict):
        return key
    clean = key.split(":", 1)[0].replace("@", "-")
    # Bedrock regional/global wrappers are transport IDs, not model versions.
    wrapped = _re2.sub(r"^(?:(?:global|us|eu|apac)\.)?anthropic\.", "", clean, flags=_re2.I)
    if wrapped != clean:
        wrapped = _re2.sub(r"-v\d+$", "", wrapped)
    undated = lambda value: _re2.sub(r"-(?:\d{8}|\d{4}-\d{2}-\d{2})$", "", value)
    index = {}
    for name, entry in prices.items():
        if name.startswith("_") or not isinstance(entry, dict):
            continue
        aliases = entry.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, (list, tuple)):
            aliases = []
        for alias in [name, *aliases]:
            if isinstance(alias, str):
                index.setdefault(_normalized_model_name(alias), set()).add(name)
    for variant in (key, clean, wrapped, undated(wrapped)):
        matches = index.get(_normalized_model_name(variant), set())
        if matches:
            return next(iter(matches)) if len(matches) == 1 else key
    # A short ID may identify a single dated entry, but multiple versions with
    # different prices must remain ambiguous instead of silently picking one.
    short = _normalized_model_name(undated(wrapped))
    matches = {name for name, entry in prices.items() if not name.startswith("_")
               and isinstance(entry, dict) and _normalized_model_name(undated(name)) == short}
    if len(matches) == 1:
        return next(iter(matches))
    return key

def _fetch_sina_fx():
    """新浪财经外汇实时价（在岸美元人民币），失败抛异常。

    返回 ``var hq_str_fx_susdcny="时间,昨收,…×5,最新价,…";``，取 index 8。
    字段含义用离岸 CNH 的涨跌字段交叉验证过：涨跌额/昨收 == 涨跌幅
    （-0.0074 / 6.7145 == -0.11%），确认 index 8 为最新价。
    """
    import urllib.request
    req = urllib.request.Request(
        "https://hq.sinajs.cn/list=fx_susdcny",
        headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=4) as r:
        txt = r.read().decode("gbk", "replace")
    rate = float(txt.split('"')[1].split(",")[8])
    if not (4.0 < rate < 10.0):          # 合理性护栏：字段错位时不采纳
        raise ValueError(f"sina fx out of range: {rate}")
    return rate

def _fetch_er_api():
    """ExchangeRate-API 免费开放端点（每日更新，作为兜底）。"""
    import urllib.request
    with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r:
        return float(json.loads(r.read().decode())["rates"]["CNY"])

def get_usd_cny(refresh=False):
    """实时 USD→CNY 汇率（缓存 30 分钟）。

    前台立即使用缓存或 7.2，过期后启动后台刷新。
    后台数据源：新浪实时 → ExchangeRate-API（日更）→ 本地缓存 → 7.2。
    注意：在岸人民币周末/夜间休市，此时汇率本就几乎不动，并非未刷新。
    """
    import time as _t
    global FX_STATUS
    FX_STATUS = "暂用值，后台刷新"
    cached_rate = 7.2
    try:
        if os.path.exists(USD_CNY_CACHE):
            with open(USD_CNY_CACHE, encoding="utf-8") as f:
                c = json.load(f)
            cached_rate = _valid_fx(c.get("rate"))
            FX_STATUS = "过期缓存，后台刷新"
            if 0 <= _t.time() - float(c.get("ts", 0)) < USD_CNY_TTL:
                FX_STATUS = "缓存"
                return cached_rate
    except Exception:
        pass
    if not refresh:
        # The short-lived renderer never waits for network I/O. A lock limits
        # background refreshes (and retries after failure) to one per minute.
        import subprocess
        lock = USD_CNY_CACHE + ".lock"
        try:
            if os.path.exists(lock) and _t.time() - os.path.getmtime(lock) > 60:
                os.unlink(lock)
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except OSError:
            return cached_rate
        try:
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "--refresh-fx"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **options)
        except OSError:
            pass
        return cached_rate
    rate = None
    for _fetch in (_fetch_sina_fx, _fetch_er_api):
        try:
            rate = _valid_fx(_fetch())
            FX_STATUS = "新浪" if _fetch is _fetch_sina_fx else "ExchangeRate-API（日更）"
            break
        except Exception:
            continue
    if rate is None:                     # 全部失败：回退到旧缓存，最后 7.2
        try:
            with open(USD_CNY_CACHE, encoding="utf-8") as f:
                return _valid_fx(json.load(f).get("rate"))
        except Exception:
            return 7.2
    try:
        with open(USD_CNY_CACHE + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"ts": _t.time(), "rate": rate}, f)
        os.replace(USD_CNY_CACHE + ".tmp", USD_CNY_CACHE)
    except Exception:
        pass
    return rate

def fmt_price(x):
    return f"{x:.5f}".rstrip("0").rstrip(".")

# ── 累计用量（增量读 transcript，避免每秒全量解析）────────
USAGE_CACHE = data_path('usage_cache.json')
LEDGER_ERROR = None
CACHE_VERSION = 8  # 文件身份、字节偏移和读取位置校验；旧缓存自动重算
BUCKETS = ("legacy", "peak", "offpeak")
_CN_TZ = timezone(timedelta(hours=8))
_PEAK_START = datetime(2026, 8, 17, 0, 0, 0, tzinfo=_CN_TZ)  # 峰谷定价生效时刻（北京）
_WEEKEND_START = datetime(2026, 8, 23, 0, 0, 0, tzinfo=_CN_TZ)  # 周末/节假日全天低谷生效时刻（北京）

def _cn_holidays_2026():
    """2026 年中国法定节假日（国务院办公厅 2025-11-04 通知）。

    只收“放假”的日期；调休上班的周六/周日不计入，仍按周末处理——
    因为 DeepSeek 计费口径只认“周一至周五（不含法定节假日）”，
    官方未把调休上班日算作高峰。
    """
    from datetime import date
    spans = [(1, 1, 1, 3), (2, 15, 2, 23), (4, 4, 4, 6),
             (5, 1, 5, 5), (6, 19, 6, 21), (9, 25, 9, 27), (10, 1, 10, 7)]
    days = set()
    for m1, d1, m2, d2 in spans:
        cur, end = date(2026, m1, d1), date(2026, m2, d2)
        while cur <= end:
            days.add(cur)
            cur += timedelta(days=1)
    return frozenset(days)

_CN_HOLIDAYS = _cn_holidays_2026()


def holiday_calendar(prices=None):
    """Optional _holidays year -> ISO dates; never assume a missing year is empty."""
    from datetime import date
    calendar = {2026: _CN_HOLIDAYS}
    for year, values in (prices or {}).get("_holidays", {}).items():
        try:
            year = int(year)
            dates = frozenset(date.fromisoformat(value) for value in values)
            if dates and all(day.year == year for day in dates):
                calendar[year] = dates
        except (TypeError, ValueError):
            continue
    return calendar

# 百炼平台模型：峰谷时段与 DeepSeek 官方不同（百炼空闲 22:00–8:00，其余高峰）
_BAILIAN_MODELS = {"deepseek-v4-flash-0731"}

def _zero_usage():
    return {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cache_write_1h": 0}

def classify_bucket(ts, model=None, calendar=None):
    """按消息时间戳 + 模型返回 legacy / peak / offpeak。

    - < 2026-08-17 00:00（北京）：legacy（旧固定单价）
    - 百炼平台模型（如 deepseek-v4-flash-0731）：高峰 8:00–22:00，空闲 22:00–8:00
    - DeepSeek 官方模型：仅工作日（周一至周五）9:00–12:00、14:00–18:00 为高峰
    - 2026-08-23 00:00（北京）起：周末（周六/周日）与法定节假日全天按空闲（offpeak）计费
    """
    if not ts:
        return "legacy"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return "legacy"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    bj = dt.astimezone(_CN_TZ)
    if bj < _PEAK_START:
        return "legacy"
    key = (model or "").split("[")[0]
    if key in _BAILIAN_MODELS:
        # 百炼：高峰 8:00–22:00，空闲 22:00–8:00
        if 8 <= bj.hour < 22:
            return "peak"
        return "offpeak"
    # 周末（周六=5/周日=6）与法定节假日自 8-23 起全天低谷
    if calendar is None:
        calendar = holiday_calendar()
    if bj >= _WEEKEND_START and (bj.weekday() >= 5 or bj.date() in calendar.get(bj.year, ())):
        return "offpeak"
    # DeepSeek 官方：仅工作日高峰 9:00–12:00、14:00–18:00
    if (9 <= bj.hour < 12) or (14 <= bj.hour < 18):
        if bj >= _WEEKEND_START and bj.year not in calendar:
            return f"calendar-unknown-{bj.year}"
        return "peak"
    return "offpeak"

def classify_segment(ts, model, input_tokens, prices):
    """返回计费分段 key：峰谷模型的 legacy/peak/offpeak，长上下文模型的 short/long，其余 flat。

    - 峰谷模型（价格表含 legacy/peak/offpeak）：沿用 classify_bucket 的时间分档
    - 长上下文模型（价格表含 long_threshold）：单条消息输入 token 超过阈值 → long，否则 short
    - 扁平模型：flat（无分档）
    """
    key = price_key(model, prices or {})
    entry = (prices or {}).get(key) or (prices or {}).get(model)
    if isinstance(entry, dict) and entry.get("revisions") and ts:
        try:
            when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            for index in range(len(entry["revisions"]) - 1, -1, -1):
                revision = entry["revisions"][index]
                since = datetime.fromisoformat(revision["from"].replace("Z", "+00:00"))
                if when >= since:
                    segment = classify_segment(ts, model, input_tokens, {**(prices or {}), key: revision["prices"]})
                    return f"revision-{index}:{segment}"
        except (ValueError, TypeError, KeyError):
            pass
    if isinstance(entry, dict) and any(b in entry for b in BUCKETS):
        return classify_bucket(ts, model, holiday_calendar(prices))
    if isinstance(entry, dict) and "long" in entry:
        return "long" if (input_tokens or 0) > entry.get("long_threshold", 0) else "short"
    return "flat"

@contextmanager
def _cache_lock(path):
    """OS locks are released even when a renderer is killed; no stale lock deletion."""
    with open(path, "a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if not lock.tell():
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            # LK_LOCK retries in one-second intervals. Poll briefly instead so
            # normal concurrent refreshes do not add a whole second of latency.
            import time
            deadline = time.monotonic() + 10
            while True:
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _with_usage_lock(func):
    @wraps(func)
    def locked(*args, **kwargs):
        with _cache_lock(USAGE_CACHE + ".lock"):
            return func(*args, **kwargs)
    return locked


def _atomic_json(path, value):
    import tempfile
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                         dir=os.path.dirname(os.path.abspath(path))) as f:
            tmp = f.name
            json.dump(value, f)
        os.replace(tmp, path)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


@_with_usage_lock
def get_cumulative_usage(transcript_path, prices=None, duration_ms=None, api_duration_ms=None):
    """增量累计每模型的 token 用量（按会话隔离 + 按计费分段，只处理新增行）。

    缓存结构：``{ "_version": 8, transcript_path: {"offset": int, "usage": {model: {segment: {…}}}, …} }``。
    segment ∈ {legacy,peak,offpeak}（峰谷）或 {short,long}（长上下文）或 {flat}（扁平），
    每个 segment 记录 input/output/cache_read/cache_write。
    旧格式缓存通过 ``_version`` 判定后自动作废重算。

    同时跨 resume 累计活跃时长：Claude Code 的 total_duration_ms / total_api_duration_ms
    在 /resume 后会重置，这里检测到值回退（cur < last）时把上一段时长并入 base，
    使时长单调累计，不会因 resume 而丢失之前工作的时间。

    另外捕获**手动命名**的会话名：transcript 里 ``custom-title`` 记录来自 /rename
    或 --name（可靠），而 ``ai-title`` 是 AI 自动生成的标题（常概括不准），
    因此只认前者、忽略后者。

    返回 ``(usage, total_duration_ms, total_api_duration_ms, custom_title)``。
    """
    if prices is None:
        prices = load_prices()
    cache = {}
    try:
        with open(USAGE_CACHE, encoding="utf-8") as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                cache = raw
    except Exception:
        pass
    if cache.get("_version") != CACHE_VERSION:
        cache = {"_version": CACHE_VERSION}
    session = cache.setdefault(transcript_path, {"offset": 0, "usage": {}})
    # Reset transcript-derived data after replacement, truncation or a rewrite
    # around the saved offset. Keep resume duration bookkeeping independent.
    import hashlib
    pricing_signature = hashlib.sha256(json.dumps(prices, sort_keys=True).encode()).hexdigest()
    try:
        stat = os.stat(transcript_path)
        identity = [stat.st_dev, stat.st_ino]
        offset = int(session.get("offset", 0))
        with open(transcript_path, "rb") as probe:
            probe.seek(max(0, offset - 256))
            tail = hashlib.sha256(probe.read(min(offset, 256))).hexdigest()
        if (session.get("identity") != identity or session.get("pricing_signature") != pricing_signature
                or stat.st_size < offset
                or session.get("tail") != tail or session.get("usage_version") != 4):
            session.update(offset=0, usage={}, messages={}, chain={}, timings={}, usage_version=4)
            session.pop("custom_title", None)
        session["identity"] = identity
        session["pricing_signature"] = pricing_signature
    except OSError:
        pass
    usage = session["usage"]
    if not isinstance(usage, dict):
        usage = session["usage"] = {}
    # ── 跨 resume 累计活跃时长 ──
    def _acc(field, cur):
        base_key = "dur_base" if field == "duration" else "api_base"
        last_key = "dur_last" if field == "duration" else "api_last"
        base = session.get(base_key, 0)
        last = session.get(last_key, 0)
        if cur < last:  # resume 重置：把上一段时长并入 base
            base += last
        session[base_key] = base
        session[last_key] = cur
        return base + cur
    total_duration = (_acc("duration", duration_ms) if duration_ms is not None
                      else session.get('dur_base', 0) + session.get('dur_last', 0))
    total_api = (_acc("api", api_duration_ms) if api_duration_ms is not None
                 else session.get('api_base', 0) + session.get('api_last', 0))
    try:
        with open(transcript_path, "rb") as f:
            f.seek(int(session.get("offset", 0)))
            while True:
                start = f.tell()
                line = f.readline()
                if not line:
                    break
                if not line.endswith(b"\n"):
                    f.seek(start)  # Writer has not finished this JSONL record.
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                chain = session.setdefault('chain', {})
                timings = session.setdefault('timings', {})
                record_chain_node(chain, rec)
                if rec.get("type") == "custom-title":
                    # 仅认手动命名（/rename、--name）；ai-title 是自动生成的，忽略
                    _ct = rec.get("customTitle")
                    if _ct:
                        session["custom_title"] = str(_ct)
                    continue
                if rec.get("type") == "assistant":
                    m = rec.get("message") or {}
                    if not isinstance(m, dict):
                        continue
                    u = m.get("usage") or {}
                    if not isinstance(u, dict) or not u:
                        continue
                    model = price_key(m.get("model") or "unknown", prices)
                    try:
                        tokens = {field: max(0, int(u.get(native, 0) or 0)) for field, native in (
                            ("input", "input_tokens"), ("output", "output_tokens"),
                            ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens"))}
                    except (TypeError, ValueError, OverflowError):
                        continue
                    creation = u.get("cache_creation") or {}
                    try:
                        tokens["cache_write_1h"] = min(tokens["cache_write"], max(0, int(
                            creation.get("ephemeral_1h_input_tokens", 0) or 0))) if isinstance(creation, dict) else 0
                    except (TypeError, ValueError, OverflowError):
                        tokens["cache_write_1h"] = 0
                    if not any(tokens.values()):
                        continue  # Synthetic/non-billable assistant records.
                    # Claude Code saves each content block separately, repeating
                    # the message-level usage. Keep one snapshot per API message.
                    identifier = m.get("id") or rec.get("requestId") or rec.get("uuid") or f'offset:{start}'
                    messages = session.setdefault("messages", {})
                    msg_key = json.dumps([model, identifier])
                    previous = messages.get(msg_key)
                    record_block_timing(timings, rec, str(identifier))
                    if not prefer_usage_snapshot(previous, tokens, m.get('stop_reason')):
                        continue
                    timing = estimated_timing(chain, timings.get(str(identifier)), m.get('stop_reason') is not None)
                    timestamp = (datetime.fromtimestamp(timing['start_ms'] / 1000, timezone.utc).isoformat()
                                 if timing else previous.get('timestamp') if previous else rec.get('timestamp'))
                    prompt_tokens = tokens["input"] + tokens["cache_read"] + tokens["cache_write"]
                    seg = classify_segment(timestamp, model, prompt_tokens, prices)
                    e = usage.get(model)
                    if not isinstance(e, dict):
                        e = usage[model] = {}
                    if previous:
                        old = e.get(previous["segment"], {})
                        for field, value in previous["tokens"].items():
                            old[field] = old.get(field, 0) - value
                    b = e.setdefault(seg, _zero_usage())
                    for field, value in tokens.items():
                        b[field] = b.get(field, 0) + value
                    messages[msg_key] = {"timestamp": timestamp, "segment": seg, "tokens": tokens,
                                         'request_key': str(identifier), 'raw_model': m.get('model'),
                                         'model': model, 'stop_reason': m.get('stop_reason'),
                                         'response_timestamp': rec.get('timestamp'),
                                         'timestamp_source': '请求起点估算（父链）' if timing else '回复记录时间（请求起点未知）'}
            session["offset"] = f.tell()
            f.seek(max(0, session["offset"] - 256))
            session["tail"] = hashlib.sha256(f.read(min(session["offset"], 256))).hexdigest()
    except Exception:
        pass
    record_session_ledger(transcript_path, session, prices)
    # 精简：只保留文件仍存在的会话，避免缓存无限增长。
    for p in list(cache.keys()):
        if p != "_version" and not os.path.exists(p):
            cache.pop(p, None)
    try:
        _atomic_json(USAGE_CACHE, cache)
    except Exception:
        pass
    return usage, total_duration, total_api, session.get("custom_title")


def ledger_db():
    return Path(USAGE_CACHE).with_name('usage_ledger.sqlite3')


def session_key(path):
    import hashlib
    return hashlib.sha256(os.path.abspath(path).encode('utf-8')).hexdigest()[:24]


def record_session_ledger(path, session, prices):
    global LEDGER_ERROR
    rows = []
    for message in session.get('messages', {}).values():
        model, seg, tokens = message['model'], message['segment'], message['tokens']
        entry = prices.get(price_key(model, prices), {})
        rates = dict(_segment_rate(entry, seg))
        if entry.get('provider') == 'anthropic' and rates:
            rates['cache_write_1h'] = rates.get('cache_write_1h', rates.get('input', 0) * 2)
        _, _, details = cumulative_cost({model: {seg: tokens}}, prices)
        detail = details.get(model, {})
        reason = detail.get('unpriced_reason') or ('价格未配置' if not rates else '')
        timing = estimated_timing(session.get('chain', {}), session.get('timings', {}).get(message['request_key']),
                                  message.get('stop_reason') is not None)
        rows.append({'session_key': session_key(path), 'request_key': message['request_key'],
                     'timestamp': message['timestamp'], 'response_timestamp': message.get('response_timestamp'),
                     'timestamp_source': message.get('timestamp_source'),
                     'model': model, 'raw_model': message.get('raw_model'), 'segment': seg,
                     'currency': entry.get('currency', 'USD'), 'tokens': tokens, 'rates': rates,
                     'price_entry': entry, 'cost': detail.get('cost') if rates else None,
                     'unpriced_reason': reason, 'source': entry.get('source', '本地价格规则'),
                     'latency_ms': timing.get('latency_ms'), 'first_token_ms': timing.get('first_token_ms')})
    try:
        usage_store.record_requests(ledger_db(), rows)
        LEDGER_ERROR = None
    except Exception as exc:
        LEDGER_ERROR = f'{type(exc).__name__}: {exc}'

def _segment_rate(entry, seg):
    """返回指定分段的单价子表。

    - 峰谷模型（含 legacy/peak/offpeak）：取 entry[seg]
    - 长上下文模型（含 long）：seg == "long" 取 entry["long"]，否则取 entry 自身
    - 扁平模型：自身即单价表
    """
    if not isinstance(entry, dict):
        return {}
    if seg.startswith("revision-"):
        revision, subsegment = seg.split(":", 1)
        try:
            return _segment_rate(entry["revisions"][int(revision.split("-")[1])]["prices"], subsegment)
        except (KeyError, IndexError, ValueError):
            return {}
    if any(b in entry for b in BUCKETS):
        return entry.get(seg) or {}
    if seg == "long" and "long" in entry:
        return entry.get("long") or {}
    return entry

def _usage_total(u, field):
    """跨分段汇总某字段；兼容旧扁平 usage（直接是 token 表）。"""
    if not isinstance(u, dict):
        return 0
    if "input" in u or "output" in u:
        return u.get(field, 0)
    return sum((v or {}).get(field, 0) for v in u.values() if isinstance(v, dict))

def cumulative_cost(usage, prices):
    """按价格库算出累计花费（跨模型求和，区分本币）。

    返回 ``(total_usd, total_cny, detail)``：
    - ``currency == "CNY"`` 的模型（deepseek 等 .cn 国产模型）价格按人民币
      原生计费，直接显示 ¥，不做美元换算；
    - 其余模型按 USD 计费，显示时再乘实时汇率换算 ¥。
    - 缺少价格的模型保留用量，cost 为 None，不计入已知费用小计。

    ``detail[model]`` 含分项金额 ``cost_in/cost_out/cost_cr/cost_cw``
    （均以该模型本币为单位）供花费明细行使用。峰谷模型按 legacy/peak/offpeak
    三档分别计价后求和；扁平模型三桶同价。
    """
    total_usd = 0.0
    total_cny = 0.0
    detail = {}
    for model, u in usage.items():
        key = price_key(model, prices)
        e = prices.get(key) or prices.get(model)
        if not e:
            detail[model] = {
                field: _usage_total(u, field)
                for field in ("input", "output", "cache_read", "cache_write")
            }
            detail[model]["cost"] = None
            continue
        currency = str(e.get("currency", "USD") or "USD").upper()
        if not isinstance(u, dict):
            continue
        if not any(isinstance(v, dict) for v in u.values()):
            u = {"flat": u}  # 兼容旧扁平 usage
        in_c = out_c = cr_c = cw_c = 0.0
        tok = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        unpriced = []
        for seg, ub in u.items():
            if not isinstance(ub, dict):
                continue
            for field in tok:
                tok[field] += ub.get(field, 0)
            rate = _segment_rate(e, seg)
            if not rate:
                if "calendar-unknown-" in seg:
                    unpriced.append(f"{seg.rsplit('-', 1)[-1]} 节假日表缺失，部分用量未计费")
                else:
                    unpriced.append("部分计费分段价格未知，未计费")
                continue
            i = ub.get("input", 0); o = ub.get("output", 0)
            cr = ub.get("cache_read", 0); cw = ub.get("cache_write", 0)
            in_c += i / 1e6 * rate.get("input", 0)
            out_c += o / 1e6 * rate.get("output", 0)
            cr_c += cr / 1e6 * rate.get("cache_read", 0)
            cw_rate = rate.get("cache_write", rate.get("input", 0))
            if e.get("provider") == "anthropic":
                one_hour = min(cw, ub.get("cache_write_1h", 0))
                hour_rate = rate.get("cache_write_1h", rate.get("input", 0) * 2)
                cw_c += ((cw - one_hour) * cw_rate + one_hour * hour_rate) / 1e6
            else:
                cw_c += cw / 1e6 * cw_rate
        c = in_c + out_c + cr_c + cw_c
        if currency == "CNY":
            total_cny += c
        else:
            total_usd += c
        detail[model] = {
            "input": tok["input"], "output": tok["output"],
            "cache_read": tok["cache_read"], "cache_write": tok["cache_write"],
            "cost": c, "currency": currency,
            "cost_in": in_c, "cost_out": out_c, "cost_cr": cr_c, "cost_cw": cw_c,
            "unpriced_reason": "; ".join(sorted(set(unpriced))),
        }
    return total_usd, total_cny, detail

def sync_price_command():
    root = Path(PRICE_DB).parent
    root.mkdir(parents=True, exist_ok=True)
    with _cache_lock(str(root / 'price_sync.lock')):
        return usage_store.sync_prices(_base_prices(), price_key, root / 'prices_online.json')


def import_usage(days=1):
    import time
    projects = Path(PRICE_DB).parent / 'projects'
    prices = load_prices()
    files = 0
    errors = []
    for path in projects.rglob('*.jsonl'):
        try:
            if path.stat().st_mtime < time.time() - days * 86400:
                continue
            get_cumulative_usage(str(path), prices)
            if LEDGER_ERROR:
                errors.append(LEDGER_ERROR)
            files += 1
        except (OSError, ValueError) as exc:
            errors.append(f'{type(exc).__name__}: {exc}')
    return {'files': files, 'errors': errors}


if len(sys.argv) > 1 and sys.argv[1] in ('--sync-prices', '--price-status', '--usage-import', '--usage-report', '--usage-web', '--help', '-h'):
    import argparse
    parser = argparse.ArgumentParser(description='Statusline price sync and per-request usage log')
    parser.add_argument('command', nargs='?')
    for flag in ('sync-prices', 'price-status', 'usage-import', 'usage-report', 'usage-web'):
        parser.add_argument('--' + flag, action='store_true')
    parser.add_argument('--days', type=float, default=1)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--output')
    args = parser.parse_args()
    root = Path(PRICE_DB).parent
    try:
        if args.sync_prices:
            print(json.dumps(sync_price_command(), ensure_ascii=False))
        elif args.price_status:
            print(json.dumps(usage_store.read_json(root / 'price_sync_status.json'), ensure_ascii=False, indent=2))
        elif args.usage_import:
            print(json.dumps(import_usage(args.days), ensure_ascii=False))
        elif args.usage_report:
            report = Path(args.output) if args.output else root / 'usage-report.html'
            report.write_text(usage_store.report_html(usage_store.read_requests(ledger_db()),
                              usage_store.read_json(root / 'price_sync_status.json')), encoding='utf-8')
            print(str(report.resolve()))
        elif args.usage_web:
            print(json.dumps(import_usage(args.days), ensure_ascii=False), flush=True)
            usage_store.serve_report(ledger_db(), root / 'price_sync_status.json', sync_price_command, args.port)
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if len(sys.argv) > 1 and sys.argv[1] == "--refresh-fx":
    get_usd_cny(refresh=True)
    sys.exit(0)

# 查单价：python ~/.claude/status-line.py --prices
if len(sys.argv) > 1 and sys.argv[1] == "--prices":
    prices = load_prices()
    rate = get_usd_cny()
    print(f"Rate: 1 USD = {rate:.4f} CNY ({FX_STATUS}; 30min cache; refresh in background)\n")
    names = [n for n in prices if not n.startswith("_")]
    mw = max([len(n) for n in names] + [len("model")])
    print(f"{'model':<{mw}} {'provider':<10} {'cur':>4} {'in':>9} {'out':>9} {'cache-read':>11}")
    print("-" * (mw + 46))
    for name, p in prices.items():
        if name.startswith("_"):
            continue
        if p.get("revisions"):
            revision = p["revisions"][-1]
            print(f"{name}: current since {revision['from']} (historical rates retained)")
            p = {**p, **revision["prices"]}
        currency = str(p.get("currency", "USD") or "USD").upper()
        unit = "¥" if currency == "CNY" else "$"
        if any(b in p for b in BUCKETS):
            print(f"{name:<{mw}} {p.get('provider','?'):<10} {currency:>4}  峰谷定价：")
            for bucket in ("legacy", "offpeak", "peak"):
                r = p.get(bucket)
                if not r:
                    continue
                print(f"    {bucket:<8} in {unit}{fmt_price(r.get('input',0)):>8}  "
                      f"out {unit}{fmt_price(r.get('output',0)):>8}  "
                      f"cache-read {unit}{fmt_price(r.get('cache_read',0)):>10}")
        elif "long" in p:
            print(f"{name:<{mw}} {p.get('provider','?'):<10} {currency:>4}  长上下文分档（阈值 {p.get('long_threshold',0)}）：")
            for seg in ("short", "long"):
                r = p if seg == "short" else p.get("long")
                if not r:
                    continue
                print(f"    {seg:<8} in {unit}{fmt_price(r.get('input',0)):>8}  "
                      f"out {unit}{fmt_price(r.get('output',0)):>8}  "
                      f"cache-read {unit}{fmt_price(r.get('cache_read',0)):>10}")
        else:
            inp, out = p.get("input", 0), p.get("output", 0)
            cr = p.get("cache_read", 0)
            print(f"{name:<{mw}} {p.get('provider','?'):<10} {currency:>4} "
                  f"{unit}{fmt_price(inp):>8} {unit}{fmt_price(out):>8} {unit}{fmt_price(cr):>10}")
    sys.exit(0)

# ── 解析 ──────────────────────────────────────────────
try:
    data = json.load(sys.stdin)
    if not isinstance(data, dict):
        raise TypeError("status input must be an object")
except (json.JSONDecodeError, TypeError):
    print("Status line: invalid input")
    sys.exit(0)

# ── 字段 ──────────────────────────────────────────────
model = data.get("model") or {}
if not isinstance(model, (str, dict)):
    model = {}
# 兼容两种格式：dict（{id, display_name}）或纯字符串（视觉模型等别名模型）。
if isinstance(model, str):
    model_id = model
    model_name = model
else:
    model_id = model.get("id") or model.get("display_name") or "?"
    model_name = model.get("display_name") or model_id
if isinstance(model_name, str) and "/" in model_name:
    model_name = model_name.split("/")[-1]
model_name = _re2.sub(r"\[\w+\]", "", model_name)  # 去掉 [1M]/[1m] 后缀
provider = model.get("provider") or model.get("vendor") or model.get("supplier") or "?" if isinstance(model, dict) else "?"

# Token 使用（真实字段在 context_window.current_usage）
ctx = data.get("context_window") or {}
cu = ctx.get("current_usage") or {}
inp   = ctx.get("total_input_tokens") or cu.get("input_tokens") or 0   # 累计输入
out   = ctx.get("total_output_tokens") or cu.get("output_tokens") or 0 # 累计输出
cache_write = cu.get("cache_creation_input_tokens")                    # 缓存写入
cache_read  = cu.get("cache_read_input_tokens")                        # 缓存读取
ctx_size  = ctx.get("context_window_size") or ctx.get("total_tokens") or ctx.get("max_tokens") or 0
used_pct     = ctx.get("used_percentage")
remaining_pct = ctx.get("remaining_percentage")
if remaining_pct is None and isinstance(used_pct, (int, float)):
    remaining_pct = max(0, min(100, 100 - used_pct))

# 会话时长 / 花费 / 消息数
cost_obj = data.get("cost") or {}
duration = cost_obj.get("total_duration_ms") or 0
api_duration = cost_obj.get("total_api_duration_ms") or 0  # 活跃 API 时长（排除空闲）
msg_count = data.get("message_count")

# 花费：按价格库 × transcript 累计用量（跨模型）。
# transcript 不可读时才退回 Claude Code 的 total_cost_usd。
_prices = load_prices()
_lookup_key = price_key(model_id, _prices)
_entry = _prices.get(_lookup_key) or _prices.get(model_name)
if provider in ("?", "") and _entry:
    provider = _entry.get("provider") or "?"
_transcript = data.get("transcript_path")
_cum_usage = {}
_cum_usd = None
_cum_cny = None
_cum_detail = {}
_custom_title = None   # 仅手动命名的会话名（/rename），AI 自动标题不采用
if _transcript and os.path.exists(_transcript):
    _cum_usage, duration, api_duration, _custom_title = get_cumulative_usage(
        _transcript, _prices, duration, api_duration)
    _cum_usd, _cum_cny, _cum_detail = cumulative_cost(_cum_usage, _prices)
    if not LEDGER_ERROR:
        _logged = usage_store.session_costs(ledger_db(), session_key(_transcript))
        if _logged:
            _cum_usd, _cum_cny, _cum_detail = _logged
_unknown_prices = any(d.get("cost") is None or d.get("unpriced_reason") for d in _cum_detail.values())
# transcript 不可读时退回 Claude Code 的 total_cost_usd（仅当有 USD 模型）。
_cost_usd_total = _cum_usd if _cum_usd is not None else float(cost_obj.get("total_cost_usd") or 0) or None
_rate = get_usd_cny()  # 共享汇率，供各行 ¥ 换算
maybe_sync_prices(_prices)

# 当前目录
cwd = data.get("cwd") or (data.get("workspace") or {}).get("current_dir") or ""
cwd_short = os.path.basename(cwd) if cwd else ""

# ── 颜色 ──────────────────────────────────────────────
CYAN   = "\033[0;36m"
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
MAGENTA= "\033[0;35m"
BLUE   = "\033[0;34m"
RED    = "\033[0;31m"
DIM    = "\033[2m"
GRAY   = "\033[97m"  # 亮白：标签/模型名在黑底上清晰可读
NC     = "\033[0m"

def dim(s):
    return f"{GRAY}{s}{NC}"
SEP = f"{DIM} · {NC}"  # 组间分隔符（淡色，低调）

# 供应商 → 颜色：模型名按供应商着色，跨模型一眼可辨
PROVIDER_COLOR = {
    "deepseek": "\033[0;36m",   # 青
    "moonshot": "\033[0;35m",   # 紫
    "minimax":  "\033[0;32m",   # 绿
    "zhipu":    "\033[0;32m",   # 绿
    "qwen":     "\033[0;35m",   # 紫
    "tencent":  "\033[1;36m",   # 亮青
    "hunyuan":  "\033[1;36m",   # 亮青
    "google":   "\033[1;34m",   # 亮蓝
    "openai":   "\033[0;37m",   # 白
    "xai":      "\033[1;33m",   # 琥珀
    "anthropic": "\033[0;34m",  # 蓝
    "xiaomi":   "\033[0;33m",   # 橙（小米 MiMo）
    "stepfun":  "\033[1;35m",   # 亮紫（阶跃 Step）
}
def provider_color(model):
    prov = (_prices.get(price_key(model, _prices)) or {}).get("provider", "")
    return PROVIDER_COLOR.get(prov, CYAN)

# ── 拼接 ──────────────────────────────────────────────
_model_tag = model_name if provider in ("?", "") else f"{model_name}@{provider}"
parts = [f"{provider_color(_lookup_key)}[{_model_tag}]{NC}"]

# 会话名——仅手动命名的（/rename、--name）才显示，放第一行做标识。
# AI 自动生成的标题常概括不准，故不采用（那份存在 transcript 的 ai-title 里）。
if _custom_title:
    parts.append(f"🏷 {MAGENTA}{_custom_title}{NC}")

# 推理强度 effort：模型不支持该参数时字段缺席（data.effort 不存在）。
# 强度越高思考 token 越多、越贵，故按 low→ultracode 由淡转浓着色。
_effort_raw = data.get("effort")
if isinstance(_effort_raw, dict):
    _effort = _effort_raw.get("level")          # 官方字段：effort.level
elif isinstance(_effort_raw, (str, int)):
    _effort = _effort_raw                       # 兼容直接给字符串/数字（子代理可为 token 预算）
else:
    _effort = None

# 全量档位：low < medium < high < xhigh < max，外加 Claude Code 特有的 ultracode
# （= xhigh 推理 + 自动多智能体编排）与 auto（跟随模型默认，仅 /effort 参数）。
_EFFORT_COLOR = {
    "low":       DIM,       # 淡：最省，简单任务
    "medium":    GREEN,     # 绿：平衡
    "high":      CYAN,      # 青：多数模型默认
    "xhigh":     YELLOW,    # 黄：更深推理（Opus 4.7 默认）
    "max":       RED,       # 红：最高，不限思考 token（仅限会话）
    "ultracode": MAGENTA,   # 紫：xhigh + 多智能体编排（仅限会话）
    "auto":      GRAY,      # 灰：跟随模型默认
}
# 数字档位（子代理的 token 预算）显示为 int
_effort_label = str(int(_effort)) if isinstance(_effort, int) else str(_effort or "")
if _effort_label:
    parts.append(f"{dim('effort')} {_EFFORT_COLOR.get(_effort_label, GRAY)}{_effort_label}{NC}")

# Token：输入 / 输出（文字标签 + 彩色数值，遵循 AI CLI 惯例）
in_str = f"{GREEN}{fmt(inp)}{NC}"
out_str = f"{MAGENTA}{fmt(out)}{NC}"
parts.append(f"{dim('in')} {in_str}")
parts.append(f"{dim('out')} {out_str}")

# 缓存
cache_strs = []
if cache_read:
    cache_strs.append(f"{dim('read')} {fmt(cache_read)}")
if cache_write:
    cache_strs.append(f"{dim('write')} {fmt(cache_write)}")
if cache_strs:
    parts.append(f"{dim('cache')} {CYAN}{','.join(cache_strs)}{NC}")

# ── 第二行：上下文进度条 / 输出速率（第一行只留模型与 token，避免过长）──
parts_ctx = []

# 上下文进度条（≤70% 绿、71–90% 黄、>90% 红 + ⚠ 剩余）
if ctx_size:
    if used_pct is not None:
        pct_val = used_pct
        bar_str = bar(pct_val)
        if pct_val > 90:
            parts_ctx.append(f"{RED}ctx {fmt(ctx_size)} [{bar_str}] {pct_val}% ⚠ {remaining_pct}% left{NC}")
        elif pct_val > 70:
            parts_ctx.append(f"{YELLOW}ctx {fmt(ctx_size)} [{bar_str}] {pct_val}% ⚠ {remaining_pct}% left{NC}")
        else:
            parts_ctx.append(f"{GREEN}ctx {fmt(ctx_size)} [{bar_str}] {pct_val}%{NC}")
    else:
        parts_ctx.append(f"{DIM}ctx {fmt(ctx_size)}{NC}")

# 提示缓存状态（原生 prompt_cache）：命中率 + 剩余 TTL；冷缓存标 ❄。
# 命中率直接决定输入成本，故 ≥80% 绿、≥50% 黄、更低红。
_pc = data.get("prompt_cache") or {}
if _pc.get("hit_ratio") is not None:
    _hr = float(_pc["hit_ratio"]) * 100
    _hr_color = GREEN if _hr >= 80 else (YELLOW if _hr >= 50 else RED)
    _pc_str = f"{_hr_color}{_hr:.0f}%{NC}"
    if not _pc.get("warm", True):
        _pc_str = f"{DIM}❄{NC} " + _pc_str
    if _pc.get("ttl"):
        _pc_str += f" {DIM}{_pc['ttl']}{NC}"
    parts_ctx.append(f"{dim('cache hit')} {_pc_str}")

# ── 第三行：花费 / 消息 / 目录 / 分支 / 时长 / 时钟 ──────
parts2 = []

# 会话花费：跨模型时标"总计"，单模型才标模型名。
# CNY 原生模型（deepseek 等 .cn）直接显示 ¥；USD 模型显示 $（并换算 ¥）。
if _cum_usd is not None or _cum_cny or _cost_usd_total is not None:
    _cost_label = _model_tag if len(_cum_detail) <= 1 else "total"
    if _unknown_prices:
        _cost_label += " (known prices only / 仅已知部分)"
    _cost_pieces = []
    if _cum_usd:
        _cost_pieces.append(f"{GREEN}${_cum_usd:.3f}{NC} ({MAGENTA}¥{_cum_usd * _rate:.2f}{NC})")
    if _cum_cny:
        _cost_pieces.append(f"{MAGENTA}¥{_cum_cny:.3f}{NC}")
    if not _cost_pieces and _cum_detail:
        currencies = {d.get("currency") for d in _cum_detail.values() if d.get("cost") is not None}
        if currencies == {"CNY"}:
            _cost_pieces.append(f"{MAGENTA}¥0.000{NC}")
        elif not currencies:
            _cost_pieces.append("暂无已知价格")
    if not _cost_pieces and _cost_usd_total is not None:
        _cost_pieces.append(f"{GREEN}${_cost_usd_total:.3f}{NC} ({MAGENTA}¥{_cost_usd_total * _rate:.2f}{NC})")
    if _cost_pieces:
        parts2.append(f"💰 {_cost_label} {' + '.join(_cost_pieces)}")
parts2.append(f"💱 1$={CYAN}{_rate:.2f}{NC}¥ ({FX_STATUS})")
if LEDGER_ERROR:
    parts2.append('⚠ 请求日志写入失败')

# 消息数
if msg_count is not None:
    parts2.append(f"💬 {msg_count}")

# 目录
if cwd_short:
    parts2.append(f"📁 {MAGENTA}{cwd_short}{NC}")

# git 分支
if cwd:
    try:
        import subprocess
        r = subprocess.run(["git", "-C", cwd, "branch", "--show-current"],
                            capture_output=True, text=True, timeout=2)
        branch = r.stdout.strip()
        if branch:
            parts2.append(f"🌿 {BLUE}{branch}{NC}")
    except Exception:
        pass

# worktree（原生 worktree.name：仅在 worktree 会话中出现）
_wt = (data.get("worktree") or {}).get("name")
if _wt:
    parts2.append(f"🌳 {GREEN}{_wt}{NC}")

# PR（原生 pr.number / review_state：仅在当前分支有打开的 PR 时出现）
_pr = data.get("pr") or {}
if _pr.get("number"):
    _pr_s = f"🔀 {BLUE}#{_pr['number']}{NC}"
    if _pr.get("review_state"):
        _pr_s += f" {DIM}{_pr['review_state']}{NC}"
    parts2.append(_pr_s)

# 子代理（原生 agent.name：--agent 或配置了 agent 时出现）
_agent = (data.get("agent") or {}).get("name")
if _agent:
    parts2.append(f"🤖 {CYAN}{_agent}{NC}")

# 时长
ds = fmt_duration(duration)
if ds:
    parts2.append(f"⏱ {ds}")

# 会话开关（原生字段，仅开启/非默认时显示，避免常态噪音）
_switches = []
if data.get("fast_mode"):
    _switches.append(f"{YELLOW}⚡fast{NC}")          # 快速模式：约 2x 价格
_vim = (data.get("vim") or {}).get("mode")           # vim 模式才出现
if _vim:
    _switches.append(f"{YELLOW}⌨{_vim}{NC}")
_ostyle = (data.get("output_style") or {}).get("name")
if _ostyle and _ostyle != "default":
    _switches.append(f"{MAGENTA}🎨{_ostyle}{NC}")
if _switches:
    parts2.append(" ".join(_switches))

# 速率限制窗口（原生 rate_limits：Claude.ai 订阅者首次响应后才有）
_rl = data.get("rate_limits") or {}
for _rl_label, _rl_key in (("5h", "five_hour"), ("7d", "seven_day")):
    _w = _rl.get(_rl_key) or {}
    if _w.get("used_percentage") is not None:
        _w_pct = float(_w["used_percentage"])
        _w_color = GREEN if _w_pct < 60 else (YELLOW if _w_pct < 85 else RED)
        parts2.append(f"⏳{_rl_label} {_w_color}{_w_pct:.0f}%{NC}")

# 时钟（年-月-日 + 时间 + 星期）
_weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_now = datetime.now()
parts2.append(f"🕐 {BLUE}{_now.strftime('%Y-%m-%d %H:%M:%S')} {_weekdays[_now.weekday()]}{NC}")

# 输出速率（累计输出 token / 活跃 API 时长秒）—— 与 ctx 同行，放第二行
_gen_time = (api_duration or duration) / 1000.0
_tot_out = sum(_usage_total(u, "output") for u in _cum_usage.values())
if _gen_time > 0 and _tot_out > 0:
    parts_ctx.append(f"{dim('rate')} {CYAN}{_tot_out/_gen_time:.0f} token/s{NC}")

# 第四行起：每个模型两行——一行 token，一行花费
parts3 = []
if _cum_detail:
    for model, d in sorted(_cum_detail.items(), key=lambda kv: -(kv[1]["cost"] or 0)):
        tok_line = f"{provider_color(model)}{model}{NC} · {dim('in')} {fmt(d['input'])}  {dim('out')} {fmt(d['output'])}"
        if d["cache_read"]:
            tok_line += f"  {dim('cache read')} {fmt(d['cache_read'])}"
        if d["cache_write"]:
            tok_line += f"  {dim('cache write')} {fmt(d['cache_write'])}"
        parts3.append(tok_line)
        if d.get("cost") is None:
            parts3.append(f"    {dim('价格未配置，未计入费用')}")
            continue
        if d.get("unpriced_reason"):
            parts3.append(f"    {YELLOW}{d['unpriced_reason']}{NC}")
        # 花费明细：金额单独一行，避免与 token 挤在一起。
        # 本币显示：CNY 模型只给 ¥；USD 模型给 $ + 换算 ¥。
        currency = d.get("currency", "USD")
        sub = []
        for label, ckey in (
            ("in", "cost_in"), ("out", "cost_out"),
            ("cache read", "cost_cr"), ("cache write", "cost_cw"),
        ):
            c = d.get(ckey)
            if not c:
                continue
            if currency == "CNY":
                sub.append(f"{dim(label)} {MAGENTA}¥{c:.3f}{NC}")
            else:
                sub.append(f"{dim(label)} {GREEN}${c:.3f}{NC}/{MAGENTA}¥{c * _rate:.2f}{NC}")
        if currency == "CNY":
            cost_str = f"{dim('cost')} {MAGENTA}¥{d['cost']:.3f}{NC}"
        else:
            cost_str = f"{dim('cost')} {GREEN}${d['cost']:.3f}{NC}/{MAGENTA}¥{d['cost'] * _rate:.2f}{NC}"
        parts3.append(f"    {cost_str}" + (f"  ({'  '.join(sub)})" if sub else ""))
else:
    parts3 = [f"{dim('in')} {fmt(inp)}  {dim('out')} {fmt(out)}"]
    if cache_read:
        parts3.append(f"{dim('cache read')} {fmt(cache_read)}")

_lines = [SEP.join(parts)]                 # 1) 模型 / effort / token
if parts_ctx:                              # 2) ctx 进度条 / 输出速率（无则整行省略）
    _lines.append(SEP.join(parts_ctx))
_lines.append(SEP.join(parts2))            # 3) 花费 / 消息 / 目录 / 分支 / 时长 / 时钟
_lines.append("\n".join(parts3))           # 4+) 各模型 token 与花费明细
print("\n".join(_lines))
