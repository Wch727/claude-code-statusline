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
cp status-line.py statusline_store.py ccswitch_compat.py usage_report.html model_prices.json ~/.claude/
cp vendor/cc-switch/LICENSE ~/.claude/CC_SWITCH_LICENSE

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
- **Cost**: locally estimated token × unit price, `$X (¥Y)` dual currency; models without configured prices retain token counts and show a price-not-configured label; totals include only known prices and are marked as partial. A missing price does not identify the connection provider. When no transcript is available, Claude Code's `total_cost_usd` is used. Multi-model sessions show `total`, single-model shows the model name
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

Prints unit prices in **$ and ¥** (cached FX, 30min cache; background refresh):

```
Rate: 1 USD = 6.7634 CNY (缓存; 30min cache; refresh in background)

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
- FX: Sina first, then ExchangeRate-API; cached for 30 minutes (`~/.claude/usd_cny.json`). Expired rates refresh in a background process; the status bar immediately uses the last cached rate, or 7.2 on first run. Failed refreshes retry after one minute.

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
cp status-line.py statusline_store.py ccswitch_compat.py usage_report.html model_prices.json ~/.claude/
cp vendor/cc-switch/LICENSE ~/.claude/CC_SWITCH_LICENSE

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
- **花费**：按 token × 单价本地估算，`$X (¥Y)` 双币显示；库里没有的模型保留用量并标注“价格未配置，未计入费用”，费用只累计已知部分并注明，不根据价格缺失推断接入供应商；没有会话记录时使用 Claude Code 的 `total_cost_usd`。多模型会话标 `total`，单模型标模型名
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

输出所有模型的 **$ 和 ¥** 单价（缓存汇率，缓存 30 分钟、后台刷新）：

```
Rate: 1 USD = 6.7634 CNY (缓存; 30min cache; refresh in background)

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
- 汇率：优先新浪，失败再尝试 ExchangeRate-API；缓存 30 分钟（`~/.claude/usd_cny.json`）。过期后后台刷新，状态栏立即使用旧缓存，首次运行无缓存则暂用 7.2；刷新失败后一分钟再试。

## License

MIT


## Windows (PowerShell 7)

```powershell
New-Item -ItemType Directory -Force "$HOME/.claude" | Out-Null
Copy-Item ./status-line.py, ./statusline_store.py, ./ccswitch_compat.py, ./usage_report.html, ./model_prices.json "$HOME/.claude/"
Copy-Item ./vendor/cc-switch/LICENSE "$HOME/.claude/CC_SWITCH_LICENSE"
```

Merge into `~/.claude/settings.json` / 合并到设置文件（Python 路径含空格时也适用）：

```json
{
  "statusLine": {
    "type": "command",
    "command": "python \"C:/Users/YOUR_NAME/.claude/status-line.py\""
  }
}
```

Replace `YOUR_NAME` with your Windows username. / 将 `YOUR_NAME` 替换为你的 Windows 用户名。

## Tests / 回归测试

```sh
python -m unittest -v test_status_line test_store test_ccswitch_compat
```

Tests use temporary files inside the repository and simulated FX responses; they do not change your Claude settings or contact pricing/FX services.
测试使用仓库内临时文件及模拟汇率响应，不修改 Claude 设置，不连接价格或汇率服务。


## Cache and pricing accuracy / 缓存与计价说明

- Usage cache updates use an OS process lock and atomic replacement, including when multiple Claude Code sessions refresh together. OS locks release automatically if a process exits.
- Price/calendar changes automatically reclassify transcript usage, while retaining accumulated resume duration.
- FX output labels cached, expired-cache and temporary-default rates. The first-run 7.2 fallback is explicitly marked `暂用值，后台刷新` and is not a live quote.
- The built-in 2026 holiday calendar matches the [State Council notice](https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html). Later years can be added in the price DB as `_holidays: {"YEAR": ["YYYY-MM-DD", ...]}` using the complete official holiday date list. The label is a schema example, not a real calendar. Until a year is supplied, weekday peak-window usage with uncertain holiday status is retained but excluded from known costs and explicitly labeled; weekends and off-peak hours remain billable normally. Annual official schedules must be added after publication.
- DeepSeek's retired Flash aliases switch to the current Flash price at **2026-09-10 12:00 Beijing time**, retaining their earlier price buckets. Sources: [current prices](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/), [release and exact price-change time](https://api-docs.deepseek.com/zh-cn/news/news260910/), [updated notice confirming Pro remains available](https://api-docs.deepseek.com/zh-cn/updates/). The price DB stores timestamped `revisions` for these aliases.

