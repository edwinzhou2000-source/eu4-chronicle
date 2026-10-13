"""Diff 关键路径测试。"""

from __future__ import annotations

from pathlib import Path

from eu4_game_report.diff import diff_states, events_to_brief
from eu4_game_report.parser import parse_save

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_diff_samples_detects_key_events():
    prev = parse_save(SAMPLES / "byz_1444.eu4")
    curr = parse_save(SAMPLES / "byz_1453.eu4")
    result = diff_states(prev, curr)

    assert result.player == "BYZ"
    assert result.prev_date == "1444.11.11"
    assert result.curr_date == "1453.5.29"
    kinds = {e.kind for e in result.events}
    assert "date_changed" in kinds
    assert "province_gained" in kinds  # 317
    assert "alliance_broken" in kinds  # WAL
    assert "war_started" in kinds
    assert "ae_changed" in kinds
    assert "subject_changed" in kinds  # ATH

    gained = [e for e in result.events if e.kind == "province_gained" and e.tag == "BYZ"]
    assert any(317 in e.detail.get("provinces", []) for e in gained)

    brief = events_to_brief(result)
    assert "BYZ" in brief
    assert "事件数" in brief


def test_diff_war_end():
    prev = parse_save(SAMPLES / "byz_1453.eu4")
    curr = parse_save(SAMPLES / "byz_1444.eu4")
    # 反向：战争从有到无
    result = diff_states(prev, curr)
    assert any(e.kind == "war_ended" for e in result.events)
