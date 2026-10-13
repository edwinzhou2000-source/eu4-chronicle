# EU4 战报 · Game Report

本机读取《欧陆风云4》**非铁人**存档，对两份 `.eu4` 做 Diff，经 **史官 / 军师 / 外交官** 分析后，由 **主编** 合成一篇可复制分享的简体中文 Markdown 战报。

> 必须在本机运行。云端环境读不到你电脑上的存档。

## 功能概览

- 解析非铁人 `.eu4`（明文或 zip 压缩的 Clausewitz 文本）
- **默认只保留与玩家强相关的事件**（参战/停战、省份得失、同盟/宿敌/附庸、直接对手等）；无关全球战争默认丢弃
- TAG / 省份 / 战争名可读化（存档与游戏本地化优先，否则内置中文名）
- 成稿结构：**一事只写一处**
  - **叙事**：开疆/失地、内政数字（人力/海军/发展/稳定等）、任务一句；战争至多「详见战局」
  - **战局要点**：战争名与阵营、战分、战争目标加分、交战军力与军科/纪律/士气、研判
  - **外交与 AE**：收附/结盟/断盟、AE 与包围网（含停战国名）
  - 标题一句钩子；短结尾不回声复述战分/AE 数字
- **进行中战争**与**两档之间已打完的战争**（`previous_war`）都会进入战报；已结束战争以和约胜负为准
- AE：从他国 `active_relations` 的侵略扩张修正取值；**好感优先 `opinion_cache`（与外交 UI 一致）**；组网门槛为可入网 **≥3** 国；停战卡住的国家写准国名与国数
- LLM 成稿时叙事内政数字会按 Diff **落地校正**，避免抄提示词示例数
- 军科、编制、纪律/士气等有双方数据才对比，禁止空口编造
- 三种用法：桌面窗口、浏览器选档页、CLI

**不做**：账号体系、数据库、云端上传存档、铁人加密档、任务书战报小节、随机事件弹窗回放、前端改存档目录。

## 快速开始（推荐：桌面）

