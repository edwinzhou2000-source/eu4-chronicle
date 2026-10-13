"""已结束战争成稿：短写、无乱码泄漏、勿当进行中。"""

from __future__ import annotations

from eu4_game_report.ae import assess_player_ae
from eu4_game_report.agents import _mock_editor, _mock_narrative_paragraph, _mock_war_section
from eu4_game_report.localisation import looks_mojibake, sanitize_display_name
from eu4_game_report.models import DiffEvent, DiffResult
from eu4_game_report.names import NameResolver
from eu4_game_report.parser import parse_save_text
from eu4_game_report.diff import diff_states
from eu4_game_report.filter import filter_diff
from eu4_game_report.warscore import assess_player_wars, war_guidance_lines


def test_side_labels_puts_player_first():
    from eu4_game_report.agents import _side_labels

    names = NameResolver(
        country_names={"TEU": "Teutonic Order", "BOH": "Bohemia", "POL": "Poland"}
    )
    s = _side_labels(["BOH", "TEU", "GLG"], names, player="TEU", limit=2)
    assert s.startswith("条顿") or s.startswith("Teutonic")
    assert "等" in s


def test_sanitize_mojibake_battle_name():
    assert looks_mojibake("R\ufffdgen")
    assert sanitize_display_name("R\ufffdgen", fallback="吕根") == "吕根"
    assert sanitize_display_name("Stargard", fallback="x") == "Stargard"


def test_previous_war_lifetime_sides_after_rem():
    text = """
date="1468.6.2"
player="TEU"
countries={ TEU={ development=1 } POL={ development=1 } BRA={ development=1 } OPL={ development=1 } }
previous_war={
  name="Teutonic Conquest of Naklo"
  history={
    1448.1.1={ add_attacker="TEU" }
    1448.1.1={ add_defender="POL" }
    1450.1.1={ add_attacker="OPL" }
    1450.1.1={ add_defender="BRA" }
    1454.1.1={ rem_attacker="TEU" }
    1454.1.1={ rem_defender="POL" }
    1454.1.1={ rem_attacker="OPL" }
    1454.1.1={ rem_defender="BRA" }
  }
}
"""
    # 仅 rem 到空 → lifetime；若只 rem TEU/POL 而残留 OPL/BRA，lifetime 仍须含 TEU
    state = parse_save_text(text)
    w = state.previous_wars[0]
    assert "TEU" in w.attackers
    assert "POL" in w.defenders


def test_previous_war_prefers_lifetime_over_leftover_sides():
    """结束时 rem 不净：不得用残留 GLG/OPL vs BRA 冒充主攻守。"""
    text = """
date="1468.6.2"
player="TEU"
countries={ TEU={ development=1 } POL={ development=1 } BRA={ development=1 }
  GLG={ development=1 } OPL={ development=1 } }
previous_war={
  name="Teutonic Conquest of Naklo"
  history={
    1448.1.1={ add_attacker="TEU" }
    1448.1.1={ add_defender="POL" }
    1450.1.1={ add_attacker="GLG" }
    1450.1.1={ add_attacker="OPL" }
    1450.1.1={ add_defender="BRA" }
    1454.1.1={ rem_attacker="TEU" }
    1454.1.1={ rem_defender="POL" }
    1454.1.1={ rem_attacker="GLG" }
    1454.1.1={ rem_defender="BRA" }
  }
}
"""
    w = parse_save_text(text).previous_wars[0]
    assert "TEU" in w.attackers
    assert "POL" in w.defenders
    # lifetime 含曾加入各方；关键是主角在列，而非只剩残留
    assert set(w.attackers) >= {"TEU", "GLG", "OPL"}


