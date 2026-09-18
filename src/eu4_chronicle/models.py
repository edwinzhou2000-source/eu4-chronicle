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
    # 真档原始键（Osallek：通常为总战分的攻/守视角，未必同存）
    attacker_score: float | None = None
    defender_score: float | None = None
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
        # 兼容：未跑 resolve 时回退 Osallek 单字段语义
        if tag in self.attackers:
            if self.defender_score is not None:
                return -float(self.defender_score)
            if self.attacker_score is not None:
                return float(self.attacker_score)
        elif tag in self.defenders:
            if self.defender_score is not None:
                return float(self.defender_score)
            if self.attacker_score is not None:
                return -float(self.attacker_score)
        for p in self.participants:
            if p.tag == tag and p.warscore_known:
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

        依据（勿再用「两键里绝对值更大的当总战分」——真档上该启发式失败）：
        - Osallek ActiveWar.getScore：优先 defender_score（攻方视角取负），否则
          attacker_score；二者是同一总战分的视角，不是 total vs ticking。
        - 参战国显式 war_score / warscore（eu4-war-explorer 提及 1.38+）若存在且
          |值| 明显大于战争级 ≤25 的字段，则显式战分=总战分，战争级小值=ticking。
        - |值|>25 的字段不可能是 ticking（WARGOAL_MAX_BONUS=25）。
        - participants.value 仍为贡献度，不作 UI 总战分。
        """
        part_cands: list[tuple[str, float]] = []
        for p in self.participants:
            if not p.warscore_known:
                continue
            if p.tag in self.attackers:
                part_cands.append((f"participants.{p.tag}.war_score", float(p.warscore)))
            elif p.tag in self.defenders:
                part_cands.append((f"participants.{p.tag}.war_score", -float(p.warscore)))

        # Osallek 战争级总战分（攻方视角）
        osallek_src: str | None = None
        osallek_val: float | None = None
        if self.defender_score is not None:
            osallek_src, osallek_val = "defender_score", -float(self.defender_score)
        elif self.attacker_score is not None:
            osallek_src, osallek_val = "attacker_score", float(self.attacker_score)

        # 另一战争级键（若同存且与 Osallek 所选不同）
        other_war: tuple[str, float] | None = None
        if self.attacker_score is not None and osallek_src != "attacker_score":
            other_war = ("attacker_score", float(self.attacker_score))
        elif self.defender_score is not None and osallek_src != "defender_score":
            other_war = ("defender_score", -float(self.defender_score))

        total_src: str | None = None
        total_val: float | None = None
        ticking_src: str | None = None
        ticking_val: float | None = None

        def _pick_largest_participant() -> tuple[str, float] | None:
            if not part_cands:
                return None
            return max(part_cands, key=lambda x: abs(x[1]))

        # 1) 参战国显式战分 |v| 更大，且战争级 Osallek |v|≤25 → 显式=总，战争级=ticking
        best_part = _pick_largest_participant()
        if (
            best_part is not None
            and osallek_val is not None
            and abs(osallek_val) <= WARGOAL_TICKING_MAX + 1e-6
            and abs(best_part[1]) > abs(osallek_val) + 1e-6
        ):
            total_src, total_val = best_part
            ticking_src, ticking_val = osallek_src, osallek_val
        # 2) 两战争级同存：|大|>25 且 |小|≤25 且量级不同 → 大=总、小=ticking
        #    （不靠「谁的绝对值更大」在两个 ≤25 或两个 >25 之间瞎猜）
        elif (
            osallek_val is not None
            and other_war is not None
            and abs(osallek_val - other_war[1]) > 1e-6
        ):
            a = (osallek_src or "", osallek_val)
            b = other_war
            big, small = (a, b) if abs(a[1]) >= abs(b[1]) else (b, a)
            if abs(big[1]) > WARGOAL_TICKING_MAX + 1e-6 and abs(small[1]) <= WARGOAL_TICKING_MAX + 1e-6:
                total_src, total_val = big
                ticking_src, ticking_val = small
            else:
                # 同量级或都 ≤25：信 Osallek，不把另一键当 ticking
                total_src, total_val = osallek_src, osallek_val
                if best_part is not None and abs(best_part[1]) > abs(total_val) + 1e-6:
                    # 参战国显式更大时仍可覆盖
                    if abs(total_val) <= WARGOAL_TICKING_MAX + 1e-6:
                        ticking_src, ticking_val = total_src, total_val
                    total_src, total_val = best_part
        # 3) 仅 Osallek 或仅参战国
        elif osallek_val is not None:
            total_src, total_val = osallek_src, osallek_val
            if (
                best_part is not None
                and abs(best_part[1]) > abs(total_val) + 1e-6
                and abs(total_val) <= WARGOAL_TICKING_MAX + 1e-6
            ):
                ticking_src, ticking_val = total_src, total_val
                total_src, total_val = best_part
        elif best_part is not None:
            total_src, total_val = best_part

        # 4) raw_score_fields 中其它 *score* 键（非贡献 value）作补充总战分
        if total_val is None and self.raw_score_fields:
            skip = {"attacker_score", "defender_score", "war_direction_quarter", "war_direction_year",
                    "last_warscore_quarter", "last_warscore_year", "stalled_years"}
            extras = [
                (k, v)
                for k, v in self.raw_score_fields.items()
                if k not in skip and "contribution" not in k and not k.endswith(".value")
            ]
            if extras:
                # 取 |v| 最大者；若像参战国战分则需已知攻守才能定向，这里只在无更好来源时用
                k, v = max(extras, key=lambda x: abs(x[1]))
                total_src, total_val = k, float(v)

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
