"""史官 / 军师 / 外交官 / 主编：真模型 + 强化 mock 成稿。

成稿硬性：只陈述 Diff 有数据支撑的事实；禁止补给线/粮草/尘埃未定等空话。
"""

from __future__ import annotations

from eu4_chronicle.ae import AeAssessment, ae_guidance_lines, assess_player_ae
from eu4_chronicle.agents import prompts
from eu4_chronicle.agents.llm import chat_completion
from eu4_chronicle.config import Settings
from eu4_chronicle.diff import events_to_brief
from eu4_chronicle.filter import vassalized_tags
from eu4_chronicle.models import AgentSection, DiffResult
from eu4_chronicle.names import NameResolver, default_resolver
from eu4_chronicle.warscore import (
    WarAssessment,
    assess_player_wars,
    format_ticking_bonus,
    tier_phrase,
    war_guidance_lines,
)


async def run_historian(
    settings: Settings,
    diff: DiffResult,
    brief: str,
    *,
    names: NameResolver | None = None,
    ae: AeAssessment | None = None,
) -> AgentSection:
    return await _run_role(
        settings,
        "historian",
        "史官 · 编年叙事",
        prompts.HISTORIAN_SYSTEM,
        brief,
        diff,
        names,
        ae,
    )


async def run_strategist(
    settings: Settings,
    diff: DiffResult,
    brief: str,
    *,
    names: NameResolver | None = None,
    ae: AeAssessment | None = None,
) -> AgentSection:
    return await _run_role(
        settings,
        "strategist",
        "军师 · 战局研判",
        prompts.STRATEGIST_SYSTEM,
        brief,
        diff,
        names,
        ae,
    )


async def run_diplomat(
    settings: Settings,
    diff: DiffResult,
    brief: str,
    *,
    names: NameResolver | None = None,
    ae: AeAssessment | None = None,
) -> AgentSection:
    return await _run_role(
        settings,
        "diplomat",
        "外交官 · 外交与 AE",
        prompts.DIPLOMAT_SYSTEM,
        brief,
        diff,
        names,
        ae,
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
    ae: AeAssessment | None = None,
) -> AgentSection:
    names = names or default_resolver()
    ae = ae or assess_player_ae(diff, country_label=names.country)
    mode = settings.resolved_mode()
    if mode == "mock":
        content = _mock_editor(diff, names, ae)
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
    ae: AeAssessment | None,
) -> AgentSection:
    names = names or default_resolver()
    ae = ae or assess_player_ae(diff, country_label=names.country)
    mode = settings.resolved_mode()
    if mode == "mock":
        content = _mock_role(role, diff, names, ae)
        return AgentSection(role=role, title=title, content=content, mock=True)  # type: ignore[arg-type]

    text = await chat_completion(
        settings,
        system=system,
        user=prompts.user_prompt_for_role(role, brief),
    )
    return AgentSection(role=role, title=title, content=text, mock=False)  # type: ignore[arg-type]


def _player_label(diff: DiffResult, names: NameResolver) -> str:
    return names.country(diff.player) if diff.player else "未知势力"


def _wars(diff: DiffResult) -> WarAssessment:
    return assess_player_wars(diff)


def _mock_role(role: str, diff: DiffResult, names: NameResolver, ae: AeAssessment) -> str:
    """三角色 mock：供 verbose/调试；主编成稿不粘贴这些原文。"""
    if role == "historian":
        return _mock_narrative_paragraph(diff, names, ae)

    if role == "strategist":
        return _mock_war_section(diff, names, ae, heading=False)

    return _mock_diplo_section(diff, names, ae, heading=False)


def _mock_editor(diff: DiffResult, names: NameResolver, ae: AeAssessment) -> str:
    """社区可分享成稿：标题钩子 + 跨度 + 叙事 + 战局 + 外交 + 短结尾。"""
    player = _player_label(diff, names)
    span = f"{diff.prev_date or '?'} → {diff.curr_date or '?'}"
    hook = _title_hook(diff, names, ae)
    narrative = _mock_narrative_paragraph(diff, names, ae)
    war = _mock_war_section(diff, names, ae, heading=False)
    diplo = _mock_diplo_section(diff, names, ae, heading=False)
    ending = _mock_ending(diff, names, ae)

    return (
        f"# {hook}\n\n"
        f"**时间** {span}  ·  **主角** {player}\n\n"
        f"## 叙事\n\n{narrative}\n\n"
        f"## 战局要点\n\n{war}\n\n"
        f"## 外交与 AE\n\n{diplo}\n\n"
        f"---\n\n{ending}\n"
    )


