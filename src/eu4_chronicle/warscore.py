"""玩家战争分数态势：按战分分档措辞，禁止无数据时写「胜负未定」。"""

from __future__ import annotations

from dataclasses import dataclass, field

from eu4_chronicle.models import DiffEvent, DiffResult

# 显著正分：基本打赢 / 优势在握
DECISIVE_SCORE = 50.0
# 偏胜
ADVANTAGE_SCORE = 20.0
# |分| 低于此视为胶着
CONTESTED_ABS = 15.0


def format_ticking_bonus(score: float) -> str:
    """成稿用：战争目标达成程度 bonus；只写「战争目标加分 ±N」，不加范围注解。"""
    return f"战争目标加分 {score:+.0f}"


@dataclass
class WarStanding:
    """单场战争中玩家侧战分。"""

    war_name: str
    war_name_zh: str | None = None
    player_score: float = 0.0
    score_from: float | None = None
    score_known: bool = False
    ticking_score: float | None = None
    tier: str = "unknown"  # decisive | advantage | contested | disadvantage | collapse | unknown
    attackers: list[str] = field(default_factory=list)
    defenders: list[str] = field(default_factory=list)
    war_goal_type: str | None = None
    casus_belli: str | None = None
    war_goal_province: int | None = None
    occupied_provinces: int | None = None
    major_battles: list[dict] = field(default_factory=list)


@dataclass
class WarAssessment:
    standings: list[WarStanding] = field(default_factory=list)

    @property
    def best_score(self) -> float | None:
        known = [s for s in self.standings if s.score_known]
        if not known:
            return None
        return max(s.player_score for s in known)

    @property
    def primary(self) -> WarStanding | None:
        if not self.standings:
            return None
        known = [s for s in self.standings if s.score_known]
        pool = known or self.standings
        return max(pool, key=lambda s: abs(s.player_score) if s.score_known else 0)


def classify_warscore(score: float) -> str:
    if score >= DECISIVE_SCORE:
        return "decisive"
    if score >= ADVANTAGE_SCORE:
        return "advantage"
    if score <= -DECISIVE_SCORE:
        return "collapse"
    if score <= -ADVANTAGE_SCORE:
        return "disadvantage"
    return "contested"


def tier_phrase(tier: str, *, score: float | None = None) -> str:
    """面向成稿的短句；仅 contested 可用「胜负未定」。"""
    sc = f"（战分 {score:+.0f}）" if score is not None else ""
    if tier == "decisive":
        return f"优势在握，基本打赢{sc}"
    if tier == "advantage":
        return f"战局偏我{sc}"
    if tier == "collapse":
        return f"战分崩塌，局势危急{sc}"
    if tier == "disadvantage":
        return f"战分落后{sc}"
    if tier == "unknown":
        return "档内未解析到玩家战分，不作胜负判断"
    return f"双方胶着，胜负未定{sc}"


def _score_from_event(e: DiffEvent, player: str) -> float | None:
    detail = e.detail or {}
    if detail.get("player_warscore") is not None:
        try:
            return float(detail["player_warscore"])
        except (TypeError, ValueError):
            pass
    if e.kind == "war_score_changed" and e.tag == player:
        if detail.get("to") is None:
            return None
        try:
            return float(detail.get("to", 0))
        except (TypeError, ValueError):
            return None
    scores = detail.get("scores") or {}
    if isinstance(scores, dict) and player in scores:
        try:
            return float(scores[player])
        except (TypeError, ValueError):
            pass
    return None


