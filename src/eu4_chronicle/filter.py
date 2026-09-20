"""玩家中心事件过滤：默认丢弃全球无关战争与远方内政。"""

from __future__ import annotations

from eu4_chronicle.models import DiffEvent, DiffResult, GameState, WarState

# 开局百年内：军科差 1 级可评「轻代差」
EARLY_GAME_YEAR_CUTOFF = 1500


def _parse_year(date: str | None) -> int | None:
    if not date:
        return None
    try:
        return int(str(date).split(".", 1)[0])
    except (TypeError, ValueError):
        return None


def is_early_game_date(date: str | None) -> bool:
    """存档日期是否落在开局百年（约 <1500）。"""
    year = _parse_year(date)
    return year is not None and year < EARLY_GAME_YEAR_CUTOFF


def _tech_levels(state: GameState, tag: str) -> dict[str, int] | None:
    country = state.countries.get(tag)
    if country is None:
        return None
    tech = country.technology or {}
    mil = tech.get("mil_tech")
    if mil is None:
        return None
    out: dict[str, int] = {"mil_tech": int(mil)}
    for k in ("adm_tech", "dip_tech"):
        if tech.get(k) is not None:
            out[k] = int(tech[k])
    return out


def _force_snapshot(state: GameState, tag: str) -> dict[str, float | int] | None:
    """玩家/战争领袖军力快照：军科 + 数量 + discipline/land_morale（有则写）。"""
    country = state.countries.get(tag)
    if country is None:
        return None
    snap: dict[str, float | int] = {}
    tech = _tech_levels(state, tag)
    if tech:
        snap.update(tech)
    # 数量：0 也是有效数字（已解析）
    snap["army_size"] = float(country.army_size)
    snap["navy_size"] = float(country.navy_size)
    snap["manpower"] = float(country.manpower)
    snap["max_manpower"] = float(country.max_manpower)
    if country.discipline is not None:
        snap["discipline"] = float(country.discipline)
    if country.land_morale is not None:
        snap["land_morale"] = float(country.land_morale)
    return snap


def _fmt_force_side(tag: str, snap: dict[str, float | int]) -> str:
    """单侧摘要片段：军科4 陆军x 人力a/b 纪律y 士气z（缺则省略）。"""
    bits: list[str] = [tag]
    if "mil_tech" in snap:
        bits.append(f"军科{int(snap['mil_tech'])}")
    if "army_size" in snap:
        bits.append(f"陆军{float(snap['army_size']):.0f}")
    if "navy_size" in snap and float(snap["navy_size"]) > 0:
        bits.append(f"海军{float(snap['navy_size']):.0f}")
    if "manpower" in snap:
        mx = snap.get("max_manpower")
        if mx is not None:
            bits.append(f"人力{float(snap['manpower']):.1f}/{float(mx):.1f}")
        else:
            bits.append(f"人力{float(snap['manpower']):.1f}")
    if "discipline" in snap:
        bits.append(f"纪律{_fmt_quality(snap['discipline'])}")
    if "land_morale" in snap:
        bits.append(f"士气{_fmt_quality(snap['land_morale'])}")
    return " ".join(bits)


def _fmt_quality(v: float | int) -> str:
    f = float(v)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:.3f}".rstrip("0").rstrip(".")


def _war_side_leader(side: list[str]) -> str | None:
    return side[0] if side else None


def enrich_war_tech_snapshots(
    events: list[DiffEvent],
    *,
    curr: GameState,
    player: str,
) -> list[DiffEvent]:
    """从 curr GameState 注入玩家参战战争的军力对比（军科+数量+纪律/士气）。

    参战方至少含攻守战争领袖 + 玩家；至少一侧有可比字段才生成。
    无双方同维数字时 detail 标记 has_both_* = False，供提示词禁该维对比。
    """
    if not player:
        return list(events)

    out = list(events)
    seen_wars: set[str] = set()
    for e in events:
        if e.kind == "war_tech_compare":
            name = str((e.detail or {}).get("name") or (e.detail or {}).get("war") or "")
            if name:
                seen_wars.add(name)

    early = is_early_game_date(curr.date)

    for w in curr.wars:
        compare = _war_tech_compare_event(w, curr=curr, player=player, early=early)
        if compare is None:
            continue
        name = str(compare.detail.get("name") or "")
        if name and name in seen_wars:
            continue
        if name:
            seen_wars.add(name)
        out.append(compare)
    return out


