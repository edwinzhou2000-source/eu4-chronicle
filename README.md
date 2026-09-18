# EU4 Chronicle（白银段）

本机读取《欧陆风云4》**非铁人**存档，对两份 `.eu4` 做 Diff，经 **史官 / 军师 / 外交官** 分析后，由 **主编** 合成一篇**可复制分享**的简体中文 Markdown 战报。

> **重要**：Cursor 云端 Agent **读不到**你台式机上的存档。本服务需安装在你本机运行。

## 它做什么

1. 解析非铁人 `.eu4`（明文或 zip 压缩的 Clausewitz 文本）
2. **默认只保留与玩家强相关的事件**（玩家国属性、参战/停战、省份得失、同盟/宿敌/附庸、直接对手）；全球无关战争（如远东大名互殴）默认丢弃
3. 将 TAG / 省份 ID / 战争名 **可读化**（存档字段优先，否则内置中文名与战争名模板，再否则「国名(TAG)」/「省份N」）
4. 主编输出一篇成稿：标题钩子 + 时间跨度 + 叙事 + 战局要点 + 外交/AE + 短结尾（**不会**把三角色原文粘三遍）
5. **AE 诚实表述**：无跳变或 AE 很低时写「未见高 AE / 包围网风险低」；仅接近/超过 50 才警告包围网
6. 提供 CLI 与本机 FastAPI（`127.0.0.1:18765`）

**不做**：账号体系、数据库、云端上传存档、铁人加密档。

## 安装

需要 Python 3.11+。推荐 [uv](https://github.com/astral-sh/uv)：

```bash
git pull
uv sync --extra dev
```

## 配置存档目录

默认路径（Windows）：

`%USERPROFILE%\Documents\Paradox Interactive\Europa Universalis IV\save games`

```bash
export EU4_SAVE_DIR="$HOME/Documents/Paradox Interactive/Europa Universalis IV/save games"
# 或 cp .env.example .env 后编辑
```

## Mock 与真实模型

| | Mock | 真实 LLM |
|--|------|----------|
| 条件 | 默认，或未设置 `OPENAI_API_KEY` | `EU4_CHRONICLE_MODE=llm` 且已设 Key |
| 文笔 | 按过滤后事件写史书短帖（有因果主次） | 同一模型、四套社区向系统提示 |
| 用途 | 无 Key 也可出可分享成稿 | 文笔更活 |

```bash
export OPENAI_API_KEY=sk-...
# export OPENAI_BASE_URL=https://api.openai.com/v1
# export EU4_CHRONICLE_MODEL=gpt-4o-mini
export EU4_CHRONICLE_MODE=llm
```

无 Key 时即使写了 `llm` 也会回退到 mock。

## 推荐选档

- 选**同一局**、玩家 TAG 相同的两份非铁人档
- 跨度建议数月～数年：太短（如仅一个月）且全球战争多时，过滤后事件可能偏少，成稿会偏「休整期」
- 玩家为 TEU 等时，默认不会再把日本/印度无关战争刷进战报；若要看全世界，加 `--include-global`

## 示例命令

仓库样例（无需真档）：

```bash
uv run eu4-chronicle analyze \
  --prev samples/byz_1444.eu4 \
  --curr samples/byz_1453.eu4 \
  --mode mock
```

本机真档（以 TEU 为例，路径按你的目录改）：

```bash
uv run eu4-chronicle analyze \
  --prev "$EU4_SAVE_DIR/teu_prev.eu4" \
  --curr "$EU4_SAVE_DIR/teu_curr.eu4" \
  --mode mock \
  --out ~/Desktop/teu-chronicle.md
```

高级选项：

```bash
# 保留全球事件（调试/看世界）
uv run eu4-chronicle analyze --prev a.eu4 --curr b.eu4 --include-global

# 额外打印史官/军师/外交官小节（默认只出成稿）
uv run eu4-chronicle analyze --prev a.eu4 --curr b.eu4 --verbose
```

列出存档 / 启动 API：

```bash
uv run eu4-chronicle list-saves
uv run eu4-chronicle serve
# POST /analyze  {"prev":"a.eu4","curr":"b.eu4","mode":"mock","include_global":false}
```

## 限制

- **铁人存档**：第一期不支持
- **云端**：不能代替本机读档
- **名称覆盖**：内置中文映射非全图（已优先覆盖波罗的海/东欧常见 TAG 与战争名模板）；缺省时用存档英文名或「省份ID」兜底，战争名可回退为「进攻方征服·目标」
- **AE**：mock 与 LLM 提示均遵守「包围网一般需 AE>50」；无跳变时禁止「高 AE」恐吓套话

## 开发与测试

```bash
uv sync --extra dev
uv run pytest
```

## 项目结构

```
src/eu4_chronicle/
  parser/     # .eu4 解压与关键字段
  diff/       # 两态事件 Diff
  filter.py   # 玩家中心过滤
  names/      # TAG / 省份 / 战争名可读化
  ae.py       # AE / 包围网态势评估
  agents/     # 史官 / 军师 / 外交官 / 主编
  pipeline.py
  cli.py
  server.py
samples/
tests/
```
