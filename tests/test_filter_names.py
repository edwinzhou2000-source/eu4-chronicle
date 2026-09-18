"""玩家过滤与名称解析。"""

from __future__ import annotations

from pathlib import Path

from eu4_chronicle.diff import diff_states
from eu4_chronicle.filter import filter_diff, filter_player_events
from eu4_chronicle.models import DiffEvent
from eu4_chronicle.names import NameResolver
from eu4_chronicle.parser import parse_save

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_filter_drops_distant_japan_wars():
    prev = parse_save(SAMPLES / "byz_1444.eu4")
    curr = parse_save(SAMPLES / "byz_1453.eu4")
    raw = diff_states(prev, curr)

    # 全量里应能看到远东战争
    assert any(
        e.kind in {"war_started", "war_ended"}
        and ("ITO" in (e.detail.get("participants") or []) or "SMZ" in (e.detail.get("attackers") or []))
        for e in raw.events
    ), "样例应含远东战争以便验证过滤"

    filtered = filter_diff(raw, prev=prev, curr=curr, include_global=False)
    for e in filtered.events:
        if e.kind in {"war_started", "war_ended", "war_score_changed"}:
            parts = set(e.detail.get("participants") or []) | set(e.detail.get("attackers") or []) | set(
                e.detail.get("defenders") or []
            )
            assert "BYZ" in parts
            assert "ITO" not in parts or "BYZ" in parts

    # 伊藤省份扩张不得进入玩家视图
    assert not any(
        e.kind == "province_gained" and e.tag == "ITO" for e in filtered.events
    )
    assert any(e.kind == "war_started" and "Hüdavendigar" in (e.detail.get("name") or "") for e in filtered.events)


def test_include_global_keeps_distant_wars():
    prev = parse_save(SAMPLES / "byz_1444.eu4")
    curr = parse_save(SAMPLES / "byz_1453.eu4")
    raw = diff_states(prev, curr)
    global_diff = filter_diff(raw, prev=prev, curr=curr, include_global=True)
    assert any(
        e.kind == "war_started"
        and "ITO" in (e.detail.get("defenders") or e.detail.get("attackers") or [])
        for e in global_diff.events
    )


def test_name_resolver_prefers_chinese_and_provinces():
    prev = parse_save(SAMPLES / "byz_1444.eu4")
    curr = parse_save(SAMPLES / "byz_1453.eu4")
    names = NameResolver.from_states(prev, curr)

    assert names.country("BYZ") == "拜占庭"
    assert names.country("TEU") == "条顿骑士团"
    assert names.country("ITO") == "伊藤"
    # 内置中文优先于存档英文
    assert "许达文迪加尔" in names.province(317) or names.province(317) == "Hudavendigar"
    assert names.province(151) in {"君士坦丁堡", "Constantinople"}
    # 无映射时兜底
    assert names.province(99999) == "省份99999"

    raw = diff_states(prev, curr)
    filtered = filter_diff(raw, prev=prev, curr=curr, include_global=False)
    readable = names.rewrite_diff(filtered)
    gained = [e for e in readable.events if e.kind == "province_gained" and e.tag == "BYZ"]
    assert gained
    assert "317" not in gained[0].summary or "许达文迪加尔" in gained[0].summary or "Hudavendigar" in gained[0].summary
    assert "拜占庭" in gained[0].summary


def test_filter_player_events_unit():
    events = [
        DiffEvent(kind="date_changed", tag="TEU", summary="时间推进", detail={"from": "a", "to": "b"}),
        DiffEvent(
            kind="war_started",
            tag="ITO",
            summary="远东战争",
            detail={"name": "x", "attackers": ["ITO"], "defenders": ["SMZ"], "participants": ["ITO", "SMZ"]},
        ),
        DiffEvent(
            kind="war_started",
            tag="TEU",
            summary="波罗的海战争",
            detail={"name": "y", "attackers": ["TEU"], "defenders": ["POL"], "participants": ["TEU", "POL"]},
        ),
        DiffEvent(kind="province_gained", tag="ITO", summary="伊藤得地", detail={"provinces": [1012]}),
        DiffEvent(kind="province_gained", tag="TEU", summary="条顿得地", detail={"provinces": [43]}),
        DiffEvent(kind="alliance_broken", tag="TEU", other_tag="LIT", summary="断盟"),
    ]
    kept = filter_player_events(events, player="TEU", sphere={"TEU", "POL", "LIT"})
    kinds_tags = {(e.kind, e.tag) for e in kept}
    assert ("date_changed", "TEU") in kinds_tags
    assert ("war_started", "TEU") in kinds_tags
    assert ("province_gained", "TEU") in kinds_tags
    assert ("alliance_broken", "TEU") in kinds_tags
    assert ("war_started", "ITO") not in kinds_tags
    assert ("province_gained", "ITO") not in kinds_tags
