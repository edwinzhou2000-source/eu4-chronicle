"""史官 / 军师 / 外交官 / 主编：真模型 + mock。"""

from __future__ import annotations

from eu4_chronicle.agents import prompts
from eu4_chronicle.agents.llm import chat_completion
from eu4_chronicle.config import Settings
from eu4_chronicle.diff import events_to_brief
from eu4_chronicle.models import AgentSection, DiffResult


async def run_historian(settings: Settings, diff: DiffResult, brief: str) -> AgentSection:
    return await _run_role(settings, "historian", "史官 · 编年叙事", prompts.HISTORIAN_SYSTEM, brief, diff)


async def run_strategist(settings: Settings, diff: DiffResult, brief: str) -> AgentSection:
    return await _run_role(settings, "strategist", "军师 · 战局研判", prompts.STRATEGIST_SYSTEM, brief, diff)


async def run_diplomat(settings: Settings, diff: DiffResult, brief: str) -> AgentSection:
    return await _run_role(settings, "diplomat", "外交官 · 外交与 AE", prompts.DIPLOMAT_SYSTEM, brief, diff)


async def run_editor(
    settings: Settings,
    diff: DiffResult,
    brief: str,
    historian: AgentSection,
    strategist: AgentSection,
    diplomat: AgentSection,
) -> AgentSection:
    mode = settings.resolved_mode()
    if mode == "mock":
        content = _mock_editor(diff, historian.content, strategist.content, diplomat.content)
        return AgentSection(role="editor", title="主编 · 合成战报", content=content, mock=True)

    text = await chat_completion(
        settings,
        system=prompts.EDITOR_SYSTEM,
        user=prompts.editor_user_prompt(brief, historian.content, strategist.content, diplomat.content),
    )
    return AgentSection(role="editor", title="主编 · 合成战报", content=text, mock=False)


async def _run_role(
    settings: Settings,
    role: str,
    title: str,
    system: str,
    brief: str,
    diff: DiffResult,
) -> AgentSection:
    mode = settings.resolved_mode()
    if mode == "mock":
        content = _mock_role(role, diff, brief)
        return AgentSection(role=role, title=title, content=content, mock=True)  # type: ignore[arg-type]

    text = await chat_completion(
        settings,
        system=system,
        user=prompts.user_prompt_for_role(role, brief),
    )
    return AgentSection(role=role, title=title, content=text, mock=False)  # type: ignore[arg-type]


def _mock_role(role: str, diff: DiffResult, brief: str) -> str:
    player = diff.player or "未知"
    span = f"{diff.prev_date or '?'} → {diff.curr_date or '?'}"
    kinds = {e.kind for e in diff.events}

    if role == "historian":
        highlights = [e.summary for e in diff.events if e.kind in {
            "province_gained", "province_lost", "war_started", "war_ended",
            "monarch_changed", "religion_changed",
        }][:6]
        bullets = "\n".join(f"- {h}" for h in highlights) or "- 本段无剧烈疆域或王朝变故，岁月在宫廷文书中静静流过。"
        return (
            f"自 {span}，以 {player} 为主视角的编年如下：\n\n"
            f"{bullets}\n\n"
            f"史官曰：江山起伏皆载于档册，共录 {len(diff.events)} 条可稽之事。"
        )

    if role == "strategist":
        wars = [e for e in diff.events if e.kind.startswith("war_") or e.kind in {"army_changed", "manpower_changed", "navy_changed"}]
        if not wars:
            return (
                f"区间 {span} 内，{player} 未现大规模交战痕迹。建议维持边境驻军与人力恢复，"
                f"并关注军事科技是否落后于邻国。"
            )
        lines = "\n".join(f"- {e.summary}" for e in wars[:8])
        return (
            f"### 战局要点\n{lines}\n\n"
            f"**研判**：优先巩固已占省份的供给线，避免多线开战；人力与陆军变化需与战争分数对照阅读。"
        )

    # diplomat
    diplo = [e for e in diff.events if e.kind in {
        "ae_changed", "alliance_formed", "alliance_broken", "rival_set",
        "rival_cleared", "opinion_changed", "subject_changed",
    }]
    if not diplo:
        return (
            f"{player} 在本区间外交结构相对平稳。仍建议定期查看宿敌与大国对你的 AE，"
            f"宣战本身不会立刻结算扩张侵略度，割地与被迫和约才会。"
        )
    lines = "\n".join(f"- {e.summary}" for e in diplo[:8])
    ae_note = "检测到 AE 变动，需评估防御同盟风险。" if "ae_changed" in kinds else "未见显著 AE 跳变。"
    return f"### 外交纪要\n{lines}\n\n**AE 提示**：{ae_note}\n\n**优先项**：修复关键断盟、用改善关系对冲高 AE 国家。"


def _mock_editor(diff: DiffResult, historian: str, strategist: str, diplomat: str) -> str:
    player = diff.player or "未知"
    span = f"{diff.prev_date or '?'} → {diff.curr_date or '?'}"
    return (
        f"# {player} 战报（{span}）\n\n"
        f"> 由史官 / 军师 / 外交官分工分析后，主编合成。事件 {len(diff.events)} 条。\n\n"
        f"## 编年叙事\n\n{historian}\n\n"
        f"## 战局研判\n\n{strategist}\n\n"
        f"## 外交与 AE\n\n{diplomat}\n\n"
        f"## 主编按语\n\n"
        f"本区间 {player} 的档册已对齐。先消化 Diff 中的得失，再决定下一场战争或媾和；"
        f"外交上盯紧 AE 与同盟破裂，军情上核对人力与战争分数是否同向。"
    )


def make_brief(diff: DiffResult) -> str:
    return events_to_brief(diff)