def assess_player_wars(diff: DiffResult) -> WarAssessment:
    """从 war_* 事件提取玩家侧战分并分档。"""
    player = diff.player
    by_war: dict[str, WarStanding] = {}

    for e in diff.events:
        if e.kind not in {"war_started", "war_ended", "war_score_changed"}:
            continue
        detail = e.detail or {}
        name = str(detail.get("name") or detail.get("war") or "")
        if not name:
            continue
        participants = (
            set(detail.get("participants") or [])
            | set(detail.get("attackers") or [])
            | set(detail.get("defenders") or [])
        )
        if player and player not in participants and e.tag != player:
            continue

        score = _score_from_event(e, player) if player else None

        standing = by_war.get(name)
        if standing is None:
            standing = WarStanding(
                war_name=name,
                war_name_zh=detail.get("name_zh"),
                attackers=list(detail.get("attackers") or []),
                defenders=list(detail.get("defenders") or []),
            )
            by_war[name] = standing

        if detail.get("name_zh"):
            standing.war_name_zh = detail["name_zh"]
        if detail.get("attackers"):
            standing.attackers = list(detail["attackers"])
        if detail.get("defenders"):
            standing.defenders = list(detail["defenders"])
        if detail.get("war_goal_type"):
            standing.war_goal_type = detail["war_goal_type"]
        if detail.get("casus_belli"):
            standing.casus_belli = detail["casus_belli"]
        if detail.get("war_goal_province") is not None:
            standing.war_goal_province = detail["war_goal_province"]
        if detail.get("occupied_provinces") is not None:
            standing.occupied_provinces = detail["occupied_provinces"]
        if detail.get("major_battles"):
            standing.major_battles = list(detail["major_battles"])
        if detail.get("player_ticking_warscore") is not None:
            try:
                standing.ticking_score = float(detail["player_ticking_warscore"])
            except (TypeError, ValueError):
                pass

        if score is not None:
            if e.kind == "war_score_changed" and detail.get("from") is not None:
                try:
                    standing.score_from = float(detail["from"])
                except (TypeError, ValueError):
                    pass
            standing.player_score = score
            standing.score_known = True
            standing.tier = classify_warscore(score)

    standings = list(by_war.values())
    for s in standings:
        if s.score_known:
            s.tier = classify_warscore(s.player_score)
        else:
            s.tier = "unknown"
    return WarAssessment(standings=standings)


def war_guidance_lines(assessment: WarAssessment, *, country_label=None) -> list[str]:
    """供 brief / 军师遵守的战分事实行。"""
    if not assessment.standings:
        return ["本区间无玩家参与的可稽战争，或档内未解析到战争分数。"]
    lines: list[str] = []
    for s in assessment.standings:
        wlabel = s.war_name_zh or s.war_name
        if s.score_known:
            lines.append(
                f"「{wlabel}」玩家总战分 {s.player_score:+.0f} → tier={s.tier}："
                f"{tier_phrase(s.tier, score=s.player_score)}"
            )
            if s.ticking_score is not None:
                lines.append(
                    f"「{wlabel}」{format_ticking_bonus(s.ticking_score)}；"
                    "系战争目标达成程度 bonus，主展示仍用总战分"
                )
        else:
            lines.append(f"「{wlabel}」档内未解析到玩家战分 → tier=unknown")
    lines.append(
        "硬性：主展示总战分；战争目标加分仅作目标达成程度附注（成稿写「战争目标加分 ±N」，勿加约±25范围注解）；"
        "战分显著为正（≥50）须写优势在握/基本打赢；"
        "仅在 |总战分| 较低（胶着）时才写胜负未定；"
        "禁止无战分依据的「尘埃未定」。"
        "有具体总战分时禁止写「战分未知」「不作胜负判断」。"
        "成稿只正面写战争目标加分，勿写元注释免责声明或约±25范围注解。"
    )
    return lines


# 成稿禁止的无数据空话 / 套话 / 元注释口吻
BANNED_EMPTY_PHRASES = (
    "粮草",
    "补给线",
    "打通补给",
    "分数打实",
    "把这一仗的分数打实",
    "胜负尚在尘埃未定",
    "尘埃未定",
    "刀尚未收",
    "刀尚未入鞘",
    "下一页按战分",
    "按战分与编制事实推进",
    "下一页仍以 Diff 为准",
    "下一页看附庸",
    "非总战分",
    "不作胶着依据",
    "勿用其判断胶着",
    "约 -25～+25",
    "（约 -25～+25）",
    "约-25～+25",
    "（约-25～+25）",
    "约±25",
    "约 ±25",
)


def contains_banned_empty_phrase(text: str) -> bool:
    return any(p in text for p in BANNED_EMPTY_PHRASES)
