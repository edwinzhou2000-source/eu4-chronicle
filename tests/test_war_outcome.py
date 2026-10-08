"""previous_war outcome：和约胜负优先；与 outcome 矛盾的归档分不写入。"""

from __future__ import annotations

from eu4_chronicle.ae import assess_player_ae
from eu4_chronicle.agents import _mock_editor, _mock_narrative_paragraph, _mock_war_section
from eu4_chronicle.diff import diff_states
from eu4_chronicle.filter import filter_diff
from eu4_chronicle.names import NameResolver
from eu4_chronicle.parser import parse_save_text
from eu4_chronicle.warscore import assess_player_wars, tier_phrase


PREV = """
date="1447.6.1"
player="TEU"
countries={ TEU={ development=90 } POL={ development=200 } STE={ development=40 } }
"""

CURR = """
date="1468.6.2"
player="TEU"
countries={ TEU={ development=139 } POL={ development=180 } STE={ development=30 } }
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


def test_parse_outcome_and_player_won():
    state = parse_save_text(CURR)
    naklo = next(w for w in state.previous_wars if "Naklo" in w.name)
    assert naklo.outcome == 2
    assert naklo.ended_date == "1454.11.16"
    assert naklo.outcome_attacker_won() is True
    assert naklo.player_won("TEU") is True
    assert naklo.player_won("POL") is False
    # 快照可为负，但不改变和约胜负
    assert naklo.score_for("TEU") == -5.0


def test_assess_uses_outcome_not_negative_snapshot_tier():
    prev = parse_save_text(PREV)
    curr = parse_save_text(CURR)
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    for e in filtered.events:
        if e.kind != "war_ended":
            continue
        d = e.detail or {}
        assert d.get("score_unreliable") is True
        assert d.get("player_warscore") is None
    assessment = assess_player_wars(filtered)
    assert assessment.standings
    assert all(s.player_won is True for s in assessment.standings)
    assert all(s.tier == "victory" for s in assessment.standings)
    assert all(s.score_known is False for s in assessment.standings)
    assert "和约取胜" in tier_phrase("victory")


def test_mock_prose_says_won_not_disadvantage():
    prev = parse_save_text(PREV)
    curr = parse_save_text(CURR)
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    names = NameResolver(
        country_names={"TEU": "Teutonic Order", "POL": "Poland", "STE": "Stettin"}
    )
    ae = assess_player_ae(filtered)
    narrative = _mock_narrative_paragraph(filtered, names, ae)
    war = _mock_war_section(filtered, names, ae, heading=False)
    md = _mock_editor(filtered, names, ae)

    assert "和约取胜" in narrative
    assert "和约取胜" in war
    assert "战分落后" not in narrative
    assert "战分落后" not in war
    assert "双方胶着" not in narrative
    assert "双方胶着" not in war
    assert "胜负未定" not in war
    assert "均和约取胜" in md or "和约取胜" in md
    # 快照可附注，但不得当研判主结论
    assert "宜收缩战线或求和" not in md


def test_outcome_3_defender_win_player_attacker_loses():
    text = """
date="1500.1.1"
player="TEU"
countries={ TEU={ development=1 } POL={ development=1 } }
previous_war={
  name="Teutonic Failure"
  last_warscore_quarter=-40
  outcome=3
  action=1490.1.1
  history={
    1480.1.1={ add_attacker="TEU" }
    1480.1.1={ add_defender="POL" }
    1490.1.1={ rem_attacker="TEU" }
    1490.1.1={ rem_defender="POL" }
  }
}
"""
    prev = parse_save_text(
        'date="1470.1.1" player="TEU" countries={ TEU={ development=1 } POL={ development=1 } }'
    )
    curr = parse_save_text(text)
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    s = assess_player_wars(filtered).standings[0]
    assert s.player_won is False
    assert s.tier == "defeat"
