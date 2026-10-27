# Claude Code Status Line

A custom terminal status bar for [Claude Code](https://claude.com/claude-code): model, tokens, context progress bar, session cost ($ + ¥), live FX rate, message count, directory, git branch, duration, clock, and output rate.

## Preview

```
[deepseek-flash@deepseek] · effort xhigh · in 1.0M · out 500.0K · cache read 2.0M, write 200
ctx 1.0M [██████░░░░░░░░] 45% · rate 3714 token/s
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
- **Effort**: current reasoning effort — all levels covered (`low`/`medium`/`high`/`xhigh`/`max`, plus Claude Code's `ultracode` and `auto`, and numeric subagent token budgets), color-graded by cost (dim → green → cyan → yellow → red → magenta); hidden when the model doesn't support the effort parameter
- **Tokens**: `in` / `out` / `cache read` / `cache write` (bright-white labels, readable on dark terminals)
- **Context progress bar**: `ctx [██████░░░░░░░░] 45%`; green ≤70%, yellow 71–90%, red >90% + `⚠ X% left`
- **Cost**: locally estimated token × unit price, `$X (¥Y)` dual currency; models missing from the DB fall back to Claude Code's `total_cost_usd`. Multi-model sessions show `total`, single-model shows the model name
- **Native currency**: `currency: "CNY"` models (DeepSeek & other .cn domestic models) are billed in **¥ directly** from their RMB unit prices — no `$→¥` conversion. USD models show `$ + ¥`. Mixed sessions show `$… + ¥…`
- **Live FX rate**: `💱 1$=¥6.76` — real-time from Sina finance (on-shore USD/CNY), 30min cache, falls back to ExchangeRate-API. Note the on-shore CNY market is closed nights/weekends, so the rate legitimately holds still then
- **Per-model cost detail**: each model gets two lines — a token line + a money line (`cost $/¥`, with `in`/`out`/`cache read`/`cache write` sub-costs, each in `$/¥`)
- **Message count / directory / git branch / session duration / clock** (Y-M-D time weekday)
- **Native Claude Code fields** (each shown only when present): prompt-cache hit ratio + TTL, worktree, PR + review state, subagent, fast mode, vim mode, output style, 5h/7d rate-limit windows
- **Session name** on line 1 — only when you set it yourself with `/rename` (or `--name`). AI-generated titles are ignored because they often mis-summarise what actually happened
- **Output rate**: `rate` = cumulative output tokens / active API seconds, on line 2 next to the context bar

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
- Covered providers: deepseek (CNY .cn) / kimi (moonshot) / minimax / glm (zhipu) / qwen / hunyuan (tencent) / mimo (xiaomi) / step (stepfun) / gpt (openai) / grok (xai) / gemini (google) / claude (anthropic).
- **DeepSeek peak/off-peak** (verified 2026-10): peak = Mon–Fri (excluding Chinese public holidays) 09:00–12:00 & 14:00–18:00 Beijing time; everything else — including weekends and holidays — is off-peak at half the peak rate. `deepseek-flash` is now DeepSeek-V4.1-Flash-1017 (peak ¥2/¥0.04/¥8, off-peak ¥1/¥0.02/¥4); `deepseek-v4-pro` (V4-Pro-0813) is still served (peak ¥9/¥0.30/¥27, off-peak ¥4.5/¥0.15/¥13.5). Legacy names `deepseek-v4-flash` / `vision-exp` are retired but still accepted, and route to V4.1-Flash-1017 at Flash pricing.
- **New in 2026-10**: OpenAI `gpt-6` / `gpt-6.1`, Anthropic `Fable 5.1` / `Opus 5.5` / `Sonnet 5.5` / `Haiku 5.5`, xAI `Grok 4.7` / `4.20`, Google `Gemini 4 Argon` / `3.8 Flash`, Kimi `K3.1 Pro`, MiniMax `M3.1 Flash`, `GLM-5.3-FlashX`, Qwen3.8 Max/Plus/Flash-Next, Xiaomi `MiMo V2.6`, StepFun `Step 5 Preview`, Hunyuan `Hy4 preview`. Timing notes: Gemini 4 Argon is at promo pricing through 2026-11-30 (doubles on 12-01); Kimi K2 series retires end of Dec 2026.
- Prices are 2026 public API list prices and may change with channels/promotions — check the official pages. **To change prices, edit `model_prices.json`.**
- FX: fetched live from `open.er-api.com`, falls back to 7.2, cached 1h (`~/.claude/usd_cny.json`).

## License

MIT

---

# Claude Code Status Line（中文）

自定义的 [Claude Code](https://claude.com/claude-code) 终端状态栏：模型、Token、上下文进度条、会话花费（$ + ¥）、实时汇率、消息数、目录、git 分支、时长、时钟、输出速率。

## 效果

```
[deepseek-flash@deepseek] · effort xhigh · in 1.0M · out 500.0K · cache read 2.0M, write 200
ctx 1.0M [██████░░░░░░░░] 45% · rate 3714 token/s
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
- **推理强度 effort**：全量档位 `low`/`medium`/`high`/`xhigh`/`max`，外加 Claude Code 特有的 `ultracode` 和 `auto`，数字档（子代理 token 预算）也支持；按花费由淡到浓着色（淡→绿→青→黄→红→紫）；模型不支持该参数时自动隐藏
- **Token**：`in` / `out` / `cache read` / `cache write`（标签亮白，黑底清晰）
- **上下文进度条**：`ctx [██████░░░░░░░░] 45%`，≤70% 绿、71–90% 黄、>90% 红 + `⚠ X% left`
- **花费**：按 token × 单价本地估算，`$X (¥Y)` 双币显示；库里没有的模型退回 Claude Code 的 `total_cost_usd`。多模型会话标 `total`，单模型标模型名
- **本币计费**：`currency: "CNY"` 的模型（deepseek 等 .cn 国产模型）按人民币单价**原生显示 ¥**，不做美元换算；USD 模型显示 `$ + ¥`；混合会话显示 `$… + ¥…`
- **实时汇率**：`💱 1$=¥6.76`，取自新浪财经在岸美元人民币实时价，缓存 30 分钟，失败回退 ExchangeRate-API。注意在岸人民币夜间/周末休市，此时汇率本就几乎不动
- **花费明细**：每个模型独立两行——token 行 + 金额行（`cost $/¥` 括号内再分 `in`/`out`/`cache read`/`cache write`，每项都带 `$/¥`）
- **消息数 / 目录 / git 分支 / 会话时长 / 时钟**（年-月-日 时间 星期）
- **Claude Code 原生字段**（均在存在时才显示）：提示缓存命中率+TTL、worktree、PR+审查状态、子代理、快速模式、vim 模式、输出风格、5h/7d 速率限制窗口
- **会话名**（第一行）：仅在你用 `/rename`（或 `--name`）手动命名时显示；AI 自动生成的标题常概括不准，故忽略不显示
- **输出速率**：`rate` 累计输出 token / 活跃 API 秒，放第二行与上下文进度条同行

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
- 已收录：deepseek（CNY .cn）/ kimi (moonshot) / minimax / glm (zhipu) / qwen / hunyuan (tencent) / mimo (xiaomi) / step (stepfun) / gpt (openai) / grok (xai) / gemini (google) / claude (anthropic)。
- **DeepSeek 峰谷规则**（2026-10 核对）：北京时间周一至周五（不含法定节假日）9:00–12:00、14:00–18:00 为高峰，其余时段（含周末、法定节假日全天）为空闲，空闲价 = 高峰价一半。当前 `deepseek-flash` = DeepSeek-V4.1-Flash-1017（高峰 ¥2/¥0.04/¥8、空闲 ¥1/¥0.02/¥4）；`deepseek-v4-pro` = V4-Pro-0813，仍在服务（高峰 ¥9/¥0.30/¥27、空闲 ¥4.5/¥0.15/¥13.5）。旧名 `deepseek-v4-flash` / `vision-exp` 已下线但接口仍接受，请求落到 1017 并按 Flash 价计费。
- **2026-10 上新**：OpenAI `gpt-6` / `gpt-6.1` 系列、Anthropic `Fable 5.1` / `Opus 5.5` / `Sonnet 5.5` / `Haiku 5.5`、xAI `Grok 4.7` / `4.20`、Google `Gemini 4 Argon` / `3.8 Flash`、Kimi `K3.1 Pro`、MiniMax `M3.1 Flash`、`GLM-5.3-FlashX`、Qwen3.8 Max/Plus/Flash-Next、小米 `MiMo V2.6`、阶跃 `Step 5 Preview`、混元 `Hy4 preview`。时效提醒：Gemini 4 Argon 现为促销价（至 2026-11-30，12-01 起翻倍）；Kimi K2 系列 2026-12 月底下线。
- 价格源为 2026 年公开 API 定价，随渠道/活动变化，以官方为准——**改价格请编辑 `model_prices.json`**。
- 汇率：实时获取（`open.er-api.com`），失败回退 7.2，缓存 1 小时（`~/.claude/usd_cny.json`）。

## License

MIT
