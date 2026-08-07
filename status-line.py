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

# 花费：优先用价格库按 token 估算；库里没有则退回 total_cost_usd
import re as _re
_lookup_key = _re.sub(r"\[.*\]", "", model_name or "")
_prices = load_prices()
_entry = _prices.get(_lookup_key) or _prices.get(model_name)
cost_usd = None
if _entry:
    cost_usd = (inp / 1e6 * _entry.get("input", 0)
                + out / 1e6 * _entry.get("output", 0)
                + (cache_read or 0) / 1e6 * _entry.get("cache_read", 0)
                + (cache_write or 0) / 1e6 * _entry.get("cache_write", _entry.get("input", 0)))
else:
    cost_usd = cost_obj.get("total_cost_usd")

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

# ── 拼接 ──────────────────────────────────────────────
_model_tag = model_name if provider in ("?", "") else f"{model_name}@{provider}"
parts = [f"{CYAN}[{_model_tag}]{NC}"]

# Token: 输入 / 输出
in_str = f"{GREEN}{fmt(inp)}{NC}"
out_str = f"{GREEN}{fmt(out)}{NC}"
parts.append(f"⬇ {in_str}  ⬆ {out_str}")

# 缓存
cache_strs = []
if cache_read:
    cache_strs.append(f"读{fmt(cache_read)}")
if cache_write:
    cache_strs.append(f"写{fmt(cache_write)}")
if cache_strs:
    parts.append(f"💾 {','.join(cache_strs)}")

# Context 窗口（进度条 + 百分比；>70% 黄、>90% 红 + 剩余警示）
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
    parts2.append(f"💰 {_model_tag} ${float(cost_usd):.3f} (¥{float(cost_usd) * _rate:.2f})")

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

# 第一行（模型/Token/缓存/上下文） + 换行 + 第二行
print("  ".join(parts) + "\n" + "  ".join(parts2))
