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
    ended: bool = False
    source: str | None = None  # previous_war | active_war | None
    # previous_war outcome：玩家和约胜负（优先于媾和前战分快照）
    outcome: int | None = None
    player_won: bool | None = None
    peace_draw: bool = False
    ended_date: str | None = None


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
        # 进行中战争优先；已结束则优先和约取胜，再看会战数
        active = [s for s in self.standings if not s.ended]
        pool = active or self.standings
        return max(
            pool,
            key=lambda s: (
                0 if s.ended else 1,
                2 if s.player_won is True else (1 if s.player_won is None and s.ended else 0),
                1 if s.score_known else 0,
                abs(s.player_score) if s.score_known else 0,
                len(s.major_battles or []),
            ),
        )


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
    if tier == "victory":
        return "和约取胜" + (f"（战分 {score:+.0f}）" if score is not None else "")
    if tier == "defeat":
        return "和约落败" + (f"（战分 {score:+.0f}）" if score is not None else "")
    if tier == "draw":
        return "白和/平局收场"
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

        if e.kind == "war_ended":
            standing.ended = True
        if detail.get("source"):
            standing.source = str(detail["source"])
        if detail.get("outcome") is not None:
            try:
                standing.outcome = int(detail["outcome"])
            except (TypeError, ValueError):
                pass
        if "player_won" in detail:
            pw = detail.get("player_won")
            standing.player_won = bool(pw) if pw is not None else None
        if detail.get("peace_draw"):
            standing.peace_draw = True
        if detail.get("ended_date"):
            standing.ended_date = str(detail["ended_date"])
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
        # 已结束战争：战争目标加分/实时 ticking 易误导，不写入
        if not standing.ended and detail.get("player_ticking_warscore") is not None:
            try:
                standing.ticking_score = float(detail["player_ticking_warscore"])
            except (TypeError, ValueError):
                pass

        # previous_war 归档分与 outcome 矛盾时 detail.score_unreliable=True，勿写入
        if score is not None and not detail.get("score_unreliable"):
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
        if s.ended and (s.player_won is not None or s.peace_draw or s.outcome is not None):
            # 已结束：胜负看 outcome，不用媾和前战分快照分档
            if s.peace_draw or s.outcome == 1:
                s.tier = "draw"
            elif s.player_won is True:
                s.tier = "victory"
            elif s.player_won is False:
                s.tier = "defeat"
            elif s.score_known:
                s.tier = classify_warscore(s.player_score)
            else:
                s.tier = "unknown"
        elif s.score_known:
            s.tier = classify_warscore(s.player_score)
        else:
            s.tier = "unknown"
    return WarAssessment(standings=standings)


def war_guidance_lines(assessment: WarAssessment, *, country_label=None) -> list[str]:
    """供 brief / 军师遵守的战分事实行。"""
    if not assessment.standings:
        return [
            "本区间无玩家参与的可稽战争（active_war / previous_war 均未检出玩家战事）。"
            "战局要点仅用一两句说明即可；禁止用陆军编制、军科、人力等和平期数据充数。"
        ]
    lines: list[str] = []
    for s in assessment.standings:
        wlabel = s.war_name_zh or s.war_name
        side_bits: list[str] = []
        if s.attackers:
            side_bits.append(f"攻方 {', '.join(s.attackers)}")
        if s.defenders:
            side_bits.append(f"守方 {', '.join(s.defenders)}")
        side = "；".join(side_bits)
        if s.ended and (s.player_won is not None or s.peace_draw or s.outcome is not None):
            if s.peace_draw or s.outcome == 1:
                result = "白和/平局"
            elif s.player_won is True:
                result = "玩家和约取胜"
            elif s.player_won is False:
                result = "玩家和约落败"
            else:
                result = f"outcome={s.outcome}"
            score_bit = ""
            if s.score_known:
                score_bit = f"；可靠战分 {s.player_score:+.0f}（来自消失前 active 或符号一致的归档分）"
            else:
                score_bit = (
                    "；档内无可靠总战分（previous_war 的 last_warscore 与 outcome 矛盾时已丢弃，"
                    "**禁止**引用负快照或写战分落后/胶着）"
                )
            date_bit = f"；媾和日 {s.ended_date}" if s.ended_date else ""
            lines.append(
                f"「{wlabel}」本区间内已结束 → {result}{score_bit}{date_bit}"
                + (f"；{side}" if side else "")
            )
        elif s.score_known:
            lines.append(
                f"「{wlabel}」玩家总战分 {s.player_score:+.0f} → tier={s.tier}："
                f"{tier_phrase(s.tier, score=s.player_score)}"
                + (f"；{side}" if side else "")
            )
            if s.ticking_score is not None:
                lines.append(
                    f"「{wlabel}」{format_ticking_bonus(s.ticking_score)}；"
                    "系战争目标达成程度 bonus，主展示仍用总战分"
                )
        else:
            status = "本区间内已结束" if s.ended else "进行中"
            battle_n = len(s.major_battles or [])
            battle_bit = f"；会战可点名至多 1 场" if battle_n else ""
            lines.append(
                f"「{wlabel}」{status}，档内无总战分 → tier=unknown；"
                f"须写战争名与参战结构（{side or '参战方见 Diff'}）{battle_bit}；"
                "禁止假称「无可稽战争」；禁止堆砌占领数=0、原始 CB 键、多场战役损兵明细、编制充数"
            )
    lines.append(
        "硬性：进行中战争主展示总战分；战争目标加分仅作目标达成程度附注；"
        "战分显著为正（≥50）须写优势在握/基本打赢；"
        "仅在 |总战分| 较低（胶着）时才写胜负未定；"
        "禁止无战分依据的「尘埃未定」。"
        "已结束战争（previous_war）：胜负以 outcome 为准（2=攻方胜 3=守方胜 1=平局）；"
        "归档 last_warscore 与 outcome 符号矛盾时已标不可靠——**禁止引用**；"
        "仅 brief 给出的可靠战分可写。有 war_* 时必须点名战争，禁止「无可稽战争」套话。"
        "硬性：war_ended = 本区间（两档之间）内发生并打完的战争；"
        "禁止写成「本区间无进行中战争/本区间无战事」——那只是后期档保存当天无 active_war。"
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