# 别名：计划称 war_military_compare；事件 kind 仍用 war_tech_compare 以兼容既有过滤/测试
enrich_war_military_snapshots = enrich_war_tech_snapshots


def _war_tech_compare_event(
    w: WarState,
    *,
    curr: GameState,
    player: str,
    early: bool,
) -> DiffEvent | None:
    involved = set(w.attackers) | set(w.defenders)
    if player not in involved:
        return None

    att_leader = _war_side_leader(w.attackers)
    def_leader = _war_side_leader(w.defenders)
    if player in w.attackers:
        foe = def_leader
    else:
        foe = att_leader
    if not foe or foe == player:
        return None

    snap_tags = [t for t in (att_leader, def_leader, player) if t]
    ordered: list[str] = list(dict.fromkeys(snap_tags))
    forces: dict[str, dict[str, float | int]] = {}
    levels: dict[str, dict[str, int]] = {}
    for tag in ordered:
        snap = _force_snapshot(curr, tag)
        if snap is not None:
            forces[tag] = snap
            tech_only = {
                k: int(v)
                for k, v in snap.items()
                if k in ("mil_tech", "adm_tech", "dip_tech")
            }
            if "mil_tech" in tech_only:
                levels[tag] = tech_only

    player_force = forces.get(player)
    foe_force = forces.get(foe)
    if not player_force or not foe_force:
        return None

    has_both_mil = "mil_tech" in player_force and "mil_tech" in foe_force
    army_signal = (
        "army_size" in player_force
        and "army_size" in foe_force
        and (
            float(player_force.get("army_size", 0)) > 0
            or float(foe_force.get("army_size", 0)) > 0
        )
    )
    navy_signal = (
        "navy_size" in player_force
        and "navy_size" in foe_force
        and (
            float(player_force.get("navy_size", 0)) > 0
            or float(foe_force.get("navy_size", 0)) > 0
        )
    )
    man_signal = (
        "manpower" in player_force
        and "manpower" in foe_force
        and (
            float(player_force.get("manpower", 0)) > 0
            or float(foe_force.get("manpower", 0)) > 0
        )
    )
    has_both_discipline = "discipline" in player_force and "discipline" in foe_force
    has_both_land_morale = "land_morale" in player_force and "land_morale" in foe_force
    has_both_army = army_signal
    has_both_navy = navy_signal
    has_both_manpower = man_signal

    # 无双方 mil、又无正兵力/人力、又无双方纪律/士气 → 不生成（避免空壳国瞎比）
    if not (
        has_both_mil
        or army_signal
        or man_signal
        or has_both_discipline
        or has_both_land_morale
    ):
        return None

    player_mil = int(player_force["mil_tech"]) if has_both_mil else None
    foe_mil = int(foe_force["mil_tech"]) if has_both_mil else None
    mil_gap = (player_mil - foe_mil) if has_both_mil else None

    # summary 中数量仅在有信号时写出，避免 陆军0 噪音；质量仅双方都有才写
    def _side_for_summary(tag: str, snap: dict[str, float | int]) -> dict[str, float | int]:
        out = dict(snap)
        if not army_signal:
            out.pop("army_size", None)
        if not navy_signal:
            out.pop("navy_size", None)
        if not man_signal:
            out.pop("manpower", None)
            out.pop("max_manpower", None)
        if not has_both_discipline:
            out.pop("discipline", None)
        if not has_both_land_morale:
            out.pop("land_morale", None)
        return out

    summary = (
        f"军力对比：{_fmt_force_side(player, _side_for_summary(player, player_force))} vs "
        f"{_fmt_force_side(foe, _side_for_summary(foe, foe_force))}"
    )
    if has_both_mil and mil_gap is not None:
        if early and abs(mil_gap) == 1:
            lead = player if mil_gap > 0 else foe
            summary += f"（早期轻代差，{lead} 军科领先 1 级）"
        elif mil_gap == 0:
            summary += "（军科同档）"

    participants = list(dict.fromkeys([*w.attackers, *w.defenders]))
    detail: dict = {
        "name": w.name,
        "war": w.name,
        "attackers": list(w.attackers),
        "defenders": list(w.defenders),
        "participants": participants,
        "attacker_leader": att_leader,
        "defender_leader": def_leader,
        "player": player,
        "foe": foe,
        "levels": levels,
        "forces": forces,
        "player_force": player_force,
        "foe_force": foe_force,
        "early_game": early,
        "has_both_mil": has_both_mil,
        "has_both_army": has_both_army,
        "has_both_navy": has_both_navy,
        "has_both_manpower": has_both_manpower,
        "has_both_discipline": has_both_discipline,
        "has_both_land_morale": has_both_land_morale,
    }
    if has_both_mil and player_mil is not None and foe_mil is not None:
        detail["player_mil"] = player_mil
        detail["foe_mil"] = foe_mil
        detail["mil_gap"] = mil_gap

    return DiffEvent(
        kind="war_tech_compare",
        tag=player,
        other_tag=foe,
        summary=summary,
        detail=detail,
    )


