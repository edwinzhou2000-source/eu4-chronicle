"""玩家过滤与名称解析。"""

from __future__ import annotations

from pathlib import Path

from eu4_game_report.diff import diff_states
from eu4_game_report.filter import filter_diff, filter_player_events
from eu4_game_report.models import DiffEvent
from eu4_game_report.names import NameResolver
from eu4_game_report.parser import parse_save

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
    # 负 id（真档 Clausewitz 键）与正 id 等价
    assert names.province(-151) == names.province(151)

    raw = diff_states(prev, curr)
    filtered = filter_diff(raw, prev=prev, curr=curr, include_global=False)
    readable = names.rewrite_diff(filtered)
    gained = [e for e in readable.events if e.kind == "province_gained" and e.tag == "BYZ"]
    assert gained
    assert "317" not in gained[0].summary or "许达文迪加尔" in gained[0].summary or "Hudavendigar" in gained[0].summary
    assert "拜占庭" in gained[0].summary


def test_province_skips_garbled_and_uses_loc():
    """乱码存档名跳过；localisation PROV{{id}} + PLACE_EN_ZH 出中文。"""
    from eu4_game_report.localisation import GameLocalisation

    loc = GameLocalisation(entries={"PROV54": "Stade", "PROV55": "Oldenburg"})
    names = NameResolver(
        province_names={54: "\x11Ëe\x10TX\x12·V"},
        loc=loc,
    )
    assert names.province(54) == "施塔德"
    assert names.province(-55) == "奥尔登堡"
    # 无 loc、无中文映射 → 兜底
    assert NameResolver().province(88888) == "省份88888"


def test_country_uses_loc_and_formable_hints():
    """存档 name=TAG 时：localisation / 成型政府名 → 中文全名，勿留裸 TAG。"""
    from eu4_game_report.localisation import GameLocalisation
    from eu4_game_report.models import CountryState, GameState

    loc = GameLocalisation(entries={"WES": "Westphalia"})
    state = GameState(
        date="1460.6.10",
        player="XX9",
        countries={
            # 未进 COUNTRY_ZH 的自定义 TAG：靠 government_name 里的 NED
            "XX9": CountryState(
                tag="XX9",
                name="XX9",
                government_name="NYDD_NED_unite_province_gov_2",
                changed_tag_from="HOL",
                previous_country_tags=["HOL"],
            ),
            "WES": CountryState(tag="WES", name="WES"),
        },
    )
    names = NameResolver.from_states(state, loc=loc)
    assert names.country("WES") == "威斯特伐利亚"
    assert names.country("XX9") == "尼德兰"
    assert names.country("NE8") == "尼德兰"


def test_core_gained_dropped_from_player_report():
    """战报只保留取得省份；造核/新增核心不进默认 Diff。"""
    from eu4_game_report.parser import parse_save_text

    prev = parse_save_text(
        """
        date="1457.4.3"
        player="NED"
        countries={
          NED={
            name="Netherlands"
            owned_provinces={ 12 15 }
            core_provinces={ }
          }
        }
        """
    )
    curr = parse_save_text(
        """
        date="1460.6.10"
        player="NED"
        countries={
          NED={
            name="Netherlands"
            owned_provinces={ 12 15 54 }
            core_provinces={ 12 15 }
          }
        }
        """
    )
    raw = diff_states(prev, curr)
    assert any(e.kind == "core_gained" for e in raw.events)
    filtered = filter_diff(raw, prev=prev, curr=curr, include_global=False)
    assert not any(e.kind == "core_gained" for e in filtered.events)
    gained = [e for e in filtered.events if e.kind == "province_gained" and e.tag == "NED"]
    assert gained and gained[0].detail["provinces"] == [54]
    names = NameResolver.from_states(prev, curr)
    readable = names.rewrite_diff(filtered)
    prov = next(e for e in readable.events if e.kind == "province_gained")
    assert "取得" in prov.summary


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


def test_filter_drops_war_with_only_stale_participants():
    """仅 participants 含玩家、攻守皆无 → 不当玩家战争（脏 previous_war）。"""
    events = [
        DiffEvent(
            kind="war_ended",
            tag="ENG",
            summary="幽灵战争",
            detail={
                "name": "Phantom English War",
                "attackers": ["ENG", "SCO", "FRA"],
                "defenders": ["BUR"],
                "participants": ["ENG", "SCO", "FRA", "BUR", "NED"],
            },
        ),
        DiffEvent(
            kind="war_score_changed",
            tag="NED",
            summary="幽灵战分",
            detail={
                "name": "Phantom English War",
                "attackers": ["ENG"],
                "defenders": ["BUR"],
                "participants": ["NED", "ENG"],
                "from": 90,
                "to": 100,
            },
        ),
    ]
    kept = filter_player_events(events, player="NED", sphere={"NED", "ENG"})
    assert not any(e.kind in {"war_ended", "war_score_changed"} for e in kept)