def _title_hook(diff: DiffResult, names: NameResolver, ae: AeAssessment) -> str:
    player = _player_label(diff, names)
    wars = _wars(diff)
    primary = wars.primary
    vassals = vassalized_tags(diff.events, diff.player) if diff.player else set()
    kinds = {e.kind for e in diff.events}

    if primary is not None:
        wlabel = primary.war_name_zh or names.war(
            primary.war_name,
            attackers=primary.attackers,
            defenders=primary.defenders,
        )
        if primary.tier == "decisive":
            return f"{player}战报：{wlabel}，优势在握（战分 {primary.player_score:+.0f}）"
        if primary.tier == "advantage":
            return f"{player}战报：{wlabel}，战局偏我（战分 {primary.player_score:+.0f}）"
        if primary.tier == "contested":
            return f"{player}战报：{wlabel}，双方胶着（战分 {primary.player_score:+.0f}）"
        if primary.tier == "disadvantage":
            return f"{player}战报：{wlabel}，战分落后（战分 {primary.player_score:+.0f}）"
        if primary.tier == "collapse":
            return f"{player}战报：{wlabel}，局势危急（战分 {primary.player_score:+.0f}）"
        return f"{player}战报：{wlabel}"

    if vassals:
        labels = "、".join(names.country(t) for t in sorted(vassals)[:2])
        return f"{player}外交录：收附 {labels}"
    if "province_gained" in kinds:
        return f"{player}开疆记：新土入册"
    if ae.warn_coalition:
        return f"{player}外交折冲：AE 逼近红线"
    if "alliance_broken" in kinds:
        return f"{player}外交折冲：同盟调整"
    if "province_lost" in kinds:
        return f"{player}失土志：版图回缩"
    return f"{player}国运切片：{diff.prev_date or '?'} → {diff.curr_date or '?'}"


def _war_display_name(e, names: NameResolver) -> str:
    detail = e.detail or {}
    if detail.get("name_zh"):
        return str(detail["name_zh"])
    return names.war(
        detail.get("name") or detail.get("war"),
        attackers=detail.get("attackers"),
        defenders=detail.get("defenders"),
    )


def _fmt_num_change(e, *, key_from: str = "from", key_to: str = "to", digits: int = 1) -> str:
    fr = e.detail.get(key_from, 0)
    to = e.detail.get(key_to, 0)
    try:
        return f"{float(fr):.{digits}f}→{float(to):.{digits}f}"
    except (TypeError, ValueError):
        return f"{fr}→{to}"