def vassalized_tags(events: list[DiffEvent], player: str) -> set[str]:
    """玩家在本区间新收附的 TAG 集合。"""
    gained: set[str] = set()
    for e in events:
        if e.kind != "subject_changed" or e.tag != player:
            continue
        for tag in e.detail.get("gained") or []:
            if tag:
                gained.add(str(tag))
    return gained


def consolidate_subject_alliance(
    events: list[DiffEvent],
    *,
    player: str,
) -> list[DiffEvent]:
    """同一对手 interval 内 alliance_broken + 收附 → 只保留收附，丢掉断盟悲剧叙事。

    附庸化常伴随旧同盟消失；外交优先写「收附 X」，事件列表合并/降级断盟。
    """
    if not player:
        return list(events)
    vassals = vassalized_tags(events, player)
    if not vassals:
        return list(events)

    out: list[DiffEvent] = []
    for e in events:
        if e.kind == "alliance_broken" and e.tag and e.other_tag:
            pair = {e.tag, e.other_tag}
            if player in pair:
                other = e.other_tag if e.tag == player else e.tag
                if other in vassals:
                    continue
        if e.kind == "subject_changed" and e.tag == player:
            gained = list(e.detail.get("gained") or [])
            if gained:
                detail = dict(e.detail)
                detail["supersedes_alliance_break"] = [
                    g for g in gained if g in vassals
                ]
                # 摘要强调收附，避免「附庸结构改组」空话
                gained_s = "、".join(gained)
                lost = list(detail.get("lost") or [])
                if lost:
                    summary = f"{player} 收附 {gained_s}（并调整附庸：失去 {lost}）"
                else:
                    summary = f"{player} 收附 {gained_s}"
                out.append(e.model_copy(update={"summary": summary, "detail": detail}))
                continue
        out.append(e)
    return out


def player_sphere(prev: GameState, curr: GameState, player: str) -> set[str]:
    """玩家 + 盟国/宿敌/附庸 + AE/好感对象 + 玩家参战对手。"""
    sphere: set[str] = {player} if player else set()
    for src in (prev, curr):
        p = src.countries.get(player) if player else None
        if not p:
            continue
        sphere.update(p.allies)
        sphere.update(p.rivals)
        sphere.update(p.subjects)
        sphere.update(p.aggressive_expansion)
        sphere.update(p.opinion_of)
    for wars in (prev.wars, curr.wars):
        for w in wars:
            involved = set(w.attackers) | set(w.defenders)
            if player and player in involved:
                sphere.update(involved)
    return {t for t in sphere if t}


def filter_player_events(
    events: list[DiffEvent],
    *,
    player: str,
    sphere: set[str] | None = None,
    include_global: bool = False,
) -> list[DiffEvent]:
    """默认只保留与玩家强相关的事件；include_global=True 时原样返回。"""
    if include_global or not player:
        return _dedupe_bilateral(list(events), player=player)

    sphere = set(sphere or {player})
    sphere.add(player)
    kept: list[DiffEvent] = []
    for ev in events:
        if _keep_event(ev, player=player, sphere=sphere):
            kept.append(ev)
    return _dedupe_bilateral(kept, player=player)


