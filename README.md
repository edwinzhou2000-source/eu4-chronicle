# EU4 Chronicle（白银段）

本机读取《欧陆风云4》**非铁人**存档，对两份 `.eu4` 做 Diff，经 **史官 / 军师 / 外交官** 并行分析后，由 **主编** 合成一份简体中文 Markdown 战报。

> **重要**：Cursor 云端 Agent **读不到**你台式机上的存档。本服务需安装在你本机（或能访问存档目录的机器）上运行。

## 它做什么

1. 解析非铁人 `.eu4`（明文或 zip 压缩的 Clausewitz 文本）
2. 对比两档，抽取吞并、断盟、宣战、AE、兵力等事件
3. 三角色并行撰写小节 → 主编合成终稿
4. 提供 CLI 与本机 FastAPI（`127.0.0.1:18765`）

**不做**：账号体系、数据库、云端上传存档、青铜段维基主路径、铁人加密档。

## 安装

需要 Python 3.11+。推荐 [uv](https://github.com/astral-sh/uv)：

```bash
uv sync --extra dev
```

## 配置存档目录

默认路径（Windows）：

`%USERPROFILE%\Documents\Paradox Interactive\Europa Universalis IV\save games`

用环境变量覆盖：

```bash
# Linux / macOS 示例
export EU4_SAVE_DIR="$HOME/Documents/Paradox Interactive/Europa Universalis IV/save games"

# 或复制 .env.example 为 .env 后编辑
cp .env.example .env
```

## Mock 与真实模型

| | Mock | 真实 LLM |
|--|------|----------|
| 条件 | 默认，或未设置 `OPENAI_API_KEY` | `EU4_CHRONICLE_MODE=llm` 且已设 Key |
| 用途 | 无 Key 跑通完整结构 | OpenAI 兼容接口推理 |

```bash
export OPENAI_API_KEY=sk-...
# 可选中转
# export OPENAI_BASE_URL=https://api.openai.com/v1
# export EU4_CHRONICLE_MODEL=gpt-4o-mini
export EU4_CHRONICLE_MODE=llm
```

无 Key 时即使写了 `llm` 也会回退到 mock，保证演示不中断。

## 示例命令

对仓库内合成样例（无需真档）：

```bash
uv run eu4-chronicle analyze \
  --prev samples/byz_1444.eu4 \
  --curr samples/byz_1453.eu4 \
  --mode mock
```

写出 Markdown 文件：

```bash
uv run eu4-chronicle analyze \
  --prev samples/byz_1444.eu4 \
  --curr samples/byz_1453.eu4 \
  --out /tmp/byz-report.md
```

列出配置目录下的存档：

```bash
export EU4_SAVE_DIR=/path/to/save\ games
uv run eu4-chronicle list-saves
```

启动本机 API：

```bash
uv run eu4-chronicle serve
# 健康检查: http://127.0.0.1:18765/health
# 列表:     GET  /saves
# 分析:     POST /analyze  {"prev":"a.eu4","curr":"b.eu4","mode":"mock"}
```

## 限制

- **铁人存档**：加密/二进制，第一期明确不支持；请使用非铁人存档或手动导出的明文/压缩文本档。
- **云端**：不能代替本机读档；请在台式机 pull 本仓库后本地运行。
- **字段覆盖**：解析聚焦玩家相关的发展度、科技、君主三维、战争、同盟、关系与 AE；不是完整官方存档规范实现。

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
  agents/     # 史官 / 军师 / 外交官 / 主编
  pipeline.py
  config.py
  cli.py
  server.py
samples/      # 最小合成样例
tests/
```
