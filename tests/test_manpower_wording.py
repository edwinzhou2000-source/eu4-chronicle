"""人力文案须区分当前人力与人力上限。"""

from __future__ import annotations

from eu4_chronicle.agents import _mock_narrative_paragraph, make_brief
from eu4_chronicle.ae import assess_player_ae
from eu4_chronicle.diff import diff_states
from eu4_chronicle.models import CountryState, DiffEvent, DiffResult, GameState
from eu4_chronicle.names import NameResolver


def test_diff_and_rewrite_separate_current_and_max():
    prev = GameState(
        date="a",
        player="TEU",
        countries={
            "TEU": CountryState(tag="TEU", manpower=15.2, max_manpower=20.0),
        },
    )
    curr = GameState(
        date="b",
        player="TEU",
        countries={
            "TEU": CountryState(tag="TEU", manpower=17.8, max_manpower=22.0),
        },
    )
    raw = diff_states(prev, curr)
    ev = next(e for e in raw.events if e.kind == "manpower_changed")
    assert "当前人力" in ev.summary
    assert "人力上限" in ev.summary
    assert "千人" not in ev.summary
    assert "15.2k" in ev.summary and "17.8k" in ev.summary
    assert "20.0k" in ev.summary and "22.0k" in ev.summary

    names = NameResolver(country_names={"TEU": "条顿骑士团"})
    out = names.rewrite_event(ev)
    assert "当前人力" in out.summary
    assert "人力上限" in out.summary
    assert "千人" not in out.summary
    assert "15.2k" in out.summary
    # 禁止旧式「人力 a/b → c/d」含混写法作为唯一表述
    assert "条顿骑士团 人力 " not in out.summary


def test_mock_narrative_and_brief_use_explicit_labels():
    diff = DiffResult(
        prev_date="a",
        curr_date="b",
        player="TEU",
        events=[
            DiffEvent(
                kind="manpower_changed",
                tag="TEU",
                summary="x",
                detail={
                    "from": 15.2,
                    "to": 17.8,
                    "max_from": 20.0,
                    "max_to": 20.0,
                },
            )
        ],
    )
    names = NameResolver(country_names={"TEU": "条顿骑士团"})
    ae = assess_player_ae(diff)
    narrative = _mock_narrative_paragraph(diff, names, ae)
    assert "当前人力" in narrative
    assert "人力上限" in narrative
    assert "千人" not in narrative
    assert "15.2k→17.8k" in narrative

    brief = make_brief(diff, names=names, ae=ae)
    assert "当前人力" in brief
    assert "人力上限" in brief
    assert "叙事内政硬数字" in brief
    assert "15.2k→17.8k" in brief
    assert "成稿后缀" in brief or "k" in brief
    assert "十五万二千" in brief or "严禁" in brief
    assert "禁止含混" in brief or "禁止编造" in brief


def test_mock_war_section_no_war_stays_short_no_domestic_dump():
    """无战争时战局要点不得塞发展度/威望/AE/编制流水账。"""
    from eu4_chronicle.agents import _mock_war_section
    from eu4_chronicle.ae import assess_player_ae

    diff = DiffResult(
        prev_date="a",
        curr_date="b",
        player="TEU",
        events=[
            DiffEvent(
                kind="manpower_changed",
                tag="TEU",
                summary="当前人力 15.2k→17.8k",
                detail={"from": 15.2, "to": 17.8, "max_from": 20.0, "max_to": 20.0},
            ),
            DiffEvent(
                kind="development_changed",
                tag="TEU",
                summary="发展度",
                detail={"from": 94.0, "to": 139.0},
            ),
            DiffEvent(
                kind="army_changed",
                tag="TEU",
                summary="陆军",
                detail={"from": 32.0, "to": 66.0},
            ),
            DiffEvent(
                kind="prestige_changed",
                tag="TEU",
                summary="威望",
                detail={"from": 2.0, "to": 46.0},
            ),
        ],
    )
    names = NameResolver(country_names={"TEU": "条顿骑士团"})
    ae = assess_player_ae(diff)
    war = _mock_war_section(diff, names, ae, heading=False)
    assert "无可稽战争" in war or "不作优劣判断" in war
    assert "发展度" not in war
    assert "威望" not in war
    assert "AE" not in war and "包围网" not in war
    assert "陆军" not in war
    assert "15.2" not in war  # 编制跳变也不塞进无战争的战局要点