需要 **Python 3.11+** 与 [uv](https://github.com/astral-sh/uv)。

```bash
git clone https://github.com/edwinzhou2000-source/eu4-game-report.git
cd eu4-game-report
cp .env.example .env
# 编辑 .env：填 OPENAI_API_KEY（要用 LLM）；存档路径一般可自动探测
uv sync --extra desktop --extra llm
```

### Windows + WSL（仓库在 Linux）

不要从 `\\wsl$\...` 双击 bat/cmd。装一次桌面快捷方式：

```bash
bash scripts/install-desktop-shortcut.sh
```

会在 Windows 桌面写出 `EU4战报.cmd`。之后只双击它。

也可在 WSL 终端临时启动：

```bash
uv run eu4-game-report-desktop
```

无桌面窗时会用系统浏览器打开选档页；回车或 Ctrl+C 退出并停服。

### 纯 Windows（仓库在 NTFS）

```bat
uv sync --extra desktop --extra llm
uv run eu4-game-report-desktop
```

也可使用仓库内 `scripts\EU4战报.bat`（仅当仓库本身在 Windows 盘；勿从 `\\wsl$` 双击）。

## 选档页怎么用

桌面或 `uv run eu4-game-report serve` 后打开 `http://127.0.0.1:18765/`：

1. 选**同一局**、玩家 TAG 相同的两份非铁人档（较早 / 较新）
2. 模式：
   - **有 Key**：默认 **LLM**（读项目根 `.env`）
   - **无 Key**：自动切到 **Mock**（折叠在「离线 / 无 Key」里）
3. 点「生成战报」，可一键复制 Markdown

页面只**展示**当前存档目录（来自 `.env` / 自动探测），**不能**在前端改路径。API Key 也只读 `.env`，不在 UI 里配置。需要看全世界事件时用 CLI 的 `--include-global`。

## 配置

```bash
cp .env.example .env
```

### 存档目录

未设置时自动探测：

- Windows：`%USERPROFILE%\Documents\Paradox Interactive\Europa Universalis IV\save games`
- WSL：`/mnt/c/Users/<你>/Documents/.../save games`（也会试 OneDrive / `文档`）

需要手写时（WSL 下 `C:\...` 会自动转成 `/mnt/c/...`）：

```env
EU4_SAVE_DIR=C:\Users\YourName\Documents\Paradox Interactive\Europa Universalis IV\save games
```

> 不要留空的 `EU4_SAVE_DIR=`（空串会变成当前目录 `.`）。不需要自定义就删掉或注释该行。改路径后**重启** `serve` / 桌面入口。

### LLM（OpenAI 兼容）

**OpenAI：**

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
EU4_GAME_REPORT_MODE=llm
```

**Gemini（官方 OpenAI 兼容端点）：**

```env
OPENAI_API_KEY=你的_Gemini_API_Key
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
OPENAI_MODEL=gemini-2.0-flash
EU4_GAME_REPORT_MODE=llm
```

| | Mock | LLM |
|--|------|-----|
| 怎么开 | 默认环境、或 `--mode mock` / UI「离线」 | `--mode llm` / `EU4_GAME_REPORT_MODE=llm` **且**已设 Key；UI 有 Key 时默认选 LLM |
| 用途 | 无 Key 也可出可分享成稿 | 文笔更活；**缺 Key 不会静默回退 mock**，会报错提示 |

可选：`EU4_GAME_DIR` / `EU4_PARADOX_DOCS`（本地化与 Mod 名；一般可自动探测）。

## CLI

仓库样例（无需真档）：

```bash
uv run eu4-game-report analyze \
  --prev samples/byz_1444.eu4 \
  --curr samples/byz_1453.eu4 \
  --mode mock
```

本机真档：

```bash
uv run eu4-game-report analyze \
  --prev "$EU4_SAVE_DIR/prev.eu4" \
  --curr "$EU4_SAVE_DIR/curr.eu4" \
  --mode llm \
  --out ~/Desktop/game-report.md
```

常用调试：

```bash
uv run eu4-game-report list-saves
uv run eu4-game-report dump-war-scores --save path/to/save.eu4
uv run eu4-game-report dump-military --save path/to/save.eu4 --tags TEU,POL
uv run eu4-game-report analyze --prev a.eu4 --curr b.eu4 --include-global   # 保留全球事件
uv run eu4-game-report analyze --prev a.eu4 --curr b.eu4 --verbose          # 打印三角色草稿
uv run eu4-game-report serve                                                # http://127.0.0.1:18765/
```

## 选档建议

- 同一局、玩家 TAG 相同的两份非铁人档
- 跨度建议数月～数年：太短且全球噪音多时，过滤后可能偏「休整期」
- 后期档若保存时已无进行中战争，战报仍会写**本区间内打完**的战争，不会假装「本区间无战事」

## 限制

- **铁人存档**不支持
- 必须本机读档，不能用云端代替
- 内置中文名非全图；缺省用存档英文名或「省份 ID」等兜底
- AE：可入网需 AE≥50、好感&lt;0、无停战、愤慨/宿敌、非同盟附庸，且至少 3 国；无跳变且峰值不高时最多一句低风险表述
- LLM 只走 OpenAI 兼容协议；切勿把真实 Key 提交进仓库（`.gitignore` 已忽略 `.env`）

## 开发与测试

```bash
uv sync --extra llm --extra desktop --extra dev
uv run pytest
```

单测默认不打付费 API。

## 项目结构

```
src/eu4_game_report/
  parser/      # .eu4 解压与关键字段（含 relations / opinion_cache）
  diff/        # 两态 Diff（含 previous_war 等）
  filter.py    # 玩家中心过滤
  names/       # TAG / 省份 / 战争名可读化
  warscore.py  # 战分解析与归档战分可信度
  ae.py        # AE / 包围网态势
  agents/      # 史官 / 军师 / 外交官 / 主编（含叙事落地校正）
  pipeline.py
  cli.py
  server.py    # FastAPI 选档页
  desktop.py   # pywebview 桌面壳
  static/      # 前端
scripts/       # Windows 桌面快捷方式与启动器
samples/
tests/
```
