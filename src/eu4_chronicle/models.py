"""共享领域模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Monarch(BaseModel):
    name: str = ""
    adm: int = 0
    dip: int = 0
    mil: int = 0


class CountryState(BaseModel):
    tag: str
    name: str = ""
    development: float = 0.0
    technology: dict[str, int] = Field(default_factory=dict)
    religion: str = ""
    government_rank: int = 1
    manpower: float = 0.0
    max_manpower: float = 0.0
    army_size: float = 0.0
    navy_size: float = 0.0
    prestige: float = 0.0
    stability: int = 0
    monarch: Monarch | None = None
    allies: list[str] = Field(default_factory=list)
    rivals: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)
    cores: list[int] = Field(default_factory=list)
    owned_provinces: list[int] = Field(default_factory=list)
    opinion_of: dict[str, float] = Field(default_factory=dict)
    aggressive_expansion: dict[str, float] = Field(default_factory=dict)


class WarParticipant(BaseModel):
    tag: str
    side: Literal["attackers", "defenders"]
    warscore: float = 0.0
    # 档内显式战分（warscore / war_score / 有符号 value）；贡献度另存 contribution。
    # 默认 True 以兼容手工构造；解析贡献度-only 时显式置 False。
    warscore_known: bool = True
    contribution: float | None = None


class WarBattle(BaseModel):
    name: str = ""
    date: str = ""
    location: int | None = None
    attacker_won: bool | None = None
    attacker_tag: str | None = None
    defender_tag: str | None = None
    attacker_losses: float | None = None
    defender_losses: float | None = None


# 战争目标 ticking 上限（defines.lua WARGOAL_MAX_BONUS）
WARGOAL_TICKING_MAX = 25.0


class WarState(BaseModel):
    name: str
    attackers: list[str] = Field(default_factory=list)
    defenders: list[str] = Field(default_factory=list)
    participants: list[WarParticipant] = Field(default_factory=list)
    # 真档原始键
    attacker_score: float | None = None  # 攻方侧 score → ticking（勿当总战分）
    defender_score: float | None = None  # 守方侧 score；无 quarter 时可读作总战分（Osallek）
    last_warscore_quarter: float | None = None  # 真档钉死：主展示总战分（季度快照）
    last_warscore_year: float | None = None  # 年快照；quarter 缺失时回退
    # 解析后：主展示用总战分；ticking 另存，不得当总战分
    total_attacker_score: float | None = None
    ticking_attacker_score: float | None = None
    total_score_source: str | None = None
    ticking_score_source: str | None = None
    # 块内一切含 score/warscore/ticking 的原始数值，便于 dump / verbose
    raw_score_fields: dict[str, float] = Field(default_factory=dict)
    war_goal_type: str | None = None
    casus_belli: str | None = None
    war_goal_province: int | None = None
    war_goal_tag: str | None = None
    occupied_provinces: int | None = None
    battles: list[WarBattle] = Field(default_factory=list)

    def score_for(self, tag: str) -> float | None:
        """玩家/国家视角**总**战争分数（非 ticking）。"""
        total = self.total_attacker_score
        if total is not None:
            if tag in self.attackers:
                return float(total)
            if tag in self.defenders:
                return -float(total)
        # 未跑 resolve 时的回退：优先季度快照；勿用 attacker_score
        quarter = self.last_warscore_quarter
        if quarter is not None:
            if tag in self.attackers:
                return float(quarter)
            if tag in self.defenders:
                return -float(quarter)
        year = self.last_warscore_year
        if year is not None:
            if tag in self.attackers:
                return float(year)
            if tag in self.defenders:
                return -float(year)
        if tag in self.attackers:
            if self.defender_score is not None:
                return -float(self.defender_score)
        elif tag in self.defenders:
            if self.defender_score is not None:
                return float(self.defender_score)
        for p in self.participants:
            if p.tag == tag and p.warscore_known and abs(p.warscore) > 1e-6:
                return float(p.warscore)
        return None

    def ticking_for(self, tag: str) -> float | None:
        """玩家视角战争目标 ticking；与总战分分离。"""
        tick = self.ticking_attacker_score
        if tick is None:
            return None
        if tag in self.attackers:
            return float(tick)
        if tag in self.defenders:
            return -float(tick)
        return None

    def resolve_total_and_ticking(self) -> None:
        """拆出 UI 总战分与 ticking。

        真档钉死（Teutonic Conquest of Naklo，玩家攻方 TEU）：
        - 总战分：优先 ``last_warscore_quarter``（攻方为正）。可能是季度快照，
          与 UI 实时值略有偏差（例：档内 64 vs UI ~68）。
        - ticking：``attacker_score``（攻方）或相应侧 score；**禁止**当总战分。
        - ``participants.value`` 为贡献度；``war_score≈0`` 不作 UI 总战分。
        - quarter 缺失时回退：``last_warscore_year`` → 非零参战国 war_score →
          Osallek ``defender_score``（攻方取负）。永不回退到 ``attacker_score``。
        """
        raw = self.raw_score_fields

        def _raw(key: str) -> float | None:
            if key in raw:
                return float(raw[key])
            return None

        quarter = self.last_warscore_quarter
        if quarter is None:
            quarter = _raw("last_warscore_quarter")
            if quarter is not None:
                self.last_warscore_quarter = quarter
        year = self.last_warscore_year
        if year is None:
            year = _raw("last_warscore_year")
            if year is not None:
                self.last_warscore_year = year

        # 非零参战国显式战分（攻方视角）；忽略 ≈0（真档全员 war_score=0）
        part_cands: list[tuple[str, float]] = []
        for p in self.participants:
            if not p.warscore_known or abs(p.warscore) <= 1e-6:
                continue
            if p.tag in self.attackers:
                part_cands.append((f"participants.{p.tag}.war_score", float(p.warscore)))
            elif p.tag in self.defenders:
                part_cands.append((f"participants.{p.tag}.war_score", -float(p.warscore)))

        total_src: str | None = None
        total_val: float | None = None

        if quarter is not None:
            total_src, total_val = "last_warscore_quarter", float(quarter)
        elif year is not None:
            total_src, total_val = "last_warscore_year", float(year)
        elif part_cands:
            total_src, total_val = max(part_cands, key=lambda x: abs(x[1]))
        elif self.defender_score is not None:
            # Osallek：仅有守方侧战争级分时作总战分（攻方视角取负）
            total_src, total_val = "defender_score", -float(self.defender_score)
        elif self.raw_score_fields:
            skip = {
                "attacker_score",
                "defender_score",
                "war_direction_quarter",
                "war_direction_year",
                "last_warscore_quarter",
                "last_warscore_year",
                "stalled_years",
            }
            extras = [
                (k, float(v))
                for k, v in self.raw_score_fields.items()
                if k not in skip
                and "contribution" not in k
                and not k.endswith(".value")
                and "participants" not in k
                and abs(float(v)) > 1e-6
            ]
            if extras:
                total_src, total_val = max(extras, key=lambda x: abs(x[1]))

        # ticking：攻方 attacker_score；无则用相应侧 defender_score（攻方视角取负），
        # 且不得与已选总战分同源。
        ticking_src: str | None = None
        ticking_val: float | None = None
        if self.attacker_score is not None:
            ticking_src, ticking_val = "attacker_score", float(self.attacker_score)
        elif (
            self.defender_score is not None
            and total_src != "defender_score"
            and abs(float(self.defender_score)) <= WARGOAL_TICKING_MAX + 1e-6
        ):
            ticking_src, ticking_val = "defender_score", -float(self.defender_score)

        # 若 ticking 与 total 同值同源，只保留总战分
        if (
            ticking_val is not None
            and total_val is not None
            and abs(ticking_val - total_val) < 1e-6
            and ticking_src == total_src
        ):
            ticking_src, ticking_val = None, None

        self.total_attacker_score = total_val
        self.total_score_source = total_src
        self.ticking_attacker_score = ticking_val
        self.ticking_score_source = ticking_src


class GameState(BaseModel):
    date: str = ""
    player: str = ""
    ironman: bool = False
    countries: dict[str, CountryState] = Field(default_factory=dict)
    wars: list[WarState] = Field(default_factory=list)
    province_names: dict[int, str] = Field(default_factory=dict)
    source_path: str | None = None
    raw_meta: dict[str, Any] = Field(default_factory=dict)


EventKind = Literal[
    "date_changed",
    "province_gained",
    "province_lost",
    "core_gained",
    "core_lost",
    "alliance_formed",
    "alliance_broken",
    "rival_set",
    "rival_cleared",
    "war_started",
    "war_ended",
    "war_score_changed",
    "development_changed",
    "tech_changed",
    "war_tech_compare",
    "religion_changed",
    "monarch_changed",
    "manpower_changed",
    "army_changed",
    "navy_changed",
    "ae_changed",
    "opinion_changed",
    "subject_changed",
    "stability_changed",
    "prestige_changed",
]


class DiffEvent(BaseModel):
    kind: EventKind
    tag: str | None = None
    other_tag: str | None = None
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)


class DiffResult(BaseModel):
    prev_date: str
    curr_date: str
    player: str
    events: list[DiffEvent] = Field(default_factory=list)
    raw_event_count: int | None = None
    filtered: bool = True

    def events_for(self, *kinds: EventKind) -> list[DiffEvent]:
        wanted = set(kinds)
        return [e for e in self.events if e.kind in wanted]


class AgentSection(BaseModel):
    role: Literal["historian", "strategist", "diplomat", "editor"]
    title: str
    content: str
    mock: bool = False


class ChronicleReport(BaseModel):
    title: str
    prev_date: str
    curr_date: str
    player: str
    mode: str
    sections: list[AgentSection]
    final_markdown: str
    event_count: int = 0
