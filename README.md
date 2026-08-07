# Claude Code Status Line

自定义的 [Claude Code](https://claude.com/claude-code) 终端状态栏：模型、Token、上下文进度条、会话花费（$ + ¥）、消息数、目录、git 分支、时长、时钟。

## 效果

```
[deepseek-v4-flash@deepseek]  ⬇ 1.0M  ⬆ 500.0K  💾 读2.0M  ▮ 1.0M [██████░░░░░░░░] 45%
💰 deepseek-v4-flash@deepseek $0.286 (¥1.93)  💬 42  📁 my_project  🌿 main  ⏱ 0h14m  🕐 2026-08-07 15:46:54 周五
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

- **模型 + 供应商**：`[model@provider]`
- **Token**：⬇ 累计输入 / ⬆ 累计输出 / 💾 缓存读/写
- **上下文进度条**：`[██████░░░░░░░░] 45%`，≤70% 绿、71–90% 黄、>90% 红 + `⚠ 剩X%`
- **花费**：按 token × 单价本地估算，`$X (¥Y)` 双币显示；库里没有的模型退回 Claude Code 的 `total_cost_usd`
- **消息数 / 目录 / git 分支 / 会话时长 / 时钟**（年-月-日 时间 星期）

## 查单价（价格库）

```bash
python ~/.claude/status-line.py --prices
```

输出所有模型的 **$ 和 ¥** 单价（实时汇率，缓存 1 小时）：

```
汇率：1 USD = 6.7634 CNY（实时，缓存1小时）

模型                  供应商              输入$       输出$      缓存读$       输入¥       输出¥
------------------------------------------------------------------------------------
deepseek-v4-flash   deepseek        0.14      0.28    0.0028   0.94688   1.89376
kimi-k3             moonshot           3        15       0.3  20.29028 101.45139
gpt-5               openai         1.25        10     0.125   8.45428  67.63426
...
```

## 价格

- 价格库：`model_prices.json`（每 1M token 美元单价），直接编辑即可生效。
- 已收录：deepseek / kimi(msghot) / minimax / glm(zhipu) / gpt(openai) / grok(xai) / claude(anthropic)。
- 价格源为 2026 年公开 API 定价，随渠道/活动变化，以官方为准——**改价格请编辑 `model_prices.json`**。
- 汇率：实时获取（`open.er-api.com`），失败回退 7.2，缓存 1 小时（`~/.claude/usd_cny.json`）。

## License

MIT
