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

# 用户真档语义：总战分≈68、ticking≈17 — 两键同存且量级不同
# 复现旧 bug：若优先 defender_score 会得到 +17 并误判「胶着」
TOTAL68_TICKING17_WAR = """
date="1454.6.1"
player="TEU"
ironman=no
countries={
  TEU={
    name="Teutonic Order"
    owned_provinces={ 43 42 2963 }
    manpower=8.5
    max_manpower=20
    navy_size=28
  }
  POL={ name="Poland" owned_provinces={ 262 254 } }
}
provinces={
  43={ name="Danzig" owner="TEU" controller="TEU" }
  42={ name="Warmia" owner="TEU" controller="TEU" }
  2963={ name="Notec" owner="TEU" controller="TEU" }
  262={ name="Krakow" owner="POL" controller="POL" }
  254={ name="Poznan" owner="POL" controller="TEU" }
}
active_war={
  name="Teutonic Conquest of Notec"
  history={
    1448.3.1={ add_attacker="TEU" }
    1448.3.1={ add_defender="POL" }
    1448.3.1={
      war_goal={
        type="take_claim"
        casus_belli="cb_conquest"
        province=2963
      }
    }
  }
  take_claim={
    type="take_claim"
    casus_belli="cb_conquest"
    province=2963
  }
  participants={
    value=71.5
    tag="TEU"
  }
  participants={
    value=28.5
    tag="POL"
  }
  original_attacker="TEU"
  original_defender="POL"
  attackers={ TEU }
  defenders={ POL }
  attacker_score=68.0
  defender_score=-17.0
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
    assert war.ticking_for("TEU") is None
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


def test_total_68_vs_ticking_17_field_split():
    """总战分来自 attacker_score=68；ticking 来自 defender_score=-17（攻方视角 +17）。"""
    war = parse_save_text(TOTAL68_TICKING17_WAR).wars[0]
    assert war.attacker_score == 68.0
    assert war.defender_score == -17.0
    assert war.total_score_source == "attacker_score"
    assert war.ticking_score_source == "defender_score"
    assert war.score_for("TEU") == 68.0
    assert war.ticking_for("TEU") == 17.0
    assert war.war_goal_type == "take_claim"
    assert war.casus_belli == "cb_conquest"
    assert war.war_goal_province == 2963


def test_swapped_keys_still_picks_larger_as_total():
    """若 defender_score 量级为总战分、attacker_score 为 ticking，仍选大者为总。"""
    text = TOTAL68_TICKING17_WAR.replace(
        "attacker_score=68.0\n  defender_score=-17.0",
        "attacker_score=17.0\n  defender_score=-68.0",
    )
    war = parse_save_text(text).wars[0]
    assert war.score_for("TEU") == 68.0
    assert war.ticking_for("TEU") == 17.0
    assert war.total_score_source == "defender_score"
    assert war.ticking_score_source == "attacker_score"


def test_participant_war_score_as_total_when_war_level_is_ticking():
    text = """
    date="1454.1.1"
    player="TEU"
    countries={ TEU={ name="Teutonic Order" } POL={ name="Poland" } }
    active_war={
      name="Border War"
      attackers={ TEU }
      defenders={ POL }
      participants={
        value=80
        tag="TEU"
        war_score=68
      }
      participants={
        value=20
        tag="POL"
        war_score=-68
      }
      defender_score=-17.0
    }
    """
    war = parse_save_text(text).wars[0]
    assert war.score_for("TEU") == 68.0
    assert war.ticking_for("TEU") == 17.0
    assert war.total_score_source.startswith("participants.")
    assert war.ticking_score_source == "defender_score"


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


def test_pipeline_total_68_not_ticking_17_as_contested():
    """成稿主分数为 +68；不得出现「胶着/+17 当总战分」。"""
    prev = parse_save_text(PREV_NO_WAR)
    curr = parse_save_text(TOTAL68_TICKING17_WAR)
    raw = diff_states(prev, curr)
    filtered = filter_diff(raw, prev=prev, curr=curr)
    war_ev = next(e for e in filtered.events if e.kind == "war_started")
    assert war_ev.detail.get("player_warscore") == 68.0
    assert war_ev.detail.get("player_ticking_warscore") == 17.0
    assert war_ev.detail.get("total_score_source") == "attacker_score"
    assert war_ev.detail.get("ticking_score_source") == "defender_score"
    assert war_ev.detail.get("war_goal_type") == "take_claim"
    assert war_ev.detail.get("war_goal_province") == 2963

    names = NameResolver.from_states(prev, curr)
    readable = names.rewrite_diff(filtered)
    ae = assess_player_ae(readable, country_label=names.country)
    wars = assess_player_wars(readable)
    assert wars.primary is not None
    assert wars.primary.player_score == 68
    assert wars.primary.ticking_score == 17
    assert wars.primary.tier == "decisive"

    md = _mock_editor(readable, names, ae)
    war = _mock_war_section(readable, names, ae, heading=False)
    assert "+68" in md
    assert "优势在握" in md or "基本打赢" in md
    assert "双方胶着" not in md
    assert "胶着（战分 +17）" not in md
    # ticking 可另行列出，但不得驱动标题胶着
    assert "ticking" in war
    assert "+17" in war
    assert "夺取宣称" in war
    assert "征服" in war
    assert "诺泰奇" in war
    title_line = md.split("\n")[0]
    assert "双方胶着" not in title_line
    assert "+17" not in title_line or "+68" in title_line
