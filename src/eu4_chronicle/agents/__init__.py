"""史官 / 军师 / 外交官 / 主编：真模型 + 强化 mock 成稿。"""

from __future__ import annotations

from eu4_chronicle.agents import prompts
from eu4_chronicle.agents.llm import chat_completion
from eu4_chronicle.config import Settings
from eu4_chronicle.diff import events_to_brief
from eu4_chronicle.models import AgentSection, DiffResult
from eu4_chronicle.names import NameResolver, default_resolver


async def run_historian(
    settings: Settings,
    diff: DiffResult,
    brief: str,
    *,
    names: NameResolver | None = None,
) -> AgentSection:
    return await _run_role(
        settings, "historian", "史官 · 编年叙事", prompts.HISTORIAN_SYSTEM, brief, diff, names
    )


async def run_strategist(
    settings: Settings,
    diff: DiffResult,
    brief: str,
    *,
    names: NameResolver | None = None,
) -> AgentSection:
    return await _run_role(
        settings, "strategist", "军师 · 战局研判", prompts.STRATEGIST_SYSTEM, brief, diff, names
    )


async def run_diplomat(
    settings: Settings,
    diff: DiffResult,
    brief: str,
    *,
    names: NameResolver | None = None,
) -> AgentSection:
    return await _run_role(
        settings, "diplomat", "外交官 · 外交与 AE", prompts.DIPLOMAT_SYSTEM, brief, diff, names
    )


async def run_editor(
    settings: Settings,
    diff: DiffResult,
    brief: str,
    historian: AgentSection,
    strategist: AgentSection,
    diplomat: AgentSection,
    *,
    names: NameResolver | None = None,
) -> AgentSection:
    names = names or default_resolver()
    mode = settings.resolved_mode()
    if mode == "mock":
        content = _mock_editor(diff, names)
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
    names: NameResolver | None,
) -> AgentSection:
    names = names or default_resolver()
    mode = settings.resolved_mode()
    if mode == "mock":
        content = _mock_role(role, diff, names)
        return AgentSection(role=role, title=title, content=content, mock=True)  # type: ignore[arg-type]

    text = await chat_completion(
        settings,
        system=system,
        user=prompts.user_prompt_for_role(role, brief),
    )
    return AgentSection(role=role, title=title, content=text, mock=False)  # type: ignore[arg-type]


def _player_label(diff: DiffResult, names: NameResolver) -> str:
    return names.country(diff.player) if diff.player else "未知势力"


def _mock_role(role: str, diff: DiffResult, names: NameResolver) -> str:
    """三角色 mock：供 verbose/调试；主编成稿不粘贴这些原文。"""
    if role == "historian":
        return _mock_narrative_paragraph(diff, names)

    if role == "strategist":
        return _mock_war_section(diff, names, heading=False)

    return _mock_diplo_section(diff, names, heading=False)


def _mock_editor(diff: DiffResult, names: NameResolver) -> str:
    """社区可分享成稿：标题钩子 + 跨度 + 叙事 + 战局 + 外交 + 短结尾；不粘贴三角色原文。"""
    player = _player_label(diff, names)
    span = f"{diff.prev_date or '?'} → {diff.curr_date or '?'}"
    hook = _title_hook(diff, names)
    narrative = _mock_narrative_paragraph(diff, names)
    war = _mock_war_section(diff, names, heading=False)
    diplo = _mock_diplo_section(diff, names, heading=False)
    ending = _mock_ending(diff, names)

    return (
        f"# {hook}\n\n"
        f"**时间** {span}  ·  **主角** {player}\n\n"
        f"## 叙事\n\n{narrative}\n\n"
        f"## 战局要点\n\n{war}\n\n"
        f"## 外交与 AE\n\n{diplo}\n\n"
        f"---\n\n{ending}\n"
    )