def test_mock_ended_wars_compact_no_ongoing_or_force():
    prev = parse_save_text(
        """
date="1447.6.1"
player="TEU"
countries={ TEU={ development=90 army_size=32 manpower=15.2 max_manpower=20 }
  POL={ development=200 } STE={ development=40 } }
"""
    )
    curr = parse_save_text(
        """
date="1468.6.2"
player="TEU"
countries={ TEU={ development=139 army_size=66 manpower=17.8 max_manpower=20 }
  POL={ development=180 } STE={ development=30 } }
previous_war={
  name="Teutonic Conquest of Naklo"
  outcome=2
  action=1454.1.1
  history={
    1448.1.1={ add_attacker="TEU" }
    1448.1.1={ add_defender="POL" }
    1450.1.1={
      battle={ name="R\ufffdgen" location=4745 result=yes
        attacker={ losses=100 country="TEU" }
        defender={ losses=200 country="POL" } }
    }
    1454.1.1={ rem_attacker="TEU" }
    1454.1.1={ rem_defender="POL" }
  }
  last_warscore_quarter=-10
  participants={ value=100 tag="TEU" war_score=0 }
  participants={ value=200 tag="POL" war_score=0 }
}
previous_war={
  name="Teutonic Conquest of Stargard"
  outcome=2
  action=1458.1.1
  history={
    1455.1.1={ add_attacker="TEU" }
    1455.1.1={ add_defender="STE" }
    1456.1.1={
      battle={ name="Stargard" location=4746 result=yes
        attacker={ losses=446 country="TEU" }
        defender={ losses=4000 country="STE" } }
    }
    1458.1.1={ rem_attacker="TEU" }
    1458.1.1={ rem_defender="STE" }
  }
  last_warscore_quarter=-24
  attacker_score=7
  participants={ value=100 tag="TEU" war_score=0 }
  participants={ value=40 tag="STE" war_score=0 }
}
"""
    )
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    filtered.events.extend(
        [
            DiffEvent(
                kind="army_changed",
                tag="TEU",
                summary="条顿骑士团 陆军约 32 → 66",
                detail={"from": 32.0, "to": 66.0},
            ),
            DiffEvent(
                kind="manpower_changed",
                tag="TEU",
                summary="当前人力 15.2k→17.8k",
                detail={"from": 15.2, "to": 17.8, "max_from": 20.0, "max_to": 20.0},
            ),
        ]
    )
    names = NameResolver(
        country_names={"TEU": "Teutonic Order", "POL": "Poland", "STE": "Stettin"}
    )
    ae = assess_player_ae(filtered)
    assessment = assess_player_wars(filtered)
    assert assessment.standings
    assert all(s.ended for s in assessment.standings)

    narrative = _mock_narrative_paragraph(filtered, names, ae)
    assert "仍在进行" not in narrative
    assert "详见战局" in narrative
    assert "和约取胜" not in narrative
    assert "交战占领省份约 0" not in narrative
    assert "战争目标加分" not in narrative
    assert "±0" not in narrative
    assert "未及全功" not in narrative
    assert "损 " not in narrative
    assert "战分落后" not in narrative

    war = _mock_war_section(filtered, names, ae, heading=False)
    assert "和约取胜" in war
    assert "本区间内打完" in war
    assert "本区间无进行中战争" not in war
    assert "本区间无战争" not in war
    assert "战争目标加分" not in war
    assert "未及全功" not in war
    assert "宜收缩战线或求和" not in war
    assert "陆军约" not in war
    assert "15.2" not in war
    assert "\ufffd" not in war
    assert "R\ufffdgen" not in war
    assert "humiliate_rotw" not in war
    assert "cb_humiliate" not in war

    md = _mock_editor(filtered, names, ae)
    assert "和约取胜" in md
    assert "本区间内打完" in md
    assert "宜收缩战线或求和" not in md
    assert "战分落后" not in md
    assert "战争目标加分" not in md

    guidance = "\n".join(war_guidance_lines(assessment))
    assert "本区间（两档之间）内发生并打完" in guidance
    assert "禁止写成「本区间无进行中战争" in guidance
    assert "±0" in guidance
    assert "未及全功" in guidance
    # 已结束场次行本身不应夹带「战争目标加分」
    for line in guidance.splitlines():
        if line.startswith("「") and "已结束" in line:
            assert "战争目标加分" not in line


def test_ended_wars_tech_changed_not_contradict_war_section():
    """叙事有本国三科升级时，战局要点不得说「本区间无军科」。"""
    from eu4_game_report.agents import make_brief
    from eu4_game_report.models import DiffEvent

    prev = parse_save_text(
        """
date="1447.6.1"
player="TEU"
countries={
  TEU={ development=90 technology={ adm_tech=3 dip_tech=3 mil_tech=3 } }
  POL={ development=200 technology={ adm_tech=3 dip_tech=3 mil_tech=3 } }
}
"""
    )
    curr = parse_save_text(
        """
date="1468.6.2"
player="TEU"
countries={
  TEU={ development=139 technology={ adm_tech=6 dip_tech=6 mil_tech=6 } }
  POL={ development=180 technology={ adm_tech=3 dip_tech=3 mil_tech=3 } }
}
previous_war={
  name="Teutonic Conquest of Naklo"
  outcome=2
  action=1454.1.1
  history={
    1448.1.1={ add_attacker="TEU" }
    1448.1.1={ add_defender="POL" }
    1454.1.1={ rem_attacker="TEU" }
    1454.1.1={ rem_defender="POL" }
  }
  last_warscore_quarter=-5
}
"""
    )
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    # 确保有 tech_changed（diff 应已产出）
    assert any(e.kind == "tech_changed" for e in filtered.events)
    names = NameResolver(country_names={"TEU": "Teutonic Order", "POL": "Poland"})
    ae = assess_player_ae(filtered)
    narrative = _mock_narrative_paragraph(filtered, names, ae)
    war = _mock_war_section(filtered, names, ae, heading=False)
    brief = make_brief(filtered, names=names, ae=ae)

    assert "军事科技" in narrative or "军事" in narrative
    assert "本区间内打完" in war
    assert "本区间无军科" not in war
    assert "不作对敌" not in war
    assert "交战当时" not in war
    assert "本 Diff 无双方军科对比数字" not in brief
    assert "故不作代差" not in brief
    assert "勿写入成稿" in brief
    assert not any(e.kind == "war_tech_compare" for e in filtered.events)
