# EU4 Chronicle（白银段）

本机读取《欧陆风云4》**非铁人**存档，对两份 `.eu4` 做 Diff，经 **史官 / 军师 / 外交官** 分析后，由 **主编** 合成一篇**可复制分享**的简体中文 Markdown 战报。

> **重要**：Cursor 云端 Agent **读不到**你台式机上的存档。本服务需安装在你本机运行。

## 它做什么

1. 解析非铁人 `.eu4`（明文或 zip 压缩的 Clausewitz 文本）
2. **默认只保留与玩家强相关的事件**（玩家国属性、参战/停战、省份得失、同盟/宿敌/附庸、直接对手）；全球无关战争（如远东大名互殴）默认丢弃
3. 将 TAG / 省份 ID / 战争名 **可读化**（存档字段优先，否则内置中文名与战争名模板，再否则「国名(TAG)」/「省份N」）
4. 主编输出一篇成稿：标题钩子 + 时间跨度 + 叙事 + 战局要点 + 外交/AE + 短结尾（**不会**把三角色原文粘三遍）
5. **AE 诚实表述**：无跳变时最多一句「未见高 AE / 包围网风险低」（勿写宿敌≠AE、宣战不结算 AE 等机制教程）；仅接近/超过 50 才警告包围网
6. **事实锚定**：同对手「断盟+收附」合并为收附；**总战分**优先 `last_warscore_quarter`（季度快照，可能与 UI 实时略差），缺则 `last_warscore_year` / 非零 `war_score` / `defender_score`；**战争目标加分**（档内 ticking / `attacker_score`）成稿统一「战争目标加分 ±N」（**不加**「约 -25～+25」注解）且叙事/要点各至多一次；`participants.value` 为贡献度、`war_score≈0` 不作 UI 总战分；禁止粮草/补给线/「下一页按战分…」等空话；有战分时禁止「未解析到 / 不作胜负判断」
7. **军科代差有据再评**：玩家参战战争从 curr 注入双方 `mil_tech`（可附 adm/dip）快照；无双方数字禁止「代差尚未拉开/同档起步」；早期差 1 级可写轻代差
8. **交战军力（数量+质量）**：同一快照附带陆军/海军/人力，以及 `discipline` / `land_morale`（顶层、嵌套，或缺绝对士气时用 `army.regiment.morale` 中位数代理，成稿写「士气≈N」）；可选 `naval_morale`（`ship.morale` 中位数→「舰船士气」）；**双方都有士气代理时必须写入战局**；无纪律数值则省略且禁止臆造；无双方同维数字禁该维对比；禁止空口「阵营体量占优」；本轮不解析军队传统/职业度
9. 提供 CLI 与本机 FastAPI（`127.0.0.1:18765`）

**不做**：账号体系、数据库、云端上传存档、铁人加密档。

## 安装

