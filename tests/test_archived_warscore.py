"""归档 previous_war 战分失真：保留 active 消失前分数；矛盾归档分省略。"""

from __future__ import annotations

from eu4_game_report.ae import assess_player_ae
from eu4_game_report.agents import _mock_editor, _mock_narrative_paragraph, _mock_war_section
from eu4_game_report.diff import diff_states
from eu4_game_report.filter import filter_diff
from eu4_game_report.names import NameResolver
from eu4_game_report.parser import parse_save_text
from eu4_game_report.warscore import assess_player_wars

PREV_ACTIVE_NAKLO = """
date="1454.11.18"
player="TEU"
countries={ TEU={ development=100 } POL={ development=200 } }
active_war={
  name="Teutonic Conquest of Naklo"
  history={
    1448.1.1={ add_attacker="TEU" }
    1448.1.1={ add_defender="POL" }
  }
  attackers={ TEU }
  defenders={ POL }
  last_warscore_quarter=64.0
  last_warscore_year=48.0
  attacker_score=16.8
  participants={ value=151.8 tag="TEU" war_score=0 }
  participants={ value=318.4 tag="POL" war_score=0 }
}
"""

CURR_PREVIOUS_NAKLO_BAD = """
date="1468.6.2"
player="TEU"
countries={ TEU={ development=139 } POL={ development=180 } }
previous_war={
  name="Teutonic Conquest of Naklo"
  last_warscore_quarter=-5
  last_warscore_year=-5
  attacker_score=16.8
  outcome=2
  action=1454.11.16
  history={
    1448.1.1={ add_attacker="TEU" }
    1448.1.1={ add_defender="POL" }
    1454.11.18={ rem_attacker="TEU" }
    1454.11.18={ rem_defender="POL" }
  }
  participants={ value=151.8 tag="TEU" war_score=0 }
  participants={ value=318.4 tag="POL" war_score=0 }
}
"""

PREV_EMPTY = """
date="1447.6.1"
player="TEU"
countries={ TEU={ development=90 } POL={ development=200 } STE={ development=40 } }
"""

CURR_PREVIOUS_ONLY = """
date="1468.6.2"
player="TEU"
countries={ TEU={ development=139 } POL={ development=180 } STE={ development=30 } }
previous_war={
  name="Teutonic Conquest of Stargard"
  last_warscore_quarter=-24
  last_warscore_year=-24
  attacker_score=6.8
  outcome=2
  action=1461.6.10
  history={
    1455.1.1={ add_attacker="TEU" }
    1455.1.1={ add_defender="STE" }
    1461.6.12={ rem_attacker="TEU" }
    1461.6.12={ rem_defender="STE" }
  }
  participants={ value=113.7 tag="TEU" war_score=0 }
  participants={ value=39.5 tag="STE" war_score=0 }
}
"""


def test_active_to_previous_ended_war_no_score_in_prose():
    """消失前战分可留在 Diff detail，但评估/成稿不写，避免「可靠战分」误导。"""
    prev = parse_save_text(PREV_ACTIVE_NAKLO)
    curr = parse_save_text(CURR_PREVIOUS_NAKLO_BAD)
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    ended = [e for e in filtered.events if e.kind == "war_ended"]
    assert len(ended) == 1
    detail = ended[0].detail or {}
    assert detail.get("outcome") == 2
    assert detail.get("player_won") is True

    assessment = assess_player_wars(filtered)
    assert assessment.standings[0].score_known is False
    assert assessment.standings[0].tier == "victory"
    assert assessment.standings[0].player_won is True

    names = NameResolver(country_names={"TEU": "Teutonic Order", "POL": "Poland"})
    ae = assess_player_ae(filtered)
    war = _mock_war_section(filtered, names, ae, heading=False)
    md = _mock_editor(filtered, names, ae)
    assert "和约取胜" in war
    assert "可靠战分" not in war
    assert "可靠战分" not in md
    assert "战分 +64" not in war
    assert "战分 +64" not in md
    assert "-5" not in md
    assert "战分落后" not in md


def test_previous_only_unreliable_negative_omitted():
    prev = parse_save_text(PREV_EMPTY)
    curr = parse_save_text(CURR_PREVIOUS_ONLY)
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    ended = next(e for e in filtered.events if e.kind == "war_ended")
    detail = ended.detail or {}
    assert detail.get("player_warscore") is None
    assert detail.get("score_unreliable") is True
    assert detail.get("raw_last_warscore") == -24.0
    assert detail.get("player_won") is True

    assessment = assess_player_wars(filtered)
    s = assessment.standings[0]
    assert s.score_known is False
    assert s.tier == "victory"
    assert s.player_won is True

    names = NameResolver(country_names={"TEU": "Teutonic Order", "STE": "Stettin"})
    ae = assess_player_ae(filtered)
    narrative = _mock_narrative_paragraph(filtered, names, ae)
    war = _mock_war_section(filtered, names, ae, heading=False)
    md = _mock_editor(filtered, names, ae)
    assert "详见战局" in narrative
    assert "和约取胜" not in narrative
    assert "和约取胜" in war
    assert "-24" not in narrative
    assert "-24" not in war
    assert "-24" not in md
    assert "战分落后" not in md
    assert "媾和前战分快照" not in md