def _dedupe_bilateral(events: list[DiffEvent], *, player: str) -> list[DiffEvent]:
    """同盟/宿敌等双边镜像只保留一条（优先玩家为 tag 的一侧）。"""
    pair_kinds = {
        "alliance_formed",
        "alliance_broken",
        "rival_set",
        "rival_cleared",
    }
    seen: set[tuple] = set()
    out: list[DiffEvent] = []
    # 玩家侧优先
    ordered = sorted(
        events,
        key=lambda e: (0 if e.tag == player else 1, e.kind, e.tag or "", e.other_tag or ""),
    )
    for ev in ordered:
        if ev.kind in pair_kinds and ev.tag and ev.other_tag:
            key = (ev.kind, frozenset({ev.tag, ev.other_tag}))
            if key in seen:
                continue
            seen.add(key)
        out.append(ev)
    # 恢复大致稳定顺序
    out.sort(key=lambda e: (e.kind, e.tag or "", e.summary))
    return out


def filter_diff(
    diff: DiffResult,
    *,
    prev: GameState | None = None,
    curr: GameState | None = None,
    include_global: bool = False,
) -> DiffResult:
    player = diff.player
    sphere: set[str] = {player} if player else set()
    if prev is not None and curr is not None and player:
        sphere = player_sphere(prev, curr, player)
    filtered = filter_player_events(
        diff.events,
        player=player,
        sphere=sphere,
        include_global=include_global,
    )
    if player:
        filtered = consolidate_subject_alliance(filtered, player=player)
    # 战争参与方军科快照：从 curr 注入，默认进入玩家过滤结果
    if player and curr is not None:
        filtered = enrich_war_tech_snapshots(filtered, curr=curr, player=player)
    return diff.model_copy(
        update={
            "events": filtered,
            "raw_event_count": getattr(diff, "raw_event_count", None) or len(diff.events),
            "filtered": not include_global,
        }
    )


def _keep_event(ev: DiffEvent, *, player: str, sphere: set[str]) -> bool:
    if ev.kind == "date_changed":
        return True

    detail = ev.detail or {}
    tags_in_event = _event_tags(ev)

    if ev.kind in {"war_started", "war_ended", "war_tech_compare"}:
        participants = set(detail.get("attackers") or []) | set(detail.get("defenders") or [])
        if not participants and detail.get("participants"):
            participants = set(detail["participants"])
        if ev.kind == "war_tech_compare" and detail.get("player") == player:
            return True
        return player in participants

    if ev.kind == "war_score_changed":
        participants = (
            set(detail.get("participants") or [])
            | set(detail.get("attackers") or [])
            | set(detail.get("defenders") or [])
        )
        return bool(participants) and player in participants

    # 玩家国家自身属性 / 省份 / 核心
    if ev.tag == player:
        return True

    # 与玩家的双边关系（同盟、宿敌、AE、好感、附庸）
    if ev.other_tag == player:
        return True

    if ev.kind in {
        "alliance_formed",
        "alliance_broken",
        "rival_set",
        "rival_cleared",
        "ae_changed",
        "opinion_changed",
        "subject_changed",
    }:
        if tags_in_event & {player}:
            return True
        # 附庸变化：玩家收附/失去
        for key in ("gained", "lost"):
            vals = detail.get(key) or []
            if player in vals:
                return True
        return False

    # 省份得失：仅玩家；远方伊藤/岛津等一律丢弃
    if ev.kind in {"province_gained", "province_lost", "core_gained", "core_lost"}:
        return ev.tag == player

    # 其他内政（发展度、科技、兵力…）：仅玩家
    if ev.kind in {
        "development_changed",
        "tech_changed",
        "religion_changed",
        "monarch_changed",
        "manpower_changed",
        "army_changed",
        "navy_changed",
        "stability_changed",
        "prestige_changed",
    }:
        return ev.tag == player

    # 兜底：事件涉及玩家本人
    return player in tags_in_event


def _event_tags(ev: DiffEvent) -> set[str]:
    tags: set[str] = set()
    if ev.tag:
        tags.add(ev.tag)
    if ev.other_tag:
        tags.add(ev.other_tag)
    detail = ev.detail or {}
    for key in ("attackers", "defenders", "participants", "gained", "lost"):
        vals = detail.get(key)
        if isinstance(vals, list):
            tags.update(str(x) for x in vals if x)
    for key in ("viewer", "target"):
        if detail.get(key):
            tags.add(str(detail[key]))
    return tags