def _mock_narrative_paragraph(diff: DiffResult, names: NameResolver, ae: AeAssessment) -> str:
    """只拼 Diff 事实句：人力/海军/战争/同盟附庸/科技等。"""
    player = _player_label(diff, names)
    span = f"{diff.prev_date or '?'} → {diff.curr_date or '?'}"
    parts: list[str] = [f"{span}，{player}："]
    facts: list[str] = []

    gained = [e for e in diff.events if e.kind == "province_gained" and e.tag == diff.player]
    lost = [e for e in diff.events if e.kind == "province_lost" and e.tag == diff.player]
    if gained:
        provinces: list = []
        for e in gained:
            provinces.extend(e.detail.get("provinces") or [])
        if provinces:
            facts.append(f"取得 {names.provinces(provinces)}")
    if lost:
        provinces = []
        for e in lost:
            if e.detail.get("annexed_or_missing"):
                continue
            provinces.extend(e.detail.get("provinces") or [])
        if provinces:
            facts.append(f"失去 {names.provinces(provinces)}")

    wars = _wars(diff)
    for s in wars.standings:
        wlabel = s.war_name_zh or names.war(
            s.war_name, attackers=s.attackers, defenders=s.defenders
        )
        if s.score_known:
            # 分数只写一次：总战分在前，tier 不再括号重复战分
            facts.append(
                f"战争「{wlabel}」玩家总战分 {s.player_score:+.0f}，"
                f"{tier_phrase(s.tier)}"
            )
        else:
            facts.append(f"战争「{wlabel}」仍在进行（档内未解析到玩家战分）")
        # ticking / 目标 / 战役细节只经由 detail_bits，避免与上文 ticking 重复
        detail_bits = _war_standing_detail_bits(s, names)
        if detail_bits:
            facts.append("；".join(detail_bits))

    # 外交：收附优先；断盟仅当未同时收附
    vassals = vassalized_tags(diff.events, diff.player) if diff.player else set()
    if vassals:
        facts.append("收附 " + "、".join(names.country(t) for t in sorted(vassals)))
    ally_form: list[str] = []
    ally_break: list[str] = []
    seen_form: set[frozenset] = set()
    seen_break: set[frozenset] = set()
    for e in diff.events:
        if e.kind == "alliance_formed" and e.tag and e.other_tag:
            key = frozenset({e.tag, e.other_tag})
            if key in seen_form:
                continue
            seen_form.add(key)
            other = e.other_tag if e.tag == diff.player else e.tag
            if other and other != diff.player and other not in vassals:
                ally_form.append(names.country(other))
        if e.kind == "alliance_broken" and e.tag and e.other_tag:
            key = frozenset({e.tag, e.other_tag})
            if key in seen_break:
                continue
            seen_break.add(key)
            other = e.other_tag if e.tag == diff.player else e.tag
            if other and other != diff.player and other not in vassals:
                ally_break.append(names.country(other))
    if ally_form:
        facts.append("新结盟 " + "、".join(ally_form[:3]))
    if ally_break:
        facts.append("同盟破裂：" + "、".join(ally_break[:3]))

    for e in diff.events:
        if e.tag != diff.player:
            continue
        if e.kind == "manpower_changed":
            facts.append(
                f"人力 {_fmt_num_change(e)}（上限 "
                f"{_fmt_num_change(e, key_from='max_from', key_to='max_to')}）"
            )
        elif e.kind == "navy_changed":
            facts.append(f"海军约 {_fmt_num_change(e, digits=0)}")
        elif e.kind == "army_changed":
            facts.append(f"陆军约 {_fmt_num_change(e, digits=0)}")
        elif e.kind == "tech_changed":
            labels = {"adm_tech": "行政科技", "dip_tech": "外交科技", "mil_tech": "军事科技"}
            tech = labels.get(str(e.detail.get("tech")), str(e.detail.get("tech")))
            facts.append(f"{tech} {e.detail.get('from')}→{e.detail.get('to')}")
        elif e.kind == "stability_changed":
            facts.append(f"稳定度 {e.detail.get('from')}→{e.detail.get('to')}")
        elif e.kind == "development_changed":
            facts.append(f"发展度 {_fmt_num_change(e, digits=0)}")

    # 战争军科对比（有双方数字才写；禁止无据臆测代差）
    for e in diff.events:
        if e.kind != "war_tech_compare":
            continue
        bit = _war_tech_compare_fact(e, names)
        if bit:
            facts.append(bit)

    if ae.has_change and ae.facts:
        facts.append("AE：" + "；".join(ae.facts[:2]))

    if not facts:
        parts.append("本区间未见可稽的疆域、战争、外交或编制跳变。")
    else:
        parts.append("；".join(facts) + "。")
    return "".join(parts)


def _war_standing_detail_bits(s, names: NameResolver) -> list[str]:
    """战争目标 / 占领 / 战役等档内细节（有则写）。ticking 至多一句。"""
    bits: list[str] = []
    if s.ticking_score is not None:
        bits.append(format_ticking_bonus(s.ticking_score))
    if s.war_goal_type or s.casus_belli:
        goal = names.war_goal(s.war_goal_type) if s.war_goal_type else "未知目标"
        cb = f"（CB {names.casus_belli(s.casus_belli)}）" if s.casus_belli else ""
        prov = ""
        if s.war_goal_province is not None:
            prov = f"，目标省 {names.province(s.war_goal_province)}"
        bits.append(f"战争目标 {goal}{cb}{prov}")
    if s.occupied_provinces is not None:
        bits.append(f"交战占领省份约 {s.occupied_provinces} 处")
    for b in (s.major_battles or [])[:2]:
        bname = b.get("name") or "某地"
        won = b.get("attacker_won")
        if won is True:
            outcome = "攻方胜"
        elif won is False:
            outcome = "守方胜"
        else:
            outcome = "胜负未载"
        losses_a = b.get("attacker_losses")
        losses_d = b.get("defender_losses")
        loss_bit = ""
        if losses_a is not None or losses_d is not None:
            loss_bit = f"（损 {losses_a or 0:.0f}/{losses_d or 0:.0f}）"
        bits.append(f"战役「{bname}」{outcome}{loss_bit}")
    return bits


