"""任务树：解析、Diff、本地化、成稿注入。"""

from __future__ import annotations

from pathlib import Path

from eu4_game_report.agents import make_brief, _mock_editor
from eu4_game_report.diff import diff_states
from eu4_game_report.filter import filter_diff
from eu4_game_report.localisation import (
    GameLocalisation,
    enrich_mission_diff,
    humanize_mission_id,
    is_garbled_loc,
    parse_localisation_yml,
)
from eu4_game_report.models import CountryState, DiffEvent, DiffResult, GameState
from eu4_game_report.names import NameResolver
from eu4_game_report.parser import parse_save_text


def _country(tag: str, missions: list[str], **kwargs) -> CountryState:
    return CountryState(tag=tag, completed_missions=list(missions), **kwargs)


def test_parse_completed_missions():
    text = """
    date="1449.12.1"
    player="TEU"
    countries={
      TEU={
        development=50
        completed_missions={
          "teu_seek_imperial_protection"
          "teu_handle_the_prussian_confederation"
        }
      }
    }
    """
    state = parse_save_text(text)
    assert state.player == "TEU"
    assert state.countries["TEU"].completed_missions == [
        "teu_seek_imperial_protection",
        "teu_handle_the_prussian_confederation",
    ]


def test_diff_missions_set_difference_same_tag():
    prev = GameState(
        date="1447.6.1",
        player="TEU",
        countries={
            "TEU": _country("TEU", ["teu_seek_imperial_protection"]),
        },
    )
    curr = GameState(
        date="1449.12.1",
        player="TEU",
        countries={
            "TEU": _country(
                "TEU",
                [
                    "teu_seek_imperial_protection",
                    "teu_handle_the_prussian_confederation",
                    "teu_livonian_alliance",
                ],
            ),
        },
    )
    raw = diff_states(prev, curr)
    completed = [e for e in raw.events if e.kind == "mission_completed"]
    ids = {e.detail["mission_id"] for e in completed}
    assert ids == {
        "teu_handle_the_prussian_confederation",
        "teu_livonian_alliance",
    }
    assert not any(e.kind == "player_tag_changed" for e in raw.events)
    assert not any(e.kind == "missions_lost" for e in raw.events)


def test_diff_missions_across_tag_change_retains_old():
    """成立新国家：旧完成仍在 curr 集合 → 不重复报；只报新增。"""
    prev = GameState(
        date="1445.8.2",
        player="HOL",
        countries={"HOL": _country("HOL", ["NYDD_HOL_a", "NYDD_HOL_b"])},
    )
    curr = GameState(
        date="1460.6.10",
        player="NE8",
        countries={
            "NE8": _country(
                "NE8",
                ["NYDD_HOL_a", "NYDD_HOL_b", "NYDD_NED_new"],
            ),
        },
    )
    raw = diff_states(prev, curr)
    assert any(e.kind == "player_tag_changed" for e in raw.events)
    completed = [e for e in raw.events if e.kind == "mission_completed"]
    assert [e.detail["mission_id"] for e in completed] == ["NYDD_NED_new"]


def test_diff_missions_lost_when_cleared():
    prev = GameState(
        date="a",
        player="TEU",
        countries={"TEU": _country("TEU", ["m1", "m2"])},
    )
    curr = GameState(
        date="b",
        player="TEU",
        countries={"TEU": _country("TEU", ["m3"])},
    )
    raw = diff_states(prev, curr)
    lost = next(e for e in raw.events if e.kind == "missions_lost")
    assert set(lost.detail["mission_ids"]) == {"m1", "m2"}
    assert [e.detail["mission_id"] for e in raw.events if e.kind == "mission_completed"] == [
        "m3"
    ]


def test_filter_drops_player_missions():
    """任务书小节已下线：默认过滤掉 mission_completed。"""
    prev = GameState(date="a", player="TEU", countries={"TEU": _country("TEU", [])})
    curr = GameState(
        date="b",
        player="TEU",
        countries={"TEU": _country("TEU", ["teu_x"])},
    )
    raw = diff_states(prev, curr)
    assert any(e.kind == "mission_completed" for e in raw.events)
    filtered = filter_diff(raw, prev=prev, curr=curr)
    assert not any(e.kind == "mission_completed" for e in filtered.events)


def test_garbled_loc_skipped():
    assert is_garbled_loc("\x10\x04Y\x10\x06t\x12Tw")
    assert not is_garbled_loc("Handle the Confederation")
    yml = """
l_english:
 garbled_title:0 "\x10\x04Y\x10\x06t"
 ok_title:0 "Handle the Confederation"
 ok_desc:0 "A long description about Prussia."
"""
    parsed = parse_localisation_yml(yml)
    assert "garbled_title" not in parsed
    assert parsed["ok_title"] == "Handle the Confederation"