需要 Python 3.11+。推荐 [uv](https://github.com/astral-sh/uv)：

```bash
git pull
uv sync --extra llm --extra desktop --extra dev
```

- `--extra llm`：OpenAI 兼容 HTTP 客户端（`httpx`；Gemini 也走同一套）
- `--extra desktop`：桌面窗口（`pywebview`）；双击启动器用
- `--extra dev`：pytest 等开发依赖

## 配置存档目录

默认路径（Windows）：

`%USERPROFILE%\Documents\Paradox Interactive\Europa Universalis IV\save games`

```bash
export EU4_SAVE_DIR="$HOME/Documents/Paradox Interactive/Europa Universalis IV/save games"
# 或 cp .env.example .env 后编辑
```

## Mock 与真实 LLM

| | Mock | 真实 LLM（OpenAI 兼容） |
|--|------|-------------------------|
| 怎么开 | 默认，或 `--mode mock` | `--mode llm` / `EU4_CHRONICLE_MODE=llm` **且**已设 `OPENAI_API_KEY` |
| 文笔 | 按过滤后事件写史书短帖（有因果主次） | 同一套社区向 / 反空话 / 事实约束提示词，走 `/chat/completions` |
| 用途 | 无 Key 也可出可分享成稿 | 文笔更活；**不会**为缺 Key 静默回退 mock，而是报错提示 |

### 本机 `.env`

```bash
cp .env.example .env
# 编辑 .env：填 Key，并把 EU4_CHRONICLE_MODE=llm（或命令行 --mode llm）
```

**OpenAI 官方：**

```bash
# .env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
EU4_CHRONICLE_MODE=llm
```

**Gemini（固定用官方 OpenAI 兼容端点，不另装 google 库）：**

```bash
# .env
OPENAI_API_KEY=你的_Gemini_API_Key
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
OPENAI_MODEL=gemini-2.0-flash
EU4_CHRONICLE_MODE=llm
```

> 兼容说明见 [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai)。变量名仍是 `OPENAI_*`，只是 Base URL / Key / 模型换成 Gemini。

未设 `OPENAI_API_KEY` 却使用 `--mode llm` 时，会提示：请设置 Key，或改用 `--mode mock`。

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

本机真档 + **mock**：

```bash
uv run eu4-chronicle analyze \
  --prev "$EU4_SAVE_DIR/teu_prev.eu4" \
  --curr "$EU4_SAVE_DIR/teu_curr.eu4" \
  --mode mock \
  --out ~/Desktop/teu-chronicle.md
```

本机真档 + **llm**（先配好 `.env`）：

```bash
uv run eu4-chronicle analyze \
  --prev "$EU4_SAVE_DIR/teu_prev.eu4" \
  --curr "$EU4_SAVE_DIR/teu_curr.eu4" \
  --mode llm \
  --out ~/Desktop/teu-chronicle-llm.md
```

若战分可疑，先 dump 原始字段（把输出贴回即可钉死总战分/ticking）：

```bash
uv run eu4-chronicle dump-war-scores --save "$EU4_SAVE_DIR/Teutonic_Order1454_11_18.eu4"
```

若纪律/士气未进战报，先 dump 军力候选键（真档常无顶层裸字段）：

```bash
uv run eu4-chronicle dump-military --save "$EU4_SAVE_DIR/Teutonic_Order1454_11_18.eu4"
# 或显式指定对比方
uv run eu4-chronicle dump-military --save "$EU4_SAVE_DIR/Teutonic_Order1454_11_18.eu4" --tags TEU,POL
```

高级选项：

```bash
# 保留全球事件（调试/看世界）
uv run eu4-chronicle analyze --prev a.eu4 --curr b.eu4 --include-global

# 额外打印史官/军师/外交官草稿，以及 curr 档 raw_war_scores 一行
uv run eu4-chronicle analyze --prev a.eu4 --curr b.eu4 --verbose
```

列出存档 / 启动 API：

```bash
uv run eu4-chronicle list-saves
uv run eu4-chronicle serve
# 浏览器打开 http://127.0.0.1:18765/ 即可选档出战报
# POST /analyze  {"prev":"a.eu4","curr":"b.eu4","mode":"mock","include_global":false}
```

## 桌面使用（双击）

真正的桌面窗口：启动后自动拉起本机 FastAPI（`127.0.0.1:18765`），关闭窗口即停服。界面可选两份存档、选 mock/llm、生成并复制成稿。

**API Key 不在 UI 里配置**，只读项目根目录 `.env` / 环境变量（与 CLI 相同）。

### 一次性准备

```bash
cd <本仓库根目录>
cp .env.example .env
# 编辑 .env：按需填 EU4_SAVE_DIR、以及 llm 模式所需的 OPENAI_* 
uv sync --extra desktop --extra llm
```

### Windows 双击

1. 在资源管理器中打开仓库的 `scripts\` 目录
2. 双击 `EU4战报.bat`（会先 `uv sync`，再打开窗口）
3. 若要放到桌面：右键该 bat →「发送到」→「桌面快捷方式」；快捷方式属性里「起始位置」保持仓库根亦可（脚本自身会 `cd` 到仓库根）

也可在仓库根手动启动：

```bash
uv run eu4-chronicle-desktop
```

### 验收要点

- 双击后出现「EU4 战报」窗口，能列出存档
- mock / llm 均可出成稿（llm 需已配 `.env` Key）
- 关闭窗口后，本机 `18765` 端口应释放（若该端口原先已被 `eu4-chronicle serve` 占用，桌面端会复用已有服务且关窗不杀它）

## 限制

- **铁人存档**：第一期不支持
- **云端**：不能代替本机读档
- **名称覆盖**：内置中文映射非全图（已优先覆盖波罗的海/东欧常见 TAG 与战争名模板）；缺省时用存档英文名或「省份ID」兜底，战争名可回退为「进攻方征服·目标」
- **AE**：无跳变时最多一句「未见高 AE / 包围网风险低」，禁止机制科普；仅接近/超过 50 才警告包围网
- **LLM**：只走 OpenAI 兼容协议；勿把真实 Key 提交进仓库（`.gitignore` 已忽略 `.env`）

## 开发与测试

```bash
uv sync --extra llm --extra desktop --extra dev
uv run pytest
```

单测默认不打付费 API：mock 路径全绿；llm 路径用注入的 mock HTTP 客户端，或在无 Key 时 skip。

## 项目结构

```
src/eu4_chronicle/
  parser/     # .eu4 解压与关键字段
  diff/       # 两态事件 Diff
  filter.py   # 玩家中心过滤
  names/      # TAG / 省份 / 战争名可读化
  ae.py       # AE / 包围网态势评估
  agents/     # 史官 / 军师 / 外交官 / 主编（prompts + OpenAI 兼容客户端）
  pipeline.py
  cli.py
  server.py
  desktop.py   # pywebview 桌面壳（optional extra: desktop）
  static/      # 选档 / 出战报前端
scripts/
  EU4战报.bat  # Windows 双击启动
samples/
tests/
```