def _title_hook(diff: DiffResult, names: NameResolver) -> str:
    player = _player_label(diff, names)
    kinds = {e.kind for e in diff.events}
    if "war_started" in kinds or "war_score_changed" in kinds:
        return f"{player}烽烟录：分数未定，刀尚未收"
    if "province_gained" in kinds:
        return f"{player}开疆记：新土入册"
    if "alliance_broken" in kinds or "ae_changed" in kinds:
        return f"{player}外交折冲：盟约松动，邻国侧目"
    if "province_lost" in kinds:
        return f"{player}失土志：版图回缩之后"
    return f"{player}国运切片：两档之间的平静与暗流"


def _mock_narrative_paragraph(diff: DiffResult, names: NameResolver) -> str:
    player = _player_label(diff, names)
    span = f"{diff.prev_date or '?'} → {diff.curr_date or '?'}"
    parts: list[str] = [f"自 {span}，{player} 的国书上落下如下记录。"]

    gained = [e for e in diff.events if e.kind == "province_gained" and e.tag == diff.player]
    lost = [e for e in diff.events if e.kind == "province_lost" and e.tag == diff.player]
    wars = [e for e in diff.events if e.kind in {"war_started", "war_ended", "war_score_changed"}]
    diplo = [
        e
        for e in diff.events
        if e.kind
        in {
            "alliance_formed",
            "alliance_broken",
            "rival_set",
            "rival_cleared",
            "subject_changed",
            "ae_changed",
        }
    ]
    internal = [
        e
        for e in diff.events
        if e.kind
        in {
            "development_changed",
            "tech_changed",
            "monarch_changed",
            "stability_changed",
            "manpower_changed",
            "army_changed",
        }
        and e.tag == diff.player
    ]

    if gained:
        provinces = []
        for e in gained:
            provinces.extend(e.detail.get("provinces") or [])
        parts.append(
            f"兵锋所至，{player} 将 {names.provinces(provinces)} 纳入版图，"
            f"边民改换旗号，税册随之改写。"
        )
    if lost:
        provinces = []
        for e in lost:
            if e.detail.get("annexed_or_missing"):
                continue
            provinces.extend(e.detail.get("provinces") or [])
        if provinces:
            parts.append(f"与此同时，{names.provinces(provinces)} 易手，朝堂不得不吞下失土的苦果。")

    if wars:
        war_names = []
        for e in wars:
            n = e.detail.get("name") or e.detail.get("war")
            if n and n not in war_names:
                war_names.append(n)
        if war_names:
            focus = "、".join(f"「{n}」" for n in war_names[:3])
            parts.append(f"战场上，{focus} 牵动军情；胜负尚在尘埃未定之际，粮草与编制已先见涨落。")
        else:
            parts.append("边境仍有刀兵声响，将帅按战争分数与补给进退。")
    elif not gained and not lost:
        parts.append("本段未见开疆或崩盘式吞并，岁月多半耗在宫廷、税吏与边境巡弋之间。")

    if diplo:
        ally_break = [e for e in diplo if e.kind == "alliance_broken"]
        ally_form = [e for e in diplo if e.kind == "alliance_formed"]
        ae = [e for e in diplo if e.kind == "ae_changed"]
        subs = [e for e in diplo if e.kind == "subject_changed" and e.tag == diff.player]
        bits = []
        if ally_break:
            others = []
            seen_pair: set[frozenset] = set()
            for e in ally_break:
                key = frozenset({e.tag, e.other_tag})
                if key in seen_pair:
                    continue
                seen_pair.add(key)
                other = e.other_tag if e.tag == diff.player else e.tag
                if other and other != diff.player:
                    others.append(names.country(other))
            if others:
                bits.append(f"与 {'、'.join(others[:2])} 的盟约撕裂")
        if ally_form:
            others = []
            seen_pair = set()
            for e in ally_form:
                key = frozenset({e.tag, e.other_tag})
                if key in seen_pair:
                    continue
                seen_pair.add(key)
                other = e.other_tag if e.tag == diff.player else e.tag
                if other and other != diff.player:
                    others.append(names.country(other))
            if others:
                bits.append(f"新结 {'、'.join(others[:2])}")
        if subs:
            bits.append("附庸结构改组")
        if ae:
            bits.append("扩张侵略度攀升，列强开始侧目")
        if bits:
            parts.append("外交席上，" + "，".join(bits) + "——这些比捷报更决定下一场战争能否独力承担。")

    if internal:
        tech = [e for e in internal if e.kind == "tech_changed"]
        stab = [e for e in internal if e.kind == "stability_changed"]
        man = [e for e in internal if e.kind == "manpower_changed"]
        if tech:
            parts.append("学问馆传来捷报：新的科技阶梯已踏出半步，军阵与行政或可因此改观。")
        if stab:
            e = stab[0]
            direction = "下滑" if (e.detail.get("to", 0) < e.detail.get("from", 0)) else "回升"
            parts.append(f"国内稳定度{direction}，敕令与叛乱风险须一并写入下一季的算计。")
        if man and not wars:
            parts.append("兵员名册有所消长，休养生息与征召令之间，君主仍需权衡。")

    if len(parts) == 1:
        parts.append(
            f"档册安静得近乎可疑：{player} 既未在远方战争中留名，也未于邻境掀起巨浪。"
            f"史官只能记下——和平亦是一种需要经营的战果。"
        )

    return "".join(parts)


