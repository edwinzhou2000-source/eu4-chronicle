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


class WarState(BaseModel):
    name: str
    attackers: list[str] = Field(default_factory=list)
    defenders: list[str] = Field(default_factory=list)
    participants: list[WarParticipant] = Field(default_factory=list)
    # 真档战争级战分（Osallek / Clausewitz：defender_score / attacker_score）
    attacker_score: float | None = None
    defender_score: float | None = None
    war_goal_type: str | None = None
    casus_belli: str | None = None
    war_goal_province: int | None = None
    war_goal_tag: str | None = None
    occupied_provinces: int | None = None
    battles: list[WarBattle] = Field(default_factory=list)

    def score_for(self, tag: str) -> float | None:
        """玩家/国家视角战争分数；优先战争级字段，其次参战国显式战分。"""
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
