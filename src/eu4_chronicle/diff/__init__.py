"""两态 GameState Diff → 事件列表。"""

from __future__ import annotations

from eu4_chronicle.models import CountryState, DiffEvent, DiffResult, GameState, WarState


def diff_states(prev: GameState, curr: GameState) -> DiffResult:
    player = curr.player or prev.player
    events: list[DiffEvent] = []

    if prev.date != curr.date:
        events.append(
            DiffEvent(
                kind="date_changed",
                tag=player or None,
                summary=f"时间从 {prev.date or '?'} 推进至 {curr.date or '?'}",
                detail={"from": prev.date, "to": curr.date},
            )
        )

    tags = sorted(set(prev.countries) | set(curr.countries))
    focus = {player} if player else set()
    # 也关注玩家盟国/宿敌相关变化：先全量再由 Agent 筛选；为控制体量，优先玩家及与玩家有关系的国家
    related = set(focus)
    for src in (prev, curr):
        p = src.countries.get(player) if player else None
        if p:
            related.update(p.allies)
            related.update(p.rivals)
            related.update(p.subjects)
            related.update(p.aggressive_expansion)
            related.update(p.opinion_of)

    for tag in tags:
        a = prev.countries.get(tag)
        b = curr.countries.get(tag)
        if a is None and b is not None:
            events.append(
                DiffEvent(
                    kind="subject_changed",
                    tag=tag,
                    summary=f"国家 {tag} 在后期档中出现（新生/释放/未被解析到前期）",
                    detail={"appeared": True},
                )
            )
            continue
        if a is not None and b is None:
            events.append(
                DiffEvent(
                    kind="province_lost",
                    tag=tag,
                    summary=f"国家 {tag} 在后期档中消失（可能被吞并）",
                    detail={"annexed_or_missing": True},
                )
            )
            continue
        assert a is not None and b is not None
        # 非相关小国：只保留吞并级与对玩家 AE/关系
        interesting = tag in related or bool(set(a.owned_provinces) ^ set(b.owned_provinces))
        if not interesting and player and tag != player:
            # 仍检测对玩家的 AE/opinion
            _diff_ae_opinion(a, b, events, only_vs=player)
            continue
        events.extend(_diff_country(a, b))

    events.extend(_diff_wars(prev.wars, curr.wars, player))

    # 稳定排序：种类 + tag
    events.sort(key=lambda e: (e.kind, e.tag or "", e.summary))
    return DiffResult(
        prev_date=prev.date,
        curr_date=curr.date,
        player=player,
        events=events,
    )


