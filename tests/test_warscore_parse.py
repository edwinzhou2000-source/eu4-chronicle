"""真档形态 warscore / 战争细节解析 → Diff / 成稿。"""

from __future__ import annotations

from eu4_chronicle.ae import assess_player_ae
from eu4_chronicle.agents import _mock_editor, _mock_war_section
from eu4_chronicle.diff import diff_states
from eu4_chronicle.filter import filter_diff
from eu4_chronicle.names import NameResolver
from eu4_chronicle.parser import parse_save_text
from eu4_chronicle.warscore import assess_player_wars

# 贴近真档：重复 participants={ value= tag= } + defender_score + history
REALISTIC_TEU_WAR = """
date="1454.6.1"
player="TEU"
ironman=no
countries={
  TEU={
    name="Teutonic Order"
    owned_provinces={ 43 42 }
    manpower=8.5
    max_manpower=20
    navy_size=28
  }
  POL={
    name="Poland"
    owned_provinces={ 262 254 }
  }
  LIV={ name="Livonian Order" owned_provinces={ 37 } }
  BOH={ name="Bohemia" owned_provinces={ 266 } }
}
provinces={
  43={ name="Danzig" owner="TEU" controller="TEU" }
  42={ name="Warmia" owner="TEU" controller="TEU" }
  262={ name="Krakow" owner="POL" controller="POL" }
  254={ name="Poznan" owner="POL" controller="TEU" }
  255={ name="Kalisz" owner="POL" controller="TEU" }
  37={ name="Livland" owner="LIV" controller="LIV" }
  266={ name="Prague" owner="BOH" controller="BOH" }
}
active_war={
  name="Teutonic Conquest of Naklo"
  history={
    1448.3.1={
      add_attacker="TEU"
    }
    1448.3.1={
      add_defender="POL"
    }
    1448.3.1={
      war_goal={
        type="take_province"
        casus_belli="cb_conquest"
        province=254
      }
    }
    1450.6.12={
      battle={
        name="Naklo"
        location=254
        result=yes
        attacker={
          infantry=12000
          losses=2100
          country="TEU"
          commander="Konrad"
        }
        defender={
          infantry=9000
          losses=6400
          country="POL"
          commander="Kazimierz"
        }
      }
    }
  }
  participants={
    value=71.5
    tag="TEU"
    losses={
      members={ 1000 200 0 0 500 0 0 0 0 0 0 0 }
    }
  }
  participants={
    value=28.5
    tag="POL"
    losses={
      members={ 4000 800 0 0 200 0 0 0 0 0 0 0 }
    }
  }
  original_attacker="TEU"
  original_defender="POL"
  attackers={ TEU }
  defenders={ POL }
  defender_score=-68.0
}
"""

PREV_NO_WAR = """
date="1447.1.1"
player="TEU"
ironman=no
countries={
  TEU={
    name="Teutonic Order"
    owned_provinces={ 43 }
    allies={ LIV }
    manpower=15.2
    max_manpower=20
    navy_size=26
  }
  POL={ name="Poland" owned_provinces={ 262 254 255 } }
  LIV={ name="Livonian Order" owned_provinces={ 37 } }
  BOH={ name="Bohemia" owned_provinces={ 266 } }
}
provinces={
  43={ name="Danzig" owner="TEU" controller="TEU" }
  262={ name="Krakow" owner="POL" controller="POL" }
  254={ name="Poznan" owner="POL" controller="POL" }
  255={ name="Kalisz" owner="POL" controller="POL" }
}
"""


def test_parse_realistic_active_war_defender_score():
    state = parse_save_text(REALISTIC_TEU_WAR)
    assert len(state.wars) == 1
    war = state.wars[0]
    assert war.name == "Teutonic Conquest of Naklo"
    assert "TEU" in war.attackers
    assert "POL" in war.defenders
    assert war.defender_score == -68.0
    assert war.score_for("TEU") == 68.0
    assert war.score_for("POL") == -68.0
    # value 为贡献度，不得误当战分覆盖战争级分数
    teu_p = next(p for p in war.participants if p.tag == "TEU")
    assert teu_p.contribution == 71.5
    assert not teu_p.warscore_known
    assert war.war_goal_type == "take_province"
    assert war.casus_belli == "cb_conquest"
    assert war.war_goal_province == 254
    assert war.occupied_provinces == 2
    assert war.battles
    assert war.battles[0].name == "Naklo"
    assert war.battles[0].attacker_won is True


def test_history_only_sides_when_lists_missing():
    text = """
    date="1450.1.1"
    player="TEU"
    countries={ TEU={ name="Teutonic Order" } POL={ name="Poland" } }
    active_war={
      name="Border Skirmish"
      history={
        1449.1.1={ add_attacker="TEU" }
        1449.1.1={ add_defender="POL" }
      }
      participants={
        value=10
        tag="TEU"
      }
      participants={
        value=5
        tag="POL"
      }
      defender_score=-12.5
    }
    """
    war = parse_save_text(text).wars[0]
    assert war.attackers == ["TEU"]
    assert war.defenders == ["POL"]
    assert war.score_for("TEU") == 12.5


def test_sample_style_tag_keyed_warscore_still_works():
    text = """
    date="1453.5.29"
    player="BYZ"
    countries={
      BYZ={ name="Byzantium" owned_provinces={ 151 } }
      TUR={ name="Ottomans" owned_provinces={ 318 } }
    }
    active_wars={
      war={
        name="Byzantine Reconquest of Hudavendigar"
        attackers={ BYZ }
        defenders={ TUR }
        participants={
          BYZ={ side="attackers" warscore=42 }
          TUR={ side="defenders" warscore=-42 }
        }
      }
    }
    """
    war = parse_save_text(text).wars[0]
    assert war.score_for("BYZ") == 42.0
    assert war.score_for("TUR") == -42.0


def test_pipeline_mock_contains_plus_68_and_decisive_phrase():
    prev = parse_save_text(PREV_NO_WAR)
    curr = parse_save_text(REALISTIC_TEU_WAR)
    raw = diff_states(prev, curr)
    filtered = filter_diff(raw, prev=prev, curr=curr)
    war_ev = next(e for e in filtered.events if e.kind == "war_started")
    assert war_ev.detail.get("player_warscore") == 68.0
    assert war_ev.detail.get("occupied_provinces") == 2
    assert war_ev.detail.get("war_goal_type") == "take_province"
    assert war_ev.detail.get("major_battles")

    names = NameResolver.from_states(prev, curr)
    readable = names.rewrite_diff(filtered)
    ae = assess_player_ae(readable, country_label=names.country)
    wars = assess_player_wars(readable)
    assert wars.primary is not None
    assert wars.primary.score_known
    assert wars.primary.player_score == 68
    assert wars.primary.tier == "decisive"

    md = _mock_editor(readable, names, ae)
    war = _mock_war_section(readable, names, ae, heading=False)
    assert "+68" in md or "战分 +68" in md or "玩家战分 +68" in md
    assert "68" in md
    assert "优势在握" in md or "基本打赢" in md
    assert "未解析到玩家战分" not in md
    assert "不作胜负判断" not in md
    assert "战分未知" not in md
    assert "胜负未定" not in md
    assert "占领" in war or "Naklo" in war or "战争目标" in war