def _war_tech_compare_fact(e, names: NameResolver) -> str | None:
    """有双方可比数字才成句；军科早期差 1 点明轻代差；纪律/士气仅双方都有才写。"""
    detail = e.detail or {}
    player_l = detail.get("player_label") or names.country(detail.get("player") or e.tag)
    foe_l = detail.get("foe_label") or names.country(detail.get("foe") or e.other_tag)
    player_force = detail.get("player_force") or {}
    foe_force = detail.get("foe_force") or {}

    bits: list[str] = []
    # 军科
    if detail.get("has_both_mil", True):
        player_mil = detail.get("player_mil")
        foe_mil = detail.get("foe_mil")
        if player_mil is not None and foe_mil is not None:
            try:
                gap = int(detail.get("mil_gap", int(player_mil) - int(foe_mil)))
            except (TypeError, ValueError):
                gap = int(player_mil) - int(foe_mil)
            base = f"军事科技 {player_l} {player_mil} vs {foe_l} {foe_mil}"
            early = bool(detail.get("early_game"))
            if early and abs(gap) == 1:
                lead = player_l if gap > 0 else foe_l
                bits.append(f"{base}（{lead} 军科领先一级，属前期轻代差）")
            elif gap == 0:
                bits.append(f"{base}（同档）")
            elif gap > 0:
                bits.append(f"{base}（玩家领先 {gap} 级）")
            else:
                bits.append(f"{base}（对手领先 {-gap} 级）")

    # 兵力 / 人力（双方同维才写）
    if detail.get("has_both_army") and player_force and foe_force:
        pa = float(player_force.get("army_size", 0))
        fa = float(foe_force.get("army_size", 0))
        bits.append(f"陆军 {player_l} {pa:.0f} vs {foe_l} {fa:.0f}")
    if detail.get("has_both_manpower") and player_force and foe_force:
        pm = float(player_force.get("manpower", 0))
        pmx = float(player_force.get("max_manpower", 0))
        fm = float(foe_force.get("manpower", 0))
        fmx = float(foe_force.get("max_manpower", 0))
        bits.append(f"人力 {player_l} {pm:.1f}/{pmx:.1f} vs {foe_l} {fm:.1f}/{fmx:.1f}")
    if detail.get("has_both_discipline") and player_force and foe_force:
        bits.append(
            f"纪律 {player_l} {_fmt_q(player_force['discipline'])} vs "
            f"{foe_l} {_fmt_q(foe_force['discipline'])}"
        )
    if detail.get("has_both_land_morale") and player_force and foe_force:
        # 团级 morale 中位数代理 →「士气≈N」（陆战单位士气快照）
        p_approx = "≈" if player_force.get("land_morale_proxy") else ""
        f_approx = "≈" if foe_force.get("land_morale_proxy") else ""
        # 任一侧为代理则统一用 ≈，标明来自部队当前士气快照
        if p_approx or f_approx:
            bits.append(
                f"士气≈ {player_l} {_fmt_q(player_force['land_morale'])} vs "
                f"{foe_l} {_fmt_q(foe_force['land_morale'])}"
            )
        else:
            bits.append(
                f"士气 {player_l} {_fmt_q(player_force['land_morale'])} vs "
                f"{foe_l} {_fmt_q(foe_force['land_morale'])}"
            )
    if detail.get("has_both_naval_morale") and player_force and foe_force:
        bits.append(
            f"舰船士气 {player_l} {_fmt_q(player_force['naval_morale'])} vs "
            f"{foe_l} {_fmt_q(foe_force['naval_morale'])}"
        )

    if not bits:
        return None
    return "；".join(bits)


def _fmt_q(v) -> str:
    f = float(v)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:.3f}".rstrip("0").rstrip(".")


