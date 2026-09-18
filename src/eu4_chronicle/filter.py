"""玩家中心事件过滤：默认丢弃全球无关战争与远方内政。"""

from __future__ import annotations

from eu4_chronicle.models import DiffEvent, DiffResult, GameState


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

    if ev.kind in {"war_started", "war_ended"}:
        participants = set(detail.get("attackers") or []) | set(detail.get("defenders") or [])
        if not participants and detail.get("participants"):
            participants = set(detail["participants"])
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
