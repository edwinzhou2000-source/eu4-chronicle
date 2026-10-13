"""两态 GameState Diff → 事件列表。"""

from __future__ import annotations

from eu4_game_report.models import CountryState, DiffEvent, DiffResult, GameState, WarState


def diff_states(prev: GameState, curr: GameState) -> DiffResult:
    """全量 Diff（含全球事件）。玩家中心裁剪见 ``eu4_game_report.filter``。"""
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
        events.extend(_diff_country(a, b))

    war_events = _diff_wars(prev.wars, curr.wars, player)
    # active→previous 去重时：补 outcome/媾和日/lifetime 攻守；
    # 禁止用归档 last_warscore_* 覆盖 prev active 的 player_warscore（归档后常失真）
    curr_prev_by_name = {w.name: w for w in curr.previous_wars}
    for e in war_events:
        if e.kind != "war_ended":
            continue
        name = str((e.detail or {}).get("name") or "")
        finished = curr_prev_by_name.get(name)
        if finished is None:
            continue
        detail = dict(e.detail or {})
        kept_score = detail.get("player_warscore")
        kept_ticking = detail.get("player_ticking_warscore")
        detail.update(_outcome_extras(finished, player))
        if finished.attackers:
            detail["attackers"] = finished.attackers
        if finished.defenders:
            detail["defenders"] = finished.defenders
        detail["participants"] = _war_involved(finished)
        # 战分：优先保留 active 消失前的分；仅缺失时才尝试归档分（且须可靠）
        if kept_score is not None:
            detail["player_warscore"] = kept_score
        else:
            archived = finished.score_for(player) if player else None
            if archived is not None and not _archived_warscore_unreliable(
                finished.outcome, archived
            ):
                detail["player_warscore"] = archived
            elif archived is not None:
                detail["player_warscore"] = None
                detail["score_unreliable"] = True
                detail["raw_last_warscore"] = archived
        if kept_ticking is not None:
            detail["player_ticking_warscore"] = kept_ticking
        e.detail = detail
        if finished.outcome == 2:
            e.summary = f"战争「{name}」结束：攻方取胜"
        elif finished.outcome == 3:
            e.summary = f"战争「{name}」结束：守方取胜"
        elif finished.outcome == 1:
            e.summary = f"战争「{name}」结束：白和"
    events.extend(war_events)
    already_ended = {
        str((e.detail or {}).get("name") or "")
        for e in war_events
        if e.kind == "war_ended"
    }
    events.extend(
        _diff_previous_wars(
            prev.previous_wars,
            curr.previous_wars,
            player,
            skip_names=already_ended,
        )
    )
    events.extend(_diff_player_missions(prev, curr))

    events.sort(key=lambda e: (e.kind, e.tag or "", e.summary))
    return DiffResult(
        prev_date=prev.date,
        curr_date=curr.date,
        player=player,
        events=events,
        raw_event_count=len(events),
        filtered=False,
    )


