# Claude Code Status Line

A custom terminal status bar for [Claude Code](https://claude.com/claude-code): model, tokens, context progress bar, session cost ($ + ¥), live FX rate, message count, directory, git branch, duration, clock, and output rate.

## Preview

```
[deepseek-v4-flash@deepseek] · in 1.0M · out 500.0K · cache read 2.0M, write 200 · ctx 1.0M [██████░░░░░░░░] 45% · rate 3714 token/s
💰 total $4.787 (¥32.37) · 💱 1$=6.76¥ · 💬 42 · 📁 Kaggriculture · 🌿 main · ⏱ 0h14m · 🕐 2026-08-07 16:39:28 Fri
deepseek-v4-flash · in 3.4M  out 2.2M  cache read 931.2M
    cost $3.703/¥25.04  (in $0.478/¥3.23  out $0.618/¥4.18  cache read $2.607/¥17.63)
grok-4.5 · in 59.6K  out 22.8K  cache read 1.9M  cache write 124.8K
    cost $1.084/¥7.33  (in $0.119/¥0.81  out $0.137/¥0.92  cache read $0.578/¥3.91  cache write $0.250/¥1.69)
```

## Install

```bash
# 1. Copy the script and price DB to ~/.claude/
cp status-line.py ~/.claude/
cp model_prices.json ~/.claude/

# 2. Configure statusLine in ~/.claude/settings.json
```

`~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "PYTHONIOENCODING=utf-8 python ~/.claude/status-line.py",
    "refreshInterval": 1
  }
}
```

## Features

- **Model + provider**: `[model@provider]`, colored per provider
- **Tokens**: `in` / `out` / `cache read` / `cache write` (bright-white labels, readable on dark terminals)
- **Context progress bar**: `ctx [██████░░░░░░░░] 45%`; green ≤70%, yellow 71–90%, red >90% + `⚠ X% left`
- **Cost**: locally estimated token × unit price, `$X (¥Y)` dual currency; models missing from the DB fall back to Claude Code's `total_cost_usd`. Multi-model sessions show `total`, single-model shows the model name
- **Native currency**: `currency: "CNY"` models (DeepSeek & other .cn domestic models) are billed in **¥ directly** from their RMB unit prices — no `$→¥` conversion. USD models show `$ + ¥`. Mixed sessions show `$… + ¥…`
- **Live FX rate**: `💱 1$=¥6.76`, real-time with 1h cache (fallback 7.2)
- **Per-model cost detail**: each model gets two lines — a token line + a money line (`cost $/¥`, with `in`/`out`/`cache read`/`cache write` sub-costs, each in `$/¥`)
- **Message count / directory / git branch / session duration / clock** (Y-M-D time weekday)
- **Output rate**: `rate` = cumulative output tokens / active API seconds, on line 1

## Prices

```bash
python ~/.claude/status-line.py --prices
```

Prints unit prices in **$ and ¥** (live FX, 1h cache):

```
Rate: 1 USD = 6.7634 CNY (live, 1h cache)

model                provider           in $      out $  cache-read $      in ¥      out ¥  cache-read ¥
--------------------------------------------------------------------------------------------------------
deepseek-v4-flash   deepseek        0.14      0.28    0.0028   0.94688   1.89376     0.01894
...
```

## Pricing notes

- Price DB: `model_prices.json` (per-1M-token prices). `currency: "CNY"` entries are **¥ / 1M tokens** (e.g. DeepSeek .cn), everything else is USD — edit it and the status line picks it up automatically.
- Covered providers: deepseek (CNY .cn) / kimi (moonshot) / minimax / glm (zhipu) / gpt (openai) / grok (xai) / claude (anthropic).
- Prices are 2026 public API list prices and may change with channels/promotions — check the official pages. **To change prices, edit `model_prices.json`.**
- FX: fetched live from `open.er-api.com`, falls back to 7.2, cached 1h (`~/.claude/usd_cny.json`).

## License

MIT

---

# Claude Code Status Line（中文）

自定义的 [Claude Code](https://claude.com/claude-code) 终端状态栏：模型、Token、上下文进度条、会话花费（$ + ¥）、实时汇率、消息数、目录、git 分支、时长、时钟、输出速率。

## 效果

```
[deepseek-v4-flash@deepseek] · in 1.0M · out 500.0K · cache read 2.0M, write 200 · ctx 1.0M [██████░░░░░░░░] 45% · rate 3714 token/s
💰 total $4.787 (¥32.37) · 💱 1$=6.76¥ · 💬 42 · 📁 Kaggriculture · 🌿 main · ⏱ 0h14m · 🕐 2026-08-07 16:39:28 Fri
deepseek-v4-flash · in 3.4M  out 2.2M  cache read 931.2M
    cost $3.703/¥25.04  (in $0.478/¥3.23  out $0.618/¥4.18  cache read $2.607/¥17.63)
grok-4.5 · in 59.6K  out 22.8K  cache read 1.9M  cache write 124.8K
    cost $1.084/¥7.33  (in $0.119/¥0.81  out $0.137/¥0.92  cache read $0.578/¥3.91  cache write $0.250/¥1.69)
```

## 安装

```bash
# 1. 把脚本和价格库放到 ~/.claude/
cp status-line.py ~/.claude/
cp model_prices.json ~/.claude/

# 2. 在 ~/.claude/settings.json 里配置 statusLine
```

`~/.claude/settings.json`：

```json
{
  "statusLine": {
    "type": "command",
    "command": "PYTHONIOENCODING=utf-8 python ~/.claude/status-line.py",
    "refreshInterval": 1
  }
}
```

## 功能

- **模型 + 供应商**：`[model@provider]`，按供应商着色
- **Token**：`in` / `out` / `cache read` / `cache write`（标签亮白，黑底清晰）
- **上下文进度条**：`ctx [██████░░░░░░░░] 45%`，≤70% 绿、71–90% 黄、>90% 红 + `⚠ X% left`
- **花费**：按 token × 单价本地估算，`$X (¥Y)` 双币显示；库里没有的模型退回 Claude Code 的 `total_cost_usd`。多模型会话标 `total`，单模型标模型名
- **本币计费**：`currency: "CNY"` 的模型（deepseek 等 .cn 国产模型）按人民币单价**原生显示 ¥**，不做美元换算；USD 模型显示 `$ + ¥`；混合会话显示 `$… + ¥…`
- **实时汇率**：`💱 1$=¥6.76`，缓存 1 小时，失败回退 7.2
- **花费明细**：每个模型独立两行——token 行 + 金额行（`cost $/¥` 括号内再分 `in`/`out`/`cache read`/`cache write`，每项都带 `$/¥`）
- **消息数 / 目录 / git 分支 / 会话时长 / 时钟**（年-月-日 时间 星期）
- **输出速率**：`rate` 累计输出 token / 活跃 API 秒，放第一行

## 查单价（价格库）

```bash
python ~/.claude/status-line.py --prices
```

输出所有模型的 **$ 和 ¥** 单价（实时汇率，缓存 1 小时）：

```
Rate: 1 USD = 6.7634 CNY (live, 1h cache)

model                provider           in $      out $  cache-read $      in ¥      out ¥  cache-read ¥
--------------------------------------------------------------------------------------------------------
deepseek-v4-flash   deepseek        0.14      0.28    0.0028   0.94688   1.89376     0.01894
...
```

## 价格

- 价格库：`model_prices.json`（每 1M token 单价）。`currency: "CNY"` 的条目是 **¥/1M tokens**（如 deepseek .cn），其余为美元——直接编辑即可生效。
- 已收录：deepseek（CNY .cn）/ kimi (moonshot) / minimax / glm (zhipu) / gpt (openai) / grok (xai) / claude (anthropic)。
- 价格源为 2026 年公开 API 定价，随渠道/活动变化，以官方为准——**改价格请编辑 `model_prices.json`**。
- 汇率：实时获取（`open.er-api.com`），失败回退 7.2，缓存 1 小时（`~/.claude/usd_cny.json`）。

## License

MIT