def _mock_war_section(
    diff: DiffResult, names: NameResolver, ae: AeAssessment, *, heading: bool
) -> str:
    player = _player_label(diff, names)
    wars = _wars(diff)
    army = [
        e
        for e in diff.events
        if e.kind in {"army_changed", "navy_changed", "manpower_changed", "development_changed"}
        and e.tag == diff.player
    ]
    tech_compares = [e for e in diff.events if e.kind == "war_tech_compare"]
    lines: list[str] = []
    if not wars.standings and not army and not tech_compares:
        text = f"{player} 本区间未卷入可稽的大战，也无编制/人力跳变记录。"
        return f"### 战局要点\n{text}" if heading else text

    for s in wars.standings:
        wlabel = s.war_name_zh or names.war(
            s.war_name, attackers=s.attackers, defenders=s.defenders
        )
        att = "、".join(names.country(x) for x in s.attackers) or "？"
        defe = "、".join(names.country(x) for x in s.defenders) or "？"
        if s.score_known:
            lines.append(
                f"- 战争「{wlabel}」：{att} vs {defe}；"
                f"玩家总战分 {s.player_score:+.0f}——"
                f"{tier_phrase(s.tier)}"
            )
        else:
            lines.append(f"- 战争「{wlabel}」：{att} vs {defe}；档内未解析到玩家战分")
        for bit in _war_standing_detail_bits(s, names):
            lines.append(f"  - {bit}")
        # 同战争的军科对比挂在条目下
        for e in tech_compares:
            wname = (e.detail or {}).get("name") or (e.detail or {}).get("war")
            if wname and wname != s.war_name:
                continue
            fact = _war_tech_compare_fact(e, names)
            if fact:
                lines.append(f"  - {fact}")
    # 无 standings 时仍列出军科对比
    if not wars.standings:
        for e in tech_compares:
            fact = _war_tech_compare_fact(e, names)
            if fact:
                lines.append(f"- {fact}")
    for e in army[:6]:
        lines.append(f"- {e.summary}")

    if wars.standings:
        primary = wars.primary
        assert primary is not None
        if primary.tier == "decisive":
            judge = f"战分 {primary.player_score:+.0f}，优势在握，可推进和约或巩固占领。"
        elif primary.tier == "advantage":
            judge = f"战分 {primary.player_score:+.0f}，战局偏我，继续扩大占领优势。"
        elif primary.tier == "contested":
            judge = f"战分 {primary.player_score:+.0f}，双方胶着，胜负未定。"
        elif primary.tier == "disadvantage":
            judge = f"战分 {primary.player_score:+.0f}，战分落后，宜收缩战线或求和。"
        elif primary.tier == "collapse":
            judge = f"战分 {primary.player_score:+.0f}，局势危急。"
        else:
            judge = "档内未解析到玩家战分，仅列参战方与编制事实，不作胜负判断。"
        if ae.warn_coalition:
            judge += f" 当前 AE 偏高（约 {ae.max_to:.0f}），忌另开第二战场。"
        # 有军科领先时附一句
        for e in tech_compares:
            gap = (e.detail or {}).get("mil_gap")
            early = bool((e.detail or {}).get("early_game"))
            if gap is None:
                continue
            try:
                g = int(gap)
            except (TypeError, ValueError):
                continue
            if early and g == 1:
                judge += " 军科领先一级（前期轻代差），利于以弱胜强。"
                break
            if early and g == -1:
                judge += " 军科落后一级（前期轻代差），需慎战。"
                break
        lines.append(f"- **研判**：{judge}")
    body = "\n".join(lines)
    return f"### 战局要点\n{body}" if heading else body


def _mock_diplo_section(
    diff: DiffResult, names: NameResolver, ae: AeAssessment, *, heading: bool
) -> str:
    player = _player_label(diff, names)
    vassals = vassalized_tags(diff.events, diff.player) if diff.player else set()
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
    # 用户成稿：不含调试旁注
    guidance = ae_guidance_lines(ae, player_label=player, for_user=True)
    if not diplo:
        # 无外交 Diff：一句平稳 + AE 平静句（勿写机制科普）
        text = f"{player} 外交结构相对平稳。" + "".join(guidance)
        return f"### 外交纪要\n{text}" if heading else text

    lines: list[str] = []
    # 收附优先展示
    for e in diplo:
        if e.kind == "subject_changed" and e.tag == diff.player:
            gained = e.detail.get("gained") or []
            if gained:
                lines.append(
                    f"- 收附 {'、'.join(names.country(x) for x in gained)}"
                    + (
                        f"；失去附庸 {'、'.join(names.country(x) for x in (e.detail.get('lost') or []))}"
                        if e.detail.get("lost")
                        else ""
                    )
                )
            else:
                lines.append(f"- {e.summary}")
        elif e.kind == "alliance_broken":
            other = e.other_tag if e.tag == diff.player else e.tag
            if other in vassals:
                continue
            lines.append(f"- {e.summary}")
        elif e.kind == "alliance_formed":
            lines.append(f"- {e.summary}")
        elif e.kind not in {"subject_changed"}:
            lines.append(f"- {e.summary}")

    lines = lines[:10]
    lines.append("- **AE**：" + guidance[0])
    for extra in guidance[1:]:
        lines.append(f"- {extra}")
    if vassals:
        lines.append(
            "- **优先**：巩固对新附庸的控制与外交容量；"
            + ("高 AE 窗口暂缓再扩张。" if ae.warn_coalition else "维护新同盟与宿敌平衡。")
        )
    elif ae.warn_coalition:
        lines.append("- **优先**：修复关键断盟，改善关系以缓冲联军。")
    else:
        lines.append("- **优先**：维护关键同盟与宿敌平衡。")
    body = "\n".join(lines)
    return f"### 外交纪要\n{body}" if heading else body