def test_enrich_mission_diff_attaches_text():
    loc = GameLocalisation(
        entries={
            "teu_handle_the_prussian_confederation_title": "Handle the Confederation",
            "teu_handle_the_prussian_confederation_desc": "Following our defeat…",
        }
    )
    diff = DiffResult(
        prev_date="a",
        curr_date="b",
        player="TEU",
        events=[
            DiffEvent(
                kind="mission_completed",
                tag="TEU",
                summary="完成任务 teu_handle_the_prussian_confederation",
                detail={"mission_id": "teu_handle_the_prussian_confederation"},
            )
        ],
    )
    out = enrich_mission_diff(diff, loc)
    ev = out.events[0]
    assert ev.detail["loc_found"] is True
    assert ev.detail["title"] == "Handle the Confederation"
    assert "Following" in ev.detail["desc"]
    assert "已完成任务「Handle the Confederation」" in ev.summary
    assert ev.detail.get("player_choice_known") is False
    assert ev.detail.get("reward_events") == []


def test_enrich_mission_ignores_script_reward_events():
    """成稿路径不注入完成弹窗（即便传入 script_index）。"""
    from eu4_game_report.mission_scripts import MissionScriptIndex, RewardEventText

    class _Idx(MissionScriptIndex):
        def reward_events_for(self, mission_id, loc):  # type: ignore[override]
            return [
                RewardEventText(
                    event_id="flavor_teu.1",
                    title="The Prussian Confederation Revolts",
                    desc="Despite our best efforts...",
                    depth=0,
                )
            ]

    loc = GameLocalisation(
        entries={
            "teu_handle_the_prussian_confederation_title": "Handle the Confederation",
            "teu_handle_the_prussian_confederation_desc": "Following our defeat.",
        }
    )
    diff = DiffResult(
        prev_date="a",
        curr_date="b",
        player="TEU",
        events=[
            DiffEvent(
                kind="mission_completed",
                tag="TEU",
                summary="x",
                detail={"mission_id": "teu_handle_the_prussian_confederation"},
            )
        ],
    )
    out = enrich_mission_diff(diff, loc, script_index=_Idx())
    ev = out.events[0]
    assert ev.detail["reward_events"] == []
    assert ev.detail["player_choice_known"] is False
    assert "Handle the Confederation" in ev.summary
    assert "弹出" not in ev.summary
    assert "Revolts" not in ev.summary


def test_enrich_mission_missing_loc_humanizes():
    loc = GameLocalisation()
    diff = DiffResult(
        prev_date="a",
        curr_date="b",
        player="TEU",
        events=[
            DiffEvent(
                kind="mission_completed",
                tag="TEU",
                summary="x",
                detail={"mission_id": "teu_seek_imperial_protection"},
            )
        ],
    )
    out = enrich_mission_diff(diff, loc)
    assert out.events[0].detail["loc_found"] is False
    assert out.events[0].detail["title"] == humanize_mission_id(
        "teu_seek_imperial_protection"
    )
    # 成稿摘要不点名脚本式标题
    assert "无可用本地化标题" in out.events[0].summary
    assert "teu_seek_imperial_protection" not in out.events[0].summary
    assert "teu seek imperial" not in out.events[0].summary.lower()


def test_brief_and_mock_editor_omit_missions_section():
    """成稿不再含「任务与剧情」。"""
    diff = DiffResult(
        prev_date="1447.6.1",
        curr_date="1449.12.1",
        player="TEU",
        events=[
            DiffEvent(
                kind="tech_changed",
                tag="TEU",
                summary="军事科技 3→4",
                detail={"tech": "mil_tech", "from": 3, "to": 4},
            )
        ],
    )
    brief = make_brief(diff)
    assert "不要**写「任务与剧情」" in brief or "任务书不在本产品范围" in brief
    assert "## 任务与剧情" not in brief

    names = NameResolver(country_names={"TEU": "Teutonic Order"})
    from eu4_game_report.ae import assess_player_ae

    ae = assess_player_ae(diff)
    md = _mock_editor(diff, names, ae)
    assert "## 叙事" in md
    assert "## 战局要点" in md
    assert "## 外交与 AE" in md
    assert "## 任务与剧情" not in md
    assert "Handle the Confederation" not in md


def test_load_localisation_from_temp_roots(tmp_path: Path):
    game = tmp_path / "game"
    loc_dir = game / "localisation"
    loc_dir.mkdir(parents=True)
    (loc_dir / "missions_l_english.yml").write_text(
        'l_english:\n teu_x_title:0 "Seek Protection"\n teu_x_desc:0 "Ask the Empire."\n',
        encoding="utf-8",
    )
    from eu4_game_report.localisation import load_localisation_from_roots

    loc = load_localisation_from_roots([game])
    text = loc.mission_text("teu_x")
    assert text.loc_found
    assert text.title == "Seek Protection"
    assert "Empire" in text.desc