用量缓存采用进程锁和原子替换，多个会话不会互相覆盖；修改价格或年度日历会自动重算分档，并保留 resume 累计时长。
汇率会标明缓存、过期缓存或暂用值。尚未收录年份的节假日不作猜测：无法确认的高峰窗口用量保留，但不计入已知费用，并显示缺少年份；可在价格库 `_holidays` 中补充官方完整日期表。
本次外部核对覆盖 DeepSeek 当前价格、别名换价时间和 2026 年日历；其余厂商沿用仓库价格条目，未在此次逐条重新核验。这里只估算 token 费用，未包含按次计费的 Search/Fetch 等费用。


## Current-session usage correctness / 当前会话统计

- Repeated content-block transcript rows with the same API message ID count once. Later usage snapshots replace earlier snapshots across incremental refreshes. Records without a message ID use the request ID or record UUID when available.
- Long-context tier selection counts the entire prompt: uncached input + cache reads + cache writes.
- Anthropic 1-hour cache writes use their separate price (default 2x input); the remaining cache writes use the configured 5-minute price. Source: [Claude pricing and caching rules](https://platform.claude.com/docs/en/about-claude/pricing).
- Pricing and provider lookup use the stable model ID; friendly display names remain for display. Known dotted/dashed Claude IDs and dated IDs resolve to matching price entries. Unrecognized models remain unpriced.
- Non-object/malformed transcript records are skipped without restarting usage accumulation; null model fields do not crash rendering. Missing remaining-context percentage is derived from the used percentage.

同一 API 消息拆成 thinking、tool_use 等多条记录时只计一次；同一消息后续更新的用量替换先前快照，不重复相加。长上下文分档包含缓存 Token，一小时缓存写入与五分钟缓存写入分开计价。查价使用模型 ID，显示名只用于展示。


## Model names and aliases / 模型名称与别名

All models use the same resolver for price lookup, context-tier selection, colors and transcript grouping. It normalizes case, whitespace, underscores, dotted/dashed versions, provider paths, `[1M]`, `:` suffixes and `@` separators. Regional Anthropic wrappers and uniquely matching dated IDs are also supported. The normalization cases are checked against the [CC Switch model ID rules](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/4-proxy/4.4-usage.md).

Names that differ semantically rather than just in formatting belong in a canonical model's `aliases` list. For example, the current V4.1 Flash names share the single `deepseek-flash` price entry:

```json
{
  "deepseek-flash": {
    "aliases": ["deepseek-v4.1-flash", "deepseek-v4.1-flash-1017"],
    "provider": "deepseek",
    "currency": "CNY",
    "peak": {"input": 2, "cache_read": 0.04, "output": 8},
    "offpeak": {"input": 1, "cache_read": 0.02, "output": 4}
  }
}
```

The `aliases` mechanism works for every provider. Exact canonical IDs take precedence. Ambiguous aliases, unrelated tiers and unlisted models are left unpriced rather than guessed. Distinct legacy entries with time-dependent rates remain separate. CC Switch's local database was inspected as a reference; its USD price figures were not imported over this repository's CNY peak/off-peak prices.

所有模型共享同一解析器；大小写、空格、点号/连字符、常见包装格式不再需要逐个添加别名。改名等语义别名配置在对应标准模型的 `aliases` 中，归一后合并统计。别名冲突不猜测，不把 Flash、Pro、FlashX 等不同型号合并。这里的 `provider` 是价格条目所属模型厂商，不代表已确认每条历史请求的接入服务商；金额是价格库参考估算，不是中转平台账单。


## Online pricing and request logs / 在线价格与逐请求日志

The sync/model selection, message deduplication, parent-chain timing and Decimal
cost calculation adapt CC Switch's MIT-licensed implementation. The original
sources, pinned revision and adaptation map are in
[vendor/cc-switch/PROVENANCE.md](vendor/cc-switch/PROVENANCE.md), with the complete
[MIT notice](vendor/cc-switch/LICENSE). This project remains a Python statusline;
it does not require installing Tauri, Rust, React or CC Switch.

### Synchronize public prices

```sh
python ~/.claude/status-line.py --sync-prices
python ~/.claude/status-line.py --price-status
```

Prices are fetched from `https://models.dev/api.json`. Normal statusline runs
start a background updater when the last successful sync is at least six hours
old; failures retry no more often than every five minutes. Rendering never waits
for the public feed. `prices_online.json` is an atomic snapshot, with the previous
snapshot retained; `price_sync_status.json` records success, failure and counts.

`model_prices.json` holds local rules. Its `_sync` block follows CC Switch's
selection fields: `autoSyncEnabled`, `includeCommonModels`, `selectedModelKeys`
(`provider/model` keys), `excludedCommonModelKeys`, plus `intervalHours` here.
The same bounded common-family selection is used, and existing catalog models
are also refreshed when their official source is present.

- Native CNY, peak/off-peak, legacy revisions and explicit `"sync": false` entries
  remain local; a flat USD quote must not replace those tariffs.
- USD entries can refresh from the selected official providers. Existing long
  context rules are retained when the remote entry omits its tier. Unsupported
  multi-tier entries are skipped rather than flattened into an inaccurate price.
- Models.dev values are reference API prices. They do not establish a reseller's
  actual bill. Local locked prices can represent a separately confirmed tariff.
- If the feed is unavailable or invalid, the last good snapshot remains active.

### View request logs

```sh
# Import session files modified within the last day; does not alter native durations.
python ~/.claude/status-line.py --usage-import --days 1

# Starts a local desktop report. The command prints its localhost URL.
python ~/.claude/status-line.py --usage-web

# Optional fixed port, or a standalone read-only HTML snapshot.
python ~/.claude/status-line.py --usage-web --port 8765
python ~/.claude/status-line.py --usage-report --output usage-report.html
```

The statusline automatically writes deduplicated Claude Code requests to
`~/.claude/usage_ledger.sqlite3`. Each row records the request/message ID, model,
raw model name, token counts, time source, selected tariff bucket, currency,
source and a per-request unit-price snapshot. Later price syncs do not rewrite
known recorded costs. A later streaming usage snapshot updates tokens using the
saved tariff; an unpriced request can become priced once a price is supplied.
No prompts, response text, credentials or request headers are retained.

The desktop page supports time/model/tariff filters, pagination, CSV export,
expandable pricing evidence, live ledger refresh and manual public-price sync.
Its provider column says **session log**, because these files do not reliably
record the connection provider. The page displays the selected time zone;
peak/off-peak classification always uses Beijing time.

Request starts and approximate latency/first-token figures use CC Switch's
parent-chain/thinking-block logic. They are estimates, not the provider's receipt
time. When the start cannot be recovered, the log explicitly identifies the
reply timestamp as its basis. A long request spanning a billing boundary can
therefore differ from provider billing. Imported old rows capture the available
price when imported, not an invented historical price.

For development or an isolated setup, `STATUSLINE_HOME` selects the data folder.
The report listens only on `127.0.0.1`; its sync action uses a per-server token.
The online endpoint receives no session data.

中文：默认每六小时后台同步公共美元价格；人民币峰谷、版本规则和手工锁定项保留。
每条请求单独保存时间、峰谷档、单价及费用快照，已定价记录不随新价格回溯改写。
桌面表格可筛选、展开计价依据、导出 CSV。当前采集范围为 Claude Code 的会话日志，
供应商未知时显示“会话日志”，不推断接入渠道。保留的是用量元数据，不包含对话正文。
