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
    """按价格库算出累计花费（跨模型求和）。返回 (总花费, 明细dict)。"""
    total = 0.0
    detail = {}
    for model, u in usage.items():
        key = _re2.sub(r"\[\w+\]", "", model) if model else ""
        e = prices.get(key) or prices.get(model)
        if not e:
            continue
        c = (u["input"] / 1e6 * e.get("input", 0)
             + u["output"] / 1e6 * e.get("output", 0)
             + u["cache_read"] / 1e6 * e.get("cache_read", 0)
             + u["cache_write"] / 1e6 * e.get("cache_write", e.get("input", 0)))
        total += c
        detail[model] = {
            "input": u["input"], "output": u["output"],
            "cache_read": u["cache_read"], "cache_write": u["cache_write"], "cost": c,
        }
    return total, detail

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
    print(f"汇率：1 USD = {rate:.4f} CNY（实时，缓存1小时）\n")
    print(f"{'模型':<20}{'供应商':<10}{'输入$':>10}{'输出$':>10}{'缓存读$':>10}{'输入¥':>10}{'输出¥':>10}")
    print("-" * 84)
    for name, p in prices.items():
        if name.startswith("_"):
            continue
        inp, out = p.get("input", 0), p.get("output", 0)
        cr = p.get("cache_read", 0)
        print(f"{name:<20}{p.get('provider','?'):<10}"
              f"{fmt_price(inp):>10}{fmt_price(out):>10}{fmt_price(cr):>10}"
              f"{fmt_price(inp*rate):>10}{fmt_price(out*rate):>10}")
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
msg_count = data.get("message_count")

# 花费：按价格库 × transcript 累计用量（跨模型）。
# transcript 不可读时才退回 Claude Code 的 total_cost_usd。
_prices = load_prices()
_lookup_key = _re2.sub(r"\[\w+\]", "", model_name or "")
_entry = _prices.get(_lookup_key) or _prices.get(model_name)
_transcript = data.get("transcript_path")
_cum_usage = {}
_cum_cost = None
_cum_comp = None
if _transcript and os.path.exists(_transcript):
    _cum_usage = get_cumulative_usage(_transcript)
    _cum_cost, _cum_detail = cumulative_cost(_cum_usage, _prices)
    _cum_comp = _component_costs(_cum_usage, _prices)
cost_usd = _cum_cost if _cum_cost is not None else float(cost_obj.get("total_cost_usd") or 0) or None

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
NC     = "\033[0m"

def dim(s):
    return f"{DIM}{s}{NC}"
SEP = f"{DIM} · {NC}"  # 组间分隔符

# ── 拼接 ──────────────────────────────────────────────
_model_tag = model_name if provider in ("?", "") else f"{model_name}@{provider}"
parts = [f"{CYAN}[{_model_tag}]{NC}"]

# Token: ⬇ 输入 / ⬆ 输出（不同颜色）
in_str = f"{GREEN}{fmt(inp)}{NC}"
out_str = f"{MAGENTA}{fmt(out)}{NC}"
parts.append(f"⬇ {in_str}")
parts.append(f"⬆ {out_str}")

# 缓存 💾
cache_strs = []
if cache_read:
    cache_strs.append(f"读 {fmt(cache_read)}")
if cache_write:
    cache_strs.append(f"写 {fmt(cache_write)}")
if cache_strs:
    parts.append(f"💾 {CYAN}{','.join(cache_strs)}{NC}")

# 上下文 ▮ 进度条（≤70% 绿、71–90% 黄、>90% 红 + ⚠ 剩余）
if ctx_size:
    if used_pct is not None:
        pct_val = used_pct
        bar_str = bar(pct_val)
        if pct_val > 90:
            parts.append(f"{RED}▮ {fmt(ctx_size)} [{bar_str}] {pct_val}% ⚠ 剩{remaining_pct}%{NC}")
        elif pct_val > 70:
            parts.append(f"{YELLOW}▮ {fmt(ctx_size)} [{bar_str}] {pct_val}% ⚠ 剩{remaining_pct}%{NC}")
        else:
            parts.append(f"{GREEN}▮ {fmt(ctx_size)} [{bar_str}] {pct_val}%{NC}")
    else:
        parts.append(f"{DIM}▮ {fmt(ctx_size)}{NC}")

# ── 第二行：花费 / 消息 / 目录 / 分支 / 时长 / 时钟 ──────
parts2 = []

# 会话花费（$ + ¥，标注模型 + 供应商）
if cost_usd is not None:
    _rate = get_usd_cny()
    parts2.append(f"💰 {_model_tag} {GREEN}${float(cost_usd):.3f}{NC} "
                  f"({MAGENTA}¥{float(cost_usd) * _rate:.2f}{NC})")

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
_weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_now = datetime.now()
parts2.append(f"🕐 {BLUE}{_now.strftime('%Y-%m-%d %H:%M:%S')} {_weekdays[_now.weekday()]}{NC}")

# 第三行：累计话费明细（transcript 累计用量 × 价格库）+ 输出速率
parts3 = []
if _cum_comp is not None:
    in_c, out_c, cr_c, cw_c = _cum_comp
    tot_in = sum(u["input"] for u in _cum_usage.values())
    tot_out = sum(u["output"] for u in _cum_usage.values())
    tot_cr = sum(u["cache_read"] for u in _cum_usage.values())
    tot_cw = sum(u["cache_write"] for u in _cum_usage.values())
    parts3.append(f"{dim('累计')} {dim('输入')} {fmt(tot_in)}→{GREEN}${in_c:.3f}{NC}  "
                  f"{dim('输出')} {fmt(tot_out)}→{GREEN}${out_c:.3f}{NC}")
    if tot_cr:
        parts3.append(f"{dim('缓存读')} {fmt(tot_cr)}→{GREEN}${cr_c:.3f}{NC}")
    if tot_cw:
        parts3.append(f"{dim('缓存写')} {fmt(tot_cw)}→{GREEN}${cw_c:.3f}{NC}")
    # 输出速率（累计输出 token / 会话时长秒）
    if duration > 0 and tot_out > 0:
        rate = tot_out / (duration / 1000.0)
        parts3.append(f"{dim('输出速率')} {CYAN}{rate:.0f} tok/s{NC}")
else:
    parts3 = [f"{dim('输入')} {fmt(inp)}  {dim('输出')} {fmt(out)}"]
    if cache_read:
        parts3.append(f"{dim('缓存读')} {fmt(cache_read)}")

# 第四行：跨模型时列出历史用过的所有模型及其花费
parts4 = []
if len(_cum_detail) > 1:
    models_str = SEP.join(
        f"{dim(m)} {GREEN}${d['cost']:.3f}{NC}" for m, d in
        sorted(_cum_detail.items(), key=lambda kv: -kv[1]["cost"]))
    parts4.append(f"{dim('模型')} {models_str}")

_line4 = "\n" + SEP.join(parts4) if parts4 else ""
print(SEP.join(parts) + "\n" + SEP.join(parts2) + "\n" + SEP.join(parts3) + _line4)
