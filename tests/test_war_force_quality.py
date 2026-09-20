"""交战军力：数量 + discipline/land_morale；禁无据体量/质量对比。"""

from __future__ import annotations

from pathlib import Path

from eu4_chronicle.ae import assess_player_ae
from eu4_chronicle.agents import (
    _mock_editor,
    _mock_narrative_paragraph,
    _mock_war_section,
    make_brief,
)
from eu4_chronicle.agents.prompts import (
    EDITOR_SYSTEM,
    FORCE_COMPARE_FORBIDDEN_WITHOUT_BOTH,
    HISTORIAN_SYSTEM,
    STRATEGIST_SYSTEM,
)
from eu4_chronicle.diff import diff_states
from eu4_chronicle.filter import enrich_war_tech_snapshots, filter_diff
from eu4_chronicle.models import (
    CountryState,
    DiffEvent,
    DiffResult,
    GameState,
    WarParticipant,
    WarState,
)
from eu4_chronicle.names import NameResolver
from eu4_chronicle.parser import parse_save

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
FORCE_FORBIDDEN = FORCE_COMPARE_FORBIDDEN_WITHOUT_BOTH


def _teu_pol_force_states(
    *,
    teu_mil: int = 4,
    pol_mil: int = 3,
    teu_army: float = 18,
    pol_army: float = 28,
    teu_man: float = 12,
    pol_man: float = 22,
    teu_disc: float | None = 1.05,
    pol_disc: float | None = 1.0,
    teu_morale: float | None = 3.2,
    pol_morale: float | None = 3.0,
) -> tuple[GameState, GameState]:
    war = WarState(
        name="Teutonic Conquest of Naklo",
        attackers=["TEU"],
        defenders=["POL"],
        participants=[
            WarParticipant(tag="TEU", side="attackers", warscore=68),
            WarParticipant(tag="POL", side="defenders", warscore=-68),
        ],
        last_warscore_quarter=68.0,
        attacker_score=18.0,
    )
    prev = GameState(
        date="1447.1.1",
        player="TEU",
        countries={
            "TEU": CountryState(
                tag="TEU",
                name="Teutonic Order",
                technology={"adm_tech": 3, "dip_tech": 3, "mil_tech": teu_mil - 1},
                army_size=teu_army,
                manpower=teu_man,
                max_manpower=teu_man + 5,
                discipline=teu_disc,
                land_morale=teu_morale,
            ),
            "POL": CountryState(
                tag="POL",
                name="Poland",
                technology={"adm_tech": 3, "dip_tech": 3, "mil_tech": pol_mil},
                army_size=pol_army,
                manpower=pol_man,
                max_manpower=pol_man + 8,
                discipline=pol_disc,
                land_morale=pol_morale,
            ),
        },
        wars=[war],
    )
    curr = GameState(
        date="1454.1.1",
        player="TEU",
        countries={
            "TEU": CountryState(
                tag="TEU",
                name="Teutonic Order",
                technology={"adm_tech": 3, "dip_tech": 3, "mil_tech": teu_mil},
                army_size=teu_army,
                manpower=teu_man,
                max_manpower=teu_man + 5,
                discipline=teu_disc,
                land_morale=teu_morale,
            ),
            "POL": CountryState(
                tag="POL",
                name="Poland",
                technology={"adm_tech": 3, "dip_tech": 3, "mil_tech": pol_mil},
                army_size=pol_army,
                manpower=pol_man,
                max_manpower=pol_man + 8,
                discipline=pol_disc,
                land_morale=pol_morale,
            ),
        },
        wars=[war],
    )
    return prev, curr


def test_parse_discipline_land_morale_from_sample():
    curr = parse_save(SAMPLES / "byz_1453.eu4")
    byz = curr.countries["BYZ"]
    tur = curr.countries["TUR"]
    assert byz.discipline == 1.0
    assert byz.land_morale == 2.8
    assert tur.discipline == 1.1
    assert tur.land_morale == 3.8


def test_parse_omits_missing_quality():
    """样例小国无纪律/士气 → None，禁止当成 0。"""
    curr = parse_save(SAMPLES / "byz_1453.eu4")
    wal = curr.countries["WAL"]
    assert wal.discipline is None
    assert wal.land_morale is None


