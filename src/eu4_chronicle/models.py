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


class WarState(BaseModel):
    name: str
    attackers: list[str] = Field(default_factory=list)
    defenders: list[str] = Field(default_factory=list)
    participants: list[WarParticipant] = Field(default_factory=list)


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