def _diff_country(a: CountryState, b: CountryState) -> list[DiffEvent]:
    events: list[DiffEvent] = []
    tag = b.tag

    gained = sorted(set(b.owned_provinces) - set(a.owned_provinces))
    lost = sorted(set(a.owned_provinces) - set(b.owned_provinces))
    if gained:
        events.append(
            DiffEvent(
                kind="province_gained",
                tag=tag,
                summary=f"{tag} 获得省份 {gained}",
                detail={"provinces": gained},
            )
        )
    if lost:
        events.append(
            DiffEvent(
                kind="province_lost",
                tag=tag,
                summary=f"{tag} 失去省份 {lost}",
                detail={"provinces": lost},
            )
        )

    core_gained = sorted(set(b.cores) - set(a.cores))
    core_lost = sorted(set(a.cores) - set(b.cores))
    if core_gained:
        events.append(
            DiffEvent(
                kind="core_gained",
                tag=tag,
                summary=f"{tag} 新增核心 {core_gained}",
                detail={"cores": core_gained},
            )
        )
    if core_lost:
        events.append(
            DiffEvent(
                kind="core_lost",
                tag=tag,
                summary=f"{tag} 失去核心 {core_lost}",
                detail={"cores": core_lost},
            )
        )

    for other in sorted(set(b.allies) - set(a.allies)):
        events.append(
            DiffEvent(
                kind="alliance_formed",
                tag=tag,
                other_tag=other,
                summary=f"{tag} 与 {other} 结成同盟",
                detail={},
            )
        )
    for other in sorted(set(a.allies) - set(b.allies)):
        events.append(
            DiffEvent(
                kind="alliance_broken",
                tag=tag,
                other_tag=other,
                summary=f"{tag} 与 {other} 同盟破裂",
                detail={},
            )
        )

    for other in sorted(set(b.rivals) - set(a.rivals)):
        events.append(
            DiffEvent(
                kind="rival_set",
                tag=tag,
                other_tag=other,
                summary=f"{tag} 将 {other} 设为宿敌",
            )
        )
    for other in sorted(set(a.rivals) - set(b.rivals)):
        events.append(
            DiffEvent(
                kind="rival_cleared",
                tag=tag,
                other_tag=other,
                summary=f"{tag} 不再视 {other} 为宿敌",
            )
        )

    sub_gained = sorted(set(b.subjects) - set(a.subjects))
    sub_lost = sorted(set(a.subjects) - set(b.subjects))
    if sub_gained or sub_lost:
        events.append(
            DiffEvent(
                kind="subject_changed",
                tag=tag,
                summary=f"{tag} 附庸变化：+{sub_gained} -{sub_lost}",
                detail={"gained": sub_gained, "lost": sub_lost},
            )
        )

    if abs(b.development - a.development) >= 1:
        events.append(
            DiffEvent(
                kind="development_changed",
                tag=tag,
                summary=f"{tag} 发展度 {a.development:.0f} → {b.development:.0f}",
                detail={"from": a.development, "to": b.development},
            )
        )

    for k in sorted(set(a.technology) | set(b.technology)):
        av, bv = a.technology.get(k, 0), b.technology.get(k, 0)
        if av != bv:
            events.append(
                DiffEvent(
                    kind="tech_changed",
                    tag=tag,
                    summary=f"{tag} {k} {av} → {bv}",
                    detail={"tech": k, "from": av, "to": bv},
                )
            )

    if a.religion and b.religion and a.religion != b.religion:
        events.append(
            DiffEvent(
                kind="religion_changed",
                tag=tag,
                summary=f"{tag} 国教 {a.religion} → {b.religion}",
                detail={"from": a.religion, "to": b.religion},
            )
        )

    if _monarch_key(a) != _monarch_key(b):
        events.append(
            DiffEvent(
                kind="monarch_changed",
                tag=tag,
                summary=f"{tag} 君主变更：{_fmt_monarch(a)} → {_fmt_monarch(b)}",
                detail={},
            )
        )

    if abs(b.manpower - a.manpower) >= 1 or abs(b.max_manpower - a.max_manpower) >= 1:
        events.append(
            DiffEvent(
                kind="manpower_changed",
                tag=tag,
                summary=(
                    f"{tag} 人力 {a.manpower:.1f}/{a.max_manpower:.1f} → "
                    f"{b.manpower:.1f}/{b.max_manpower:.1f}"
                ),
                detail={
                    "from": a.manpower,
                    "to": b.manpower,
                    "max_from": a.max_manpower,
                    "max_to": b.max_manpower,
                },
            )
        )

    if abs(b.army_size - a.army_size) >= 1:
        events.append(
            DiffEvent(
                kind="army_changed",
                tag=tag,
                summary=f"{tag} 陆军规模约 {a.army_size:.0f} → {b.army_size:.0f}",
                detail={"from": a.army_size, "to": b.army_size},
            )
        )
    if abs(b.navy_size - a.navy_size) >= 1:
        events.append(
            DiffEvent(
                kind="navy_changed",
                tag=tag,
                summary=f"{tag} 海军规模约 {a.navy_size:.0f} → {b.navy_size:.0f}",
                detail={"from": a.navy_size, "to": b.navy_size},
            )
        )

    if a.stability != b.stability:
        events.append(
            DiffEvent(
                kind="stability_changed",
                tag=tag,
                summary=f"{tag} 稳定度 {a.stability} → {b.stability}",
                detail={"from": a.stability, "to": b.stability},
            )
        )
    if abs(b.prestige - a.prestige) >= 5:
        events.append(
            DiffEvent(
                kind="prestige_changed",
                tag=tag,
                summary=f"{tag} 威望 {a.prestige:.0f} → {b.prestige:.0f}",
                detail={"from": a.prestige, "to": b.prestige},
            )
        )

    _diff_ae_opinion(a, b, events)
    return events