def _mock_ending(diff: DiffResult, names: NameResolver, ae: AeAssessment) -> str:
    """短收束：只点事实，禁止「下一页…」「按…事实推进」类套话。"""
    player = _player_label(diff, names)
    wars = _wars(diff)
    vassals = vassalized_tags(diff.events, diff.player) if diff.player else set()
    primary = wars.primary
    if primary is not None and primary.score_known:
        return f"*{player}：{tier_phrase(primary.tier, score=primary.player_score)}。*"
    if primary is not None:
        return f"*{player} 仍有战争进行中；档内战分未解析到，不作胜负口号。*"
    if vassals:
        labels = "、".join(names.country(t) for t in sorted(vassals)[:2])
        return f"*{player} 已收附 {labels}。*"
    if ae.warn_coalition:
        return f"*{player} 眼前的约束主要在 AE（约 {ae.max_to:.0f}）。*"
    return f"*{player} 本页档册事实如上。*"


def make_brief(
    diff: DiffResult,
    *,
    names: NameResolver | None = None,
    ae: AeAssessment | None = None,
) -> str:
    names = names or default_resolver()
    ae = ae or assess_player_ae(diff, country_label=names.country)
    wars = assess_player_wars(diff)
    base = events_to_brief(diff)
    player = names.country(diff.player) if diff.player else "玩家"
    guide = ae_guidance_lines(ae, player_label=player, for_user=False)
    war_lines = war_guidance_lines(wars, country_label=names.country)
    tech_lines = _tech_guidance_lines(diff)
    force_lines = _force_guidance_lines(diff)
    block = [
        "",
        "## AE 态势（供外交官/主编遵守，禁止编造恐吓；调试旁注勿写入成稿正文）",
        f"level={ae.level} max_to={ae.max_to:.0f} has_change={ae.has_change} warn_coalition={ae.warn_coalition}",
        *[f"- {g}" for g in guide],
        "- 硬性：AE=0 或无跳变时最多一句「当前未见高 AE / 包围网风险低」，禁止机制科普；"
        "仅 level=approaching|high 才可提包围网门槛。",
        "",
        "## 战争分数态势（供军师/史官/主编遵守）",
        *[f"- {g}" for g in war_lines],
        "",
        "## 军事科技 / 代差（供军师/史官/主编遵守）",
        *tech_lines,
        "",
        "## 交战军力（数量 + 质量；供军师/史官/主编遵守）",
        *force_lines,
        "",
        "## 成稿禁词（空话）",
        "- 禁止：粮草、补给线、打通补给、分数打实、胜负尚在尘埃未定、刀尚未收/入鞘。",
        "- 禁止：「下一页…」「按…事实推进」等收束套话。",
        "- 战争目标加分叙事与要点各至多一句（统一「战争目标加分 ±N」）；"
        "禁止附加任何「约±25」类范围括号注解；正面解释目标达成程度，勿写元注释免责声明。",
        "- 只陈述 Diff 有数据的事实：人力/海军/陆军/战争参战方与战分/同盟附庸/科技/纪律/士气等。",
        "- 同对手 alliance_break + 收附 → 只写收附，禁止渲染断盟悲剧。",
        "- 禁止提及军队传统/海军传统/职业度（本轮未注入）。",
    ]
    return base + "\n".join(block)