def test_enrich_injects_army_manpower_discipline_morale():
    prev, curr = _teu_pol_force_states()
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    compares = [e for e in filtered.events if e.kind == "war_tech_compare"]
    assert len(compares) == 1
    e = compares[0]
    assert e.detail["player_mil"] == 4
    assert e.detail["foe_mil"] == 3
    assert e.detail["has_both_army"] is True
    assert e.detail["has_both_manpower"] is True
    assert e.detail["has_both_discipline"] is True
    assert e.detail["has_both_land_morale"] is True
    pf = e.detail["player_force"]
    ff = e.detail["foe_force"]
    assert pf["army_size"] == 18
    assert ff["army_size"] == 28
    assert pf["discipline"] == 1.05
    assert ff["land_morale"] == 3.0
    assert "军力对比" in e.summary
    assert "陆军" in e.summary
    assert "纪律" in e.summary
    assert "士气" in e.summary


def test_enrich_omits_discipline_when_only_one_side():
    prev, curr = _teu_pol_force_states(pol_disc=None, pol_morale=None)
    events = enrich_war_tech_snapshots([], curr=curr, player="TEU")
    e = next(x for x in events if x.kind == "war_tech_compare")
    assert e.detail["has_both_discipline"] is False
    assert e.detail["has_both_land_morale"] is False
    assert "discipline" not in (e.detail["foe_force"] or {})
    # summary 不应写纪律/士气对比（仅玩家有也不写该维）
    assert "纪律" not in e.summary
    assert "士气" not in e.summary


def test_mock_without_opponent_army_no_force_boasting():
    """无 war_tech_compare / 无双方兵力 → 禁空口体量句。"""
    names = NameResolver()
    diff = DiffResult(
        prev_date="1447.1.1",
        curr_date="1454.1.1",
        player="TEU",
        events=[
            DiffEvent(
                kind="war_score_changed",
                tag="TEU",
                summary="战争分数",
                detail={
                    "war": "Teutonic Conquest of Naklo",
                    "name": "Teutonic Conquest of Naklo",
                    "from": 40,
                    "to": 68,
                    "attackers": ["TEU"],
                    "defenders": ["POL"],
                    "participants": ["TEU", "POL"],
                    "player_warscore": 68,
                },
            ),
        ],
    )
    ae = assess_player_ae(diff, country_label=names.country)
    narrative = _mock_narrative_paragraph(diff, names, ae)
    war = _mock_war_section(diff, names, ae, heading=False)
    editor = _mock_editor(diff, names, ae)
    brief = make_brief(diff, names=names, ae=ae)

    for text in (narrative, war, editor):
        for phrase in FORCE_FORBIDDEN:
            assert phrase not in text, f"不应出现「{phrase}」于: {text[:160]}"
    assert "交战军力" in brief
    assert "无交战军力" in brief or "禁止" in brief


def test_mock_with_teu_pol_force_states_numbers():
    prev, curr = _teu_pol_force_states()
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    names = NameResolver.from_states(prev, curr)
    readable = names.rewrite_diff(filtered)
    ae = assess_player_ae(readable, country_label=names.country)

    narrative = _mock_narrative_paragraph(readable, names, ae)
    war = _mock_war_section(readable, names, ae, heading=False)
    editor = _mock_editor(readable, names, ae)
    brief = make_brief(readable, names=names, ae=ae)
    blob = "\n".join([narrative, war, editor, brief])

    assert "18" in blob and "28" in blob  # 陆军
    assert "4" in blob and "3" in blob  # 军科
    assert "纪律" in blob or "1.05" in blob
    assert "士气" in blob or "3.2" in blob
    assert "轻代差" in blob or "领先一级" in blob or "领先 1" in blob
    # 成稿正文勿写传统/职业度（brief 禁词说明可提及）
    for text in (narrative, war, editor):
        for phrase in ("军队传统", "海军传统", "职业度", "army_tradition", "army_professionalism"):
            assert phrase not in text


def test_prompts_forbid_force_compare_without_numbers():
    for sys in (HISTORIAN_SYSTEM, STRATEGIST_SYSTEM, EDITOR_SYSTEM):
        assert "同维" in sys or "体量" in sys or "军力" in sys
        assert "传统" in sys or "职业度" in sys


def test_sample_byz_force_vs_tur():
    prev = parse_save(SAMPLES / "byz_1444.eu4")
    curr = parse_save(SAMPLES / "byz_1453.eu4")
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    compares = [e for e in filtered.events if e.kind == "war_tech_compare"]
    assert compares
    e = compares[0]
    assert e.detail["foe"] == "TUR"
    assert e.detail["has_both_army"] is True
    assert e.detail["player_force"]["army_size"] == 10
    assert e.detail["foe_force"]["army_size"] == 32
    assert e.detail["has_both_discipline"] is True
    assert e.detail["has_both_land_morale"] is True
    assert "陆军" in e.summary
    assert "纪律" in e.summary