def _diff_ae_opinion(
    a: CountryState,
    b: CountryState,
    events: list[DiffEvent],
    *,
    only_vs: str | None = None,
) -> None:
    tag = b.tag
    ae_keys = set(a.aggressive_expansion) | set(b.aggressive_expansion)
    for other in sorted(ae_keys):
        if only_vs and other != only_vs and tag != only_vs:
            continue
        av = a.aggressive_expansion.get(other, 0.0)
        bv = b.aggressive_expansion.get(other, 0.0)
        if abs(bv - av) >= 1:
            events.append(
                DiffEvent(
                    kind="ae_changed",
                    tag=tag,
                    other_tag=other,
                    summary=f"{other} 对 {tag} 的 AE {av:.0f} → {bv:.0f}",
                    detail={"from": av, "to": bv, "viewer": other, "target": tag},
                )
            )

    op_keys = set(a.opinion_of) | set(b.opinion_of)
    for other in sorted(op_keys):
        if only_vs and other != only_vs and tag != only_vs:
            continue
        av = a.opinion_of.get(other, 0.0)
        bv = b.opinion_of.get(other, 0.0)
        if abs(bv - av) >= 10:
            events.append(
                DiffEvent(
                    kind="opinion_changed",
                    tag=tag,
                    other_tag=other,
                    summary=f"{tag} 对 {other} 好感 {av:.0f} → {bv:.0f}",
                    detail={"from": av, "to": bv},
                )
            )


def _diff_wars(prev: list[WarState], curr: list[WarState], player: str) -> list[DiffEvent]:
    events: list[DiffEvent] = []
    prev_map = {w.name: w for w in prev}
    curr_map = {w.name: w for w in curr}

    for name in sorted(set(curr_map) - set(prev_map)):
        w = curr_map[name]
        events.append(
            DiffEvent(
                kind="war_started",
                tag=player or None,
                summary=f"爆发战争「{name}」：攻方 {w.attackers} vs 守方 {w.defenders}",
                detail={
                    "name": name,
                    "attackers": w.attackers,
                    "defenders": w.defenders,
                },
            )
        )
    for name in sorted(set(prev_map) - set(curr_map)):
        w = prev_map[name]
        events.append(
            DiffEvent(
                kind="war_ended",
                tag=player or None,
                summary=f"战争「{name}」结束（攻方曾为 {w.attackers}，守方 {w.defenders}）",
                detail={"name": name},
            )
        )
    for name in sorted(set(prev_map) & set(curr_map)):
        a, b = prev_map[name], curr_map[name]
        a_scores = {p.tag: p.warscore for p in a.participants}
        b_scores = {p.tag: p.warscore for p in b.participants}
        for tag in sorted(set(a_scores) | set(b_scores)):
            av, bv = a_scores.get(tag, 0.0), b_scores.get(tag, 0.0)
            if abs(bv - av) >= 5:
                events.append(
                    DiffEvent(
                        kind="war_score_changed",
                        tag=tag,
                        summary=f"战争「{name}」中 {tag} 战争分数 {av:.0f} → {bv:.0f}",
                        detail={"war": name, "from": av, "to": bv},
                    )
                )
    return events


def _monarch_key(c: CountryState) -> tuple:
    m = c.monarch
    if m is None:
        return ()
    return (m.name, m.adm, m.dip, m.mil)


def _fmt_monarch(c: CountryState) -> str:
    m = c.monarch
    if m is None:
        return "无"
    return f"{m.name}（{m.adm}/{m.dip}/{m.mil}）"


def events_to_brief(diff: DiffResult, *, limit: int = 80) -> str:
    lines = [
        f"玩家: {diff.player or '未知'}",
        f"区间: {diff.prev_date or '?'} → {diff.curr_date or '?'}",
        f"事件数: {len(diff.events)}",
        "",
    ]
    for i, ev in enumerate(diff.events[:limit], 1):
        lines.append(f"{i}. [{ev.kind}] {ev.summary}")
    if len(diff.events) > limit:
        lines.append(f"... 另有 {len(diff.events) - limit} 条未列出")
    return "\n".join(lines)