def _tech_guidance_lines(diff: DiffResult) -> list[str]:
    """brief 军科硬规则：无双方数字禁对比；早期差 1 可评轻代差。"""
    from eu4_chronicle.agents.prompts import TECH_COMPARE_FORBIDDEN_WITHOUT_BOTH

    compares = [e for e in diff.events if e.kind == "war_tech_compare"]
    lines: list[str] = []
    mil_compares = [e for e in compares if (e.detail or {}).get("has_both_mil")]
    if not mil_compares:
        lines.append(
            "- 本 Diff **无双方军科对比数字**：禁止写「"
            + " / ".join(TECH_COMPARE_FORBIDDEN_WITHOUT_BOTH[:4])
            + "」等；仅可写玩家 tech_changed（若有）。"
        )
        return lines

    for e in mil_compares:
        detail = e.detail or {}
        lines.append(f"- 事实：{e.summary}")
        gap = detail.get("mil_gap")
        early = bool(detail.get("early_game"))
        if gap is None:
            continue
        try:
            g = int(gap)
        except (TypeError, ValueError):
            continue
        if g == 0:
            lines.append("- 军科差 0：可写同档；禁止臆造代差。")
        elif early and abs(g) == 1:
            side = "玩家" if g > 0 else "对手"
            lines.append(
                f"- 早期且军科差 1：可写「{side}军科领先一级，属前期轻代差」；"
                "禁止写代差尚未拉开 / 同档起步。"
            )
        else:
            lines.append(f"- 军科差 {g:+d}：可据实点评，勿夸大。")
    lines.append(
        "- 硬性：没有双方 mil 数字时，禁止一切代差或同档对比句。"
    )
    return lines


def _force_guidance_lines(diff: DiffResult) -> list[str]:
    """brief 交战军力：无双方同维数字禁该维对比。"""
    from eu4_chronicle.agents.prompts import FORCE_COMPARE_FORBIDDEN_WITHOUT_BOTH

    compares = [e for e in diff.events if e.kind == "war_tech_compare"]
    lines: list[str] = []
    if not compares:
        lines.append(
            "- 本 Diff **无交战军力快照**：禁止写「"
            + " / ".join(FORCE_COMPARE_FORBIDDEN_WITHOUT_BOTH[:4])
            + "」等空口体量句；勿臆造对手兵力/纪律/士气。"
        )
        lines.append("- 硬性：无双方同维数字则禁止该维对比；勿提传统/职业度。")
        return lines

    for e in compares:
        detail = e.detail or {}
        lines.append(f"- 事实：{e.summary}")
        dims = []
        if detail.get("has_both_army"):
            dims.append("陆军")
        if detail.get("has_both_manpower"):
            dims.append("人力")
        if detail.get("has_both_discipline"):
            dims.append("纪律")
        if detail.get("has_both_land_morale"):
            dims.append("士气")
        if detail.get("has_both_naval_morale"):
            dims.append("舰船士气")
        if detail.get("has_both_mil"):
            dims.append("军科")
        if dims:
            lines.append(f"- 可对比维：{'、'.join(dims)}（仅这些；缺维勿评）。")
        must_dims = []
        if detail.get("has_both_discipline"):
            must_dims.append("纪律")
        if detail.get("has_both_land_morale"):
            must_dims.append("士气（含士气≈代理）")
        if detail.get("has_both_naval_morale"):
            must_dims.append("舰船士气")
        if must_dims:
            lines.append(
                f"- **必须写入战局/叙事（不得省略）**：{'、'.join(must_dims)}。"
            )
        missing = []
        if not detail.get("has_both_army"):
            missing.append("陆军")
        if not detail.get("has_both_manpower"):
            missing.append("人力")
        if not detail.get("has_both_discipline"):
            missing.append("纪律")
        if not detail.get("has_both_land_morale"):
            missing.append("士气")
        if missing:
            lines.append(f"- 缺双方数字、禁止对比：{'、'.join(missing)}。")
            if "纪律" in missing:
                lines.append("- 无纪律数值：成稿勿提纪律（禁止臆造）。")
        if not detail.get("has_both_army") and not detail.get("has_both_manpower"):
            lines.append(
                "- 无双方兵力/人力：禁止「"
                + " / ".join(FORCE_COMPARE_FORBIDDEN_WITHOUT_BOTH[:3])
                + "」。"
            )
    lines.append(
        "- 硬性：无双方同维数字禁该维对比；有双方纪律/士气必须写入；禁止传统/职业度。"
    )
    return lines