def _mock_war_section(diff: DiffResult, names: NameResolver, *, heading: bool) -> str:
    player = _player_label(diff, names)
    wars = [e for e in diff.events if e.kind.startswith("war_")]
    army = [
        e
        for e in diff.events
        if e.kind in {"army_changed", "navy_changed", "manpower_changed", "development_changed"}
        and e.tag == diff.player
    ]
    lines: list[str] = []
    if not wars and not army:
        text = (
            f"{player} 本区间未卷入可稽的大战。建议维持边境驻军与人力恢复，"
            f"并核对军事科技是否落后于宿敌与邻国。"
        )
        return f"### 战局要点\n{text}" if heading else text

    for e in wars[:6]:
        lines.append(f"- {e.summary}")
    for e in army[:4]:
        lines.append(f"- {e.summary}")
    if wars:
        lines.append(
            f"- **研判**：以 {player} 为轴，先打通补给与占领线，忌在 AE 高企时另开第二战场。"
        )
    else:
        lines.append(f"- **研判**：无热战不等于无威胁；盯紧宿敌编制与己方人力曲线是否同向。")
    body = "\n".join(lines)
    return f"### 战局要点\n{body}" if heading else body


def _mock_diplo_section(diff: DiffResult, names: NameResolver, *, heading: bool) -> str:
    player = _player_label(diff, names)
    diplo = [
        e
        for e in diff.events
        if e.kind
        in {
            "ae_changed",
            "alliance_formed",
            "alliance_broken",
            "rival_set",
            "rival_cleared",
            "opinion_changed",
            "subject_changed",
        }
    ]
    if not diplo:
        text = (
            f"{player} 外交结构相对平稳。仍建议巡视宿敌与大国对你的扩张侵略度；"
            f"宣战不会立刻结算 AE，割地与苛刻和约才会。"
        )
        return f"### 外交纪要\n{text}" if heading else text

    lines = [f"- {e.summary}" for e in diplo[:8]]
    has_ae = any(e.kind == "ae_changed" for e in diplo)
    if has_ae:
        lines.append("- **AE**：扩张侵略度已动，评估防御同盟与改善关系窗口。")
    else:
        lines.append("- **AE**：未见显著跳变，但勿在下一次割地时掉以轻心。")
    lines.append("- **优先**：修复关键断盟，用改善关系对冲高 AE，附庸需算独立倾向。")
    body = "\n".join(lines)
    return f"### 外交纪要\n{body}" if heading else body


def _mock_ending(diff: DiffResult, names: NameResolver) -> str:
    player = _player_label(diff, names)
    kinds = {e.kind for e in diff.events}
    if "war_started" in kinds or "war_score_changed" in kinds:
        return f"*{player} 的刀尚未入鞘。先把这一仗的分数打实，再谈下一场国运。*"
    if "ae_changed" in kinds or "alliance_broken" in kinds:
        return f"*{player} 眼前的对手，往往不在前线，而在外交席未写完的那一行。*"
    return f"*{player} 这一页档册已合上。下一页，是休养生息，还是再度出征——君主自知。*"


def make_brief(diff: DiffResult) -> str:
    return events_to_brief(diff)
