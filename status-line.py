#!/usr/bin/env python3
"""Claude Code Status Line — 模型 / 输入输出Token / 上下文 / 目录 / 时长 / 时钟"""

import json
import sys
import os
from datetime import datetime

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
PRICE_DB = os.path.expanduser("~/.claude/model_prices.json")
USD_CNY_CACHE = os.path.expanduser("~/.claude/usd_cny.json")
USD_CNY_TTL = 3600  # 汇率缓存 1 小时

def load_prices():
    try:
        with open(PRICE_DB, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_usd_cny():
    """实时 USD→CNY 汇率（缓存 1 小时，失败回退 7.2）。"""
    import time as _t
    try:
        if os.path.exists(USD_CNY_CACHE):
            with open(USD_CNY_CACHE, encoding="utf-8") as f:
                c = json.load(f)
            if _t.time() - c.get("ts", 0) < USD_CNY_TTL and c.get("rate"):
                return c["rate"]
    except Exception:
        pass
    try:
        import urllib.request
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r:
            d = json.loads(r.read().decode())
        rate = float(d["rates"]["CNY"])
        try:
            with open(USD_CNY_CACHE, "w", encoding="utf-8") as f:
                json.dump({"ts": _t.time(), "rate": rate}, f)
        except Exception:
            pass
        return rate
    except Exception:
        try:
            with open(USD_CNY_CACHE, encoding="utf-8") as f:
                return json.load(f).get("rate", 7.2)
        except Exception:
            return 7.2

def fmt_price(x):
    return f"{x:.5f}".rstrip("0").rstrip(".")

# ── 累计用量（增量读 transcript，避免每秒全量解析）────────
USAGE_CACHE = os.path.expanduser("~/.claude/usage_cache.json")

def get_cumulative_usage(transcript_path):
    """增量累计每模型的 token 用量（只处理新增行）。"""
    cache = {"offset": 0, "usage": {}}
    try:
        with open(USAGE_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        pass
    if not isinstance(cache.get("usage"), dict):
        cache["usage"] = {}
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            f.seek(int(cache.get("offset", 0)))
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("type") == "assistant":
                    m = rec.get("message") or {}
                    u = m.get("usage") or {}
                    model = str(m.get("model") or "unknown")
                    e = cache["usage"].setdefault(
                        model, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
                    e["input"] += int(u.get("input_tokens", 0) or 0)
                    e["output"] += int(u.get("output_tokens", 0) or 0)
                    e["cache_read"] += int(u.get("cache_read_input_tokens", 0) or 0)
                    e["cache_write"] += int(u.get("cache_creation_input_tokens", 0) or 0)
            cache["offset"] = f.tell()
    except Exception:
        pass
    try:
        with open(USAGE_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass
    return cache["usage"]

def cumulative_cost(usage, prices):
    """按价格库算出累计花费（跨模型求和，区分本币）。

    返回 ``(total_usd, total_cny, detail)``：
    - ``currency == "CNY"`` 的模型（deepseek 等 .cn 国产模型）价格按人民币
      原生计费，直接显示 ¥，不做美元换算；
    - 其余模型按 USD 计费，显示时再乘实时汇率换算 ¥。

    ``detail[model]`` 含分项金额 ``cost_in/cost_out/cost_cr/cost_cw``
    （均以该模型本币为单位）供花费明细行使用。
    """
    total_usd = 0.0
    total_cny = 0.0
    detail = {}
    for model, u in usage.items():
        key = _re2.sub(r"\[\w+\]", "", model) if model else ""
        e = prices.get(key) or prices.get(model)
        if not e:
            continue
        currency = str(e.get("currency", "USD") or "USD").upper()
        in_c = u["input"] / 1e6 * e.get("input", 0)
        out_c = u["output"] / 1e6 * e.get("output", 0)
        cr_c = u["cache_read"] / 1e6 * e.get("cache_read", 0)
        cw_c = u["cache_write"] / 1e6 * e.get("cache_write", e.get("input", 0))
        c = in_c + out_c + cr_c + cw_c
        if currency == "CNY":
            total_cny += c
        else:
            total_usd += c
        detail[model] = {
            "input": u["input"], "output": u["output"],
            "cache_read": u["cache_read"], "cache_write": u["cache_write"],
            "cost": c, "currency": currency,
            "cost_in": in_c, "cost_out": out_c, "cost_cr": cr_c, "cost_cw": cw_c,
        }
    return total_usd, total_cny, detail

def _component_costs(usage, prices):
    """跨模型累加每个分项（输入/输出/缓存读/缓存写）的花费。"""
    in_c = out_c = cr_c = cw_c = 0.0
    for model, u in usage.items():
        key = _re2.sub(r"\[\w+\]", "", model) if model else ""
        e = prices.get(key) or prices.get(model)
        if not e:
            continue
        in_c += u["input"] / 1e6 * e.get("input", 0)
        out_c += u["output"] / 1e6 * e.get("output", 0)
        cr_c += u["cache_read"] / 1e6 * e.get("cache_read", 0)
        cw_c += u["cache_write"] / 1e6 * e.get("cache_write", e.get("input", 0))
    return in_c, out_c, cr_c, cw_c

# 查单价：python ~/.claude/status-line.py --prices
if len(sys.argv) > 1 and sys.argv[1] == "--prices":
    prices = load_prices()
    rate = get_usd_cny()
    print(f"Rate: 1 USD = {rate:.4f} CNY (live, 1h cache)\n")
    print(f"{'model':<20} {'provider':<10} {'cur':>4} {'in':>9} {'out':>9} {'cache-read':>11}")
    print("-" * 66)
    for name, p in prices.items():
        if name.startswith("_"):
            continue
        currency = str(p.get("currency", "USD") or "USD").upper()
        inp, out = p.get("input", 0), p.get("output", 0)
        cr = p.get("cache_read", 0)
        unit = "¥" if currency == "CNY" else "$"
        print(f"{name:<20} {p.get('provider','?'):<10} {currency:>4} "
              f"{unit}{fmt_price(inp):>8} {unit}{fmt_price(out):>8} {unit}{fmt_price(cr):>10}")
    sys.exit(0)

# ── 解析 ──────────────────────────────────────────────
try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, TypeError):
    print("Status line: invalid input")
    sys.exit(0)

# ── 字段 ──────────────────────────────────────────────
model = data.get("model", {})
model_id = model.get("id") or model.get("display_name") or "?"
model_name = model.get("display_name") or model_id
if isinstance(model_name, str) and "/" in model_name:
    model_name = model_name.split("/")[-1]
import re as _re2
model_name = _re2.sub(r"\[\w+\]", "", model_name)  # 去掉 [1M]/[1m] 后缀
provider = model.get("provider") or model.get("vendor") or model.get("supplier") or "?"

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

# 会话时长 / 花费 / 消息数
cost_obj = data.get("cost") or {}
duration = cost_obj.get("total_duration_ms") or 0
api_duration = cost_obj.get("total_api_duration_ms") or 0  # 活跃 API 时长（排除空闲）
msg_count = data.get("message_count")

# 花费：按价格库 × transcript 累计用量（跨模型）。
# transcript 不可读时才退回 Claude Code 的 total_cost_usd。
_prices = load_prices()
_lookup_key = _re2.sub(r"\[\w+\]", "", model_name or "")
_entry = _prices.get(_lookup_key) or _prices.get(model_name)
_transcript = data.get("transcript_path")
_cum_usage = {}
_cum_usd = None
_cum_cny = None
_cum_comp = None
_cum_detail = {}
if _transcript and os.path.exists(_transcript):
    _cum_usage = get_cumulative_usage(_transcript)
    _cum_usd, _cum_cny, _cum_detail = cumulative_cost(_cum_usage, _prices)
    _cum_comp = _component_costs(_cum_usage, _prices)
# transcript 不可读时退回 Claude Code 的 total_cost_usd（仅当有 USD 模型）。
_cost_usd_total = _cum_usd if _cum_usd is not None else float(cost_obj.get("total_cost_usd") or 0) or None
_rate = get_usd_cny()  # 共享汇率，供各行 ¥ 换算

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
    "openai":   "\033[0;37m",   # 白
    "xai":      "\033[1;33m",   # 琥珀
    "anthropic": "\033[0;34m",  # 蓝
}
def provider_color(model):
    prov = (_prices.get(model) or {}).get("provider", "")
    return PROVIDER_COLOR.get(prov, CYAN)

# ── 拼接 ──────────────────────────────────────────────
_model_tag = model_name if provider in ("?", "") else f"{model_name}@{provider}"
parts = [f"{provider_color(_lookup_key)}[{_model_tag}]{NC}"]

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

# 上下文进度条（≤70% 绿、71–90% 黄、>90% 红 + ⚠ 剩余）
if ctx_size:
    if used_pct is not None:
        pct_val = used_pct
        bar_str = bar(pct_val)
        if pct_val > 90:
            parts.append(f"{RED}ctx {fmt(ctx_size)} [{bar_str}] {pct_val}% ⚠ {remaining_pct}% left{NC}")
        elif pct_val > 70:
            parts.append(f"{YELLOW}ctx {fmt(ctx_size)} [{bar_str}] {pct_val}% ⚠ {remaining_pct}% left{NC}")
        else:
            parts.append(f"{GREEN}ctx {fmt(ctx_size)} [{bar_str}] {pct_val}%{NC}")
    else:
        parts.append(f"{DIM}ctx {fmt(ctx_size)}{NC}")

# ── 第二行：花费 / 消息 / 目录 / 分支 / 时长 / 时钟 ──────
parts2 = []

# 会话花费：跨模型时标"总计"，单模型才标模型名。
# CNY 原生模型（deepseek 等 .cn）直接显示 ¥；USD 模型显示 $（并换算 ¥）。
if _cum_usd is not None or _cum_cny or _cost_usd_total is not None:
    _cost_label = _model_tag if len(_cum_detail) <= 1 else "total"
    _cost_pieces = []
    if _cum_usd:
        _cost_pieces.append(f"{GREEN}${_cum_usd:.3f}{NC} ({MAGENTA}¥{_cum_usd * _rate:.2f}{NC})")
    if _cum_cny:
        _cost_pieces.append(f"{MAGENTA}¥{_cum_cny:.3f}{NC}")
    if not _cost_pieces and _cost_usd_total is not None:
        _cost_pieces.append(f"{GREEN}${_cost_usd_total:.3f}{NC} ({MAGENTA}¥{_cost_usd_total * _rate:.2f}{NC})")
    if _cost_pieces:
        parts2.append(f"💰 {_cost_label} {' + '.join(_cost_pieces)}")
parts2.append(f"💱 1$={CYAN}{_rate:.2f}{NC}¥")

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

# 时长
ds = fmt_duration(duration)
if ds:
    parts2.append(f"⏱ {ds}")

# 时钟（年-月-日 + 时间 + 星期）
_weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_now = datetime.now()
parts2.append(f"🕐 {BLUE}{_now.strftime('%Y-%m-%d %H:%M:%S')} {_weekdays[_now.weekday()]}{NC}")

# 输出速率（累计输出 token / 活跃 API 时长秒）放第一行
_gen_time = (api_duration or duration) / 1000.0
_tot_out = sum(u["output"] for u in _cum_usage.values())
if _gen_time > 0 and _tot_out > 0:
    parts.append(f"{dim('rate')} {CYAN}{_tot_out/_gen_time:.0f} token/s{NC}")

# 第三行起：每个模型两行——一行 token，一行花费
parts3 = []
if _cum_detail:
    for model, d in sorted(_cum_detail.items(), key=lambda kv: -kv[1]["cost"]):
        tok_line = f"{provider_color(model)}{model}{NC} · {dim('in')} {fmt(d['input'])}  {dim('out')} {fmt(d['output'])}"
        if d["cache_read"]:
            tok_line += f"  {dim('cache read')} {fmt(d['cache_read'])}"
        if d["cache_write"]:
            tok_line += f"  {dim('cache write')} {fmt(d['cache_write'])}"
        parts3.append(tok_line)
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

print(SEP.join(parts) + "\n" + SEP.join(parts2) + "\n" + "\n".join(parts3))