def _diff_player_missions(prev: GameState, curr: GameState) -> list[DiffEvent]:
    """玩家任务树：按各档 player TAG 取 completed_missions 做集合差。

    转 TAG / 换树时旧完成 ID 通常随国家块迁移；消失的 ID 单独标 missions_lost，
    不计入新完成。
    """
    events: list[DiffEvent] = []
    prev_tag = (prev.player or "").strip()
    curr_tag = (curr.player or "").strip()
    if not curr_tag and not prev_tag:
        return events

    if prev_tag and curr_tag and prev_tag != curr_tag:
        events.append(
            DiffEvent(
                kind="player_tag_changed",
                tag=curr_tag,
                other_tag=prev_tag,
                summary=f"玩家 TAG 变化：{prev_tag} → {curr_tag}（成立新国家或换皮）",
                detail={"from": prev_tag, "to": curr_tag},
            )
        )

    prev_c = prev.countries.get(prev_tag) if prev_tag else None
    curr_c = curr.countries.get(curr_tag) if curr_tag else None
    prev_set = set(prev_c.completed_missions if prev_c else [])
    curr_set = set(curr_c.completed_missions if curr_c else [])

    gained = sorted(curr_set - prev_set)
    lost = sorted(prev_set - curr_set)
    player = curr_tag or prev_tag

    for mid in gained:
        events.append(
            DiffEvent(
                kind="mission_completed",
                tag=player,
                summary=f"完成任务 {mid}",
                detail={"mission_id": mid},
            )
        )

    if lost:
        events.append(
            DiffEvent(
                kind="missions_lost",
                tag=player,
                summary=(
                    f"部分旧任务完成记录在新档中消失（{len(lost)} 项；"
                    "可能换树重置），不计入新完成"
                ),
                detail={"mission_ids": lost, "count": len(lost)},
            )
        )

    return events


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
        # 仍写入 raw Diff；默认玩家过滤会丢掉（战报只写 province_gained）
        owned_prev = set(a.owned_provinces)
        events.append(
            DiffEvent(
                kind="core_gained",
                tag=tag,
                summary=f"{tag} 新增核心 {core_gained}",
                detail={
                    "cores": core_gained,
                    "coring_owned": [p for p in core_gained if p in owned_prev],
                    "cores_elsewhere": [p for p in core_gained if p not in owned_prev],
                },
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
                    f"{tag} 当前人力 {a.manpower:.1f}k→{b.manpower:.1f}k；"
                    f"人力上限 {a.max_manpower:.1f}k→{b.max_manpower:.1f}k"
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


def _war_scores(w: WarState) -> dict[str, float]:
    tags = set(w.attackers) | set(w.defenders) | {p.tag for p in w.participants}
    out: dict[str, float] = {}
    for tag in tags:
        score = w.score_for(tag)
        if score is not None:
            out[tag] = float(score)
    return out


def _war_involved(w: WarState) -> list[str]:
    """攻守列表 + participants TAG（previous_war 结束时 history rem 可能清空攻守）。"""
    tags: list[str] = []
    for t in [*w.attackers, *w.defenders]:
        if t and t not in tags:
            tags.append(t)
    for p in w.participants:
        if p.tag and p.tag not in tags:
            tags.append(p.tag)
    return tags


def _archived_warscore_unreliable(outcome: int | None, attacker_score: float | None) -> bool:
    """previous_war 归档后 last_warscore_* 常失真：与 outcome 符号矛盾则不可靠。"""
    if outcome is None or attacker_score is None:
        return False
    if outcome == 2 and attacker_score < 0:
        return True
    if outcome == 3 and attacker_score > 0:
        return True
    return False


def _outcome_extras(w: WarState, player: str = "") -> dict:
    """仅 outcome / 媾和日 / 玩家胜负——不含战分字段。"""
    extras: dict = {}
    if w.outcome is not None:
        extras["outcome"] = w.outcome
        extras["outcome_label"] = {1: "draw", 2: "attacker_win", 3: "defender_win"}.get(
            w.outcome, f"outcome_{w.outcome}"
        )
    if w.ended_date:
        extras["ended_date"] = w.ended_date
    if player:
        pw = w.player_won(player)
        if pw is not None:
            extras["player_won"] = pw
        elif w.outcome == 1:
            extras["player_won"] = None
            extras["peace_draw"] = True
    return extras


def _war_detail_extras(w: WarState, player: str = "") -> dict:
    extras: dict = {}
    extras.update(_outcome_extras(w, player))
    if w.war_goal_type:
        extras["war_goal_type"] = w.war_goal_type
    if w.casus_belli:
        extras["casus_belli"] = w.casus_belli
    if w.war_goal_province is not None:
        extras["war_goal_province"] = w.war_goal_province
    if w.war_goal_tag:
        extras["war_goal_tag"] = w.war_goal_tag
    if w.occupied_provinces is not None:
        extras["occupied_provinces"] = w.occupied_provinces
    if w.last_warscore_quarter is not None:
        extras["last_warscore_quarter"] = w.last_warscore_quarter
    if w.last_warscore_year is not None:
        extras["last_warscore_year"] = w.last_warscore_year
    if w.attacker_score is not None:
        extras["attacker_score"] = w.attacker_score
    if w.defender_score is not None:
        extras["defender_score"] = w.defender_score
    if w.total_score_source:
        extras["total_score_source"] = w.total_score_source
    if w.ticking_score_source:
        extras["ticking_score_source"] = w.ticking_score_source
    if w.raw_score_fields:
        extras["raw_score_fields"] = dict(w.raw_score_fields)
    if player:
        tick = w.ticking_for(player)
        if tick is not None:
            extras["player_ticking_warscore"] = tick
    if w.battles:
        extras["major_battles"] = [
            {
                "name": b.name,
                "date": b.date,
                "location": b.location,
                "attacker_won": b.attacker_won,
                "attacker_tag": b.attacker_tag,
                "defender_tag": b.defender_tag,
                "attacker_losses": b.attacker_losses,
                "defender_losses": b.defender_losses,
            }
            for b in w.battles[:3]
        ]
    return extras


def _diff_previous_wars(
    prev: list[WarState],
    curr: list[WarState],
    player: str,
    *,
    skip_names: set[str] | None = None,
) -> list[DiffEvent]:
    """两档 previous_war 集合差：期内结束且未由 active 差集发出的战争。"""
    events: list[DiffEvent] = []
    skip = skip_names or set()
    prev_names = {w.name for w in prev}
    curr_map = {w.name: w for w in curr}
    for name in sorted(set(curr_map) - prev_names):
        if name in skip or not name:
            continue
        w = curr_map[name]
        involved = _war_involved(w)
        primary = (
            player
            if player in involved
            else (w.attackers[0] if w.attackers else (w.defenders[0] if w.defenders else (involved[0] if involved else None)))
        )
        scores = _war_scores(w)
        # 归档 last_warscore 为攻方视角；与 outcome 符号矛盾则不可靠
        attacker_total = w.total_attacker_score
        if attacker_total is None:
            attacker_total = w.last_warscore_quarter
        if attacker_total is None:
            attacker_total = w.last_warscore_year
        unreliable = _archived_warscore_unreliable(w.outcome, attacker_total)
        player_ws = None if unreliable else (w.score_for(player) if player else None)
        if w.outcome == 2:
            summary = f"战争「{name}」于本区间内结束：攻方取胜（攻方 {w.attackers}，守方 {w.defenders}）"
        elif w.outcome == 3:
            summary = f"战争「{name}」于本区间内结束：守方取胜（攻方 {w.attackers}，守方 {w.defenders}）"
        elif w.outcome == 1:
            summary = f"战争「{name}」于本区间内结束：白和（攻方 {w.attackers}，守方 {w.defenders}）"
        else:
            summary = f"战争「{name}」于本区间内结束（攻方 {w.attackers}，守方 {w.defenders}）"
        detail = {
            "name": name,
            "attackers": w.attackers,
            "defenders": w.defenders,
            "participants": involved,
            "scores": scores,
            "player_warscore": player_ws,
            "source": "previous_war",
            **_war_detail_extras(w, player),
        }
        # extras 可能再次写入 last_warscore；强制 player 分与不可靠标记
        detail["player_warscore"] = player_ws
        if unreliable:
            detail["score_unreliable"] = True
            detail["raw_last_warscore"] = attacker_total
            detail.pop("player_ticking_warscore", None)
        events.append(
            DiffEvent(
                kind="war_ended",
                tag=primary,
                summary=summary,
                detail=detail,
            )
        )
    return events


def _diff_wars(prev: list[WarState], curr: list[WarState], player: str) -> list[DiffEvent]:
    """战争事件：tag 标主参战方，detail 带攻守列表与 warscore；不过滤（由 filter 裁剪）。"""
    events: list[DiffEvent] = []
    prev_map = {w.name: w for w in prev}
    curr_map = {w.name: w for w in curr}

    for name in sorted(set(curr_map) - set(prev_map)):
        w = curr_map[name]
        involved = _war_involved(w)
        primary = (
            player
            if player in involved
            else (w.attackers[0] if w.attackers else (w.defenders[0] if w.defenders else (involved[0] if involved else None)))
        )
        scores = _war_scores(w)
        player_ws = w.score_for(player) if player else None
        score_bit = ""
        if player_ws is not None:
            score_bit = f"；玩家战分 {player_ws:+.0f}"
        events.append(
            DiffEvent(
                kind="war_started",
                tag=primary,
                summary=f"爆发战争「{name}」：攻方 {w.attackers} vs 守方 {w.defenders}{score_bit}",
                detail={
                    "name": name,
                    "attackers": w.attackers,
                    "defenders": w.defenders,
                    "participants": involved,
                    "scores": scores,
                    "player_warscore": player_ws,
                    **_war_detail_extras(w, player),
                },
            )
        )
    for name in sorted(set(prev_map) - set(curr_map)):
        w = prev_map[name]
        involved = _war_involved(w)
        primary = (
            player
            if player in involved
            else (w.attackers[0] if w.attackers else (involved[0] if involved else None))
        )
        scores = _war_scores(w)
        player_ws = w.score_for(player) if player else None
        events.append(
            DiffEvent(
                kind="war_ended",
                tag=primary,
                summary=f"战争「{name}」结束（攻方曾为 {w.attackers}，守方 {w.defenders}）",
                detail={
                    "name": name,
                    "attackers": w.attackers,
                    "defenders": w.defenders,
                    "participants": involved,
                    "scores": scores,
                    "player_warscore": player_ws,
                    "source": "active_war",
                    **_war_detail_extras(w, player),
                },
            )
        )
    for name in sorted(set(prev_map) & set(curr_map)):
        a, b = prev_map[name], curr_map[name]
        involved = list(dict.fromkeys([*_war_involved(b), *_war_involved(a)]))
        a_scores = _war_scores(a)
        b_scores = _war_scores(b)
        # 玩家参战：始终写入当前战分（即使跳变 <5），供叙事分档
        tags_to_emit = set()
        for tag in set(a_scores) | set(b_scores):
            av, bv = a_scores.get(tag, 0.0), b_scores.get(tag, 0.0)
            if tag == player or abs(bv - av) >= 5:
                tags_to_emit.add(tag)
        if player and player in involved and player not in tags_to_emit:
            tags_to_emit.add(player)
        for tag in sorted(tags_to_emit):
            av = a.score_for(tag)
            bv = b.score_for(tag)
            # 两端皆未知则跳过，避免伪造 0→0
            if av is None and bv is None:
                continue
            av_f = float(av) if av is not None else 0.0
            bv_f = float(bv) if bv is not None else 0.0
            player_ws = b.score_for(player) if player else None
            events.append(
                DiffEvent(
                    kind="war_score_changed",
                    tag=tag,
                    summary=f"战争「{name}」中 {tag} 战争分数 {av_f:.0f} → {bv_f:.0f}",
                    detail={
                        "war": name,
                        "name": name,
                        "from": av,
                        "to": bv,
                        "attackers": b.attackers,
                        "defenders": b.defenders,
                        "participants": involved,
                        "scores": b_scores,
                        "player_warscore": player_ws,
                        **_war_detail_extras(b, player),
                    },
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
    player = diff.player or "未知"
    lines = [
        f"玩家: {player}",
        f"区间: {diff.prev_date or '?'} → {diff.curr_date or '?'}",
        f"事件数: {len(diff.events)}"
        + (
            f"（过滤前 {diff.raw_event_count}）"
            if diff.raw_event_count and diff.raw_event_count != len(diff.events)
            else ""
        ),
        "",
    ]
    for i, ev in enumerate(diff.events[:limit], 1):
        lines.append(f"{i}. [{ev.kind}] {ev.summary}")
    if len(diff.events) > limit:
        lines.append(f"... 另有 {len(diff.events) - limit} 条未列出")
    return "\n".join(lines)
