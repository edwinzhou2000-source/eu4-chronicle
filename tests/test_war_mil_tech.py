"""军科代差：无对手科技不瞎评；TEU4/POL3 必须写对。"""

from __future__ import annotations

from eu4_game_report.ae import assess_player_ae
from eu4_game_report.agents import (
    _mock_editor,
    _mock_narrative_paragraph,
    _mock_war_section,
    make_brief,
)
from eu4_game_report.agents.prompts import (
    EDITOR_SYSTEM,
    HISTORIAN_SYSTEM,
    STRATEGIST_SYSTEM,
    TECH_COMPARE_FORBIDDEN_WITHOUT_BOTH,
)
from eu4_game_report.diff import diff_states
from eu4_game_report.filter import enrich_war_tech_snapshots, filter_diff, is_early_game_date
from eu4_game_report.models import (
    CountryState,
    DiffEvent,
    DiffResult,
    GameState,
    WarParticipant,
    WarState,
)
from eu4_game_report.names import NameResolver
from eu4_game_report.parser import parse_save
from pathlib import Path

SAMPLES = Path(__file__).resolve().parents[1] / "samples"

FORBIDDEN_WITHOUT_BOTH = TECH_COMPARE_FORBIDDEN_WITHOUT_BOTH


def _teu_pol_states(*, teu_mil: int = 4, pol_mil: int = 3) -> tuple[GameState, GameState]:
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
            ),
            "POL": CountryState(
                tag="POL",
                name="Poland",
                technology={"adm_tech": 3, "dip_tech": 3, "mil_tech": pol_mil},
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
            ),
            "POL": CountryState(
                tag="POL",
                name="Poland",
                technology={"adm_tech": 3, "dip_tech": 3, "mil_tech": pol_mil},
            ),
        },
        wars=[war],
    )
    return prev, curr


def test_is_early_game_date():
    assert is_early_game_date("1447.1.1")
    assert is_early_game_date("1499.12.31")
    assert not is_early_game_date("1500.1.1")
    assert not is_early_game_date("1600.1.1")


def test_enrich_injects_teu4_vs_pol3():
    prev, curr = _teu_pol_states(teu_mil=4, pol_mil=3)
    raw = diff_states(prev, curr)
    filtered = filter_diff(raw, prev=prev, curr=curr, include_global=False)
    compares = [e for e in filtered.events if e.kind == "war_tech_compare"]
    assert len(compares) == 1
    e = compares[0]
    assert e.detail["player_mil"] == 4
    assert e.detail["foe_mil"] == 3
    assert e.detail["mil_gap"] == 1
    assert e.detail["foe"] == "POL"
    assert e.detail["early_game"] is True
    assert "4" in e.summary and "3" in e.summary
    assert "轻代差" in e.summary
    # 扩展后摘要以「军力对比」为题，仍含军科数字
    assert "军力对比" in e.summary or "军事科技" in e.summary
    assert "军科" in e.summary or "4" in e.summary


def test_enrich_skips_when_foe_mil_missing():
    curr = GameState(
        date="1454.1.1",
        player="TEU",
        countries={
            "TEU": CountryState(
                tag="TEU",
                technology={"mil_tech": 4},
            ),
            # POL 无 technology → 不注入对比
            "POL": CountryState(tag="POL"),
        },
        wars=[
            WarState(
                name="Teutonic Conquest of Naklo",
                attackers=["TEU"],
                defenders=["POL"],
            )
        ],
    )
    events = enrich_war_tech_snapshots([], curr=curr, player="TEU")
    assert not any(e.kind == "war_tech_compare" for e in events)


def test_mock_without_opponent_tech_no_false_parity():
    """仅玩家 tech_changed、无 war_tech_compare → 成稿禁代差/同档瞎评。"""
    names = NameResolver()
    diff = DiffResult(
        prev_date="1447.1.1",
        curr_date="1454.1.1",
        player="TEU",
        events=[
            DiffEvent(
                kind="tech_changed",
                tag="TEU",
                summary="TEU mil_tech 3 → 4",
                detail={"tech": "mil_tech", "from": 3, "to": 4},
            ),
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
        for phrase in FORBIDDEN_WITHOUT_BOTH:
            assert phrase not in text, f"不应出现「{phrase}」于: {text[:120]}"
    assert "勿写入成稿" in brief or "禁止套话" in brief
    assert "本 Diff 无双方军科对比数字" not in brief
    # 玩家升级事实仍可写
    assert "军事科技" in narrative or "3" in narrative


def test_mock_teu4_pol3_must_state_lead_not_parity():
    prev, curr = _teu_pol_states(teu_mil=4, pol_mil=3)
    raw = diff_states(prev, curr)
    filtered = filter_diff(raw, prev=prev, curr=curr)
    names = NameResolver.from_states(prev, curr)
    readable = names.rewrite_diff(filtered)
    ae = assess_player_ae(readable, country_label=names.country)

    narrative = _mock_narrative_paragraph(readable, names, ae)
    war = _mock_war_section(readable, names, ae, heading=False)
    editor = _mock_editor(readable, names, ae)
    brief = make_brief(readable, names=names, ae=ae)

    # 须体现 4 vs 3 / 领先 / 轻代差
    blob = "\n".join([narrative, war, editor, brief])
    assert "4" in blob and "3" in blob
    assert "波兰" in blob or "POL" in blob
    assert "轻代差" in blob or "领先一级" in blob or "领先 1" in blob
    for phrase in ("代差尚未拉开", "同档起步", "无代差"):
        assert phrase not in narrative
        assert phrase not in war
        assert phrase not in editor


def test_prompts_forbid_tech_compare_without_numbers():
    # 军科对比归战局/主编；史官只禁止展开，不写对比细则
    assert "战局" in HISTORIAN_SYSTEM or "禁止在叙事展开" in HISTORIAN_SYSTEM
    for sys in (STRATEGIST_SYSTEM, EDITOR_SYSTEM):
        assert "代差" in sys or "军科" in sys
        assert "双方" in sys or "无双方" in sys or "双方军科" in sys


def test_sample_byz_injects_war_tech_vs_tur():
    prev = parse_save(SAMPLES / "byz_1444.eu4")
    curr = parse_save(SAMPLES / "byz_1453.eu4")
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    compares = [e for e in filtered.events if e.kind == "war_tech_compare"]
    assert compares
    e = compares[0]
    assert e.detail["foe"] == "TUR"
    # 1453：BYZ mil 4 vs TUR mil 4 → 同档
    assert e.detail["player_mil"] == 4
    assert e.detail["foe_mil"] == 4
    assert e.detail["mil_gap"] == 0
