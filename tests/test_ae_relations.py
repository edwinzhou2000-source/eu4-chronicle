"""active_relations AE 好感修正 → AE 分数与包围网条件。"""

from __future__ import annotations

from eu4_chronicle.ae import assess_player_ae
from eu4_chronicle.models import DiffResult
from eu4_chronicle.parser import parse_save_text


def test_parse_ae_from_aggressive_expansion_opinion_modifier():
    text = """
    date="1460.6.10"
    player="NE8"
    countries={
      NE8={ government_rank=2 owned_provinces={ 1 } }
      HSA={
        government_rank=1
        owned_provinces={ 45 }
        active_relations={
          NE8={
            opinion={
              modifier="aggressive_expansion"
              date=1460.2.5
              current_opinion=-79.002
              expiry_date=yes
            }
            opinion={
              modifier="had_war_with_us"
              date=1460.1.5
              current_opinion=-15.000
            }
            cached_sum=-181
            truce=yes
            attitude="attitude_rivalry"
          }
        }
      }
      STE={
        owned_provinces={ 48 }
        active_relations={
          NE8={
            opinion={
              modifier="aggressive_expansion"
              current_opinion=-63.0
            }
            cached_sum=-40
            truce=no
          }
        }
      }
    }
    """
    state = parse_save_text(text)
    assert state.countries["NE8"].aggressive_expansion["HSA"] == 79.002
    assert state.countries["NE8"].aggressive_expansion["STE"] == 63.0
    hsa_rel = state.countries["HSA"].relations["NE8"]
    assert hsa_rel.ae == 79.002
    assert hsa_rel.opinion == -181.0
    assert hsa_rel.truce is True
    ste_rel = state.countries["STE"].relations["NE8"]
    assert ste_rel.truce is False

    ae = assess_player_ae(
        DiffResult(prev_date="a", curr_date="b", player="NE8", events=[]),
        ae_snapshot=dict(state.countries["NE8"].aggressive_expansion),
        curr=state,
    )
    assert ae.max_to == 79.002
    assert ae.level == "high"
    assert not ae.warn_coalition
    # 样例未写 attitude_outraged，且 HSA 有停战 → 可入网为空
    assert ae.coalition_eligible == []
    assert "HSA" in ae.coalition_truce_blocked


def test_opinion_cache_overrides_stale_cached_sum():
    """外交 UI 好感来自 opinion_cache；cached_sum 常滞后。"""
    # 键序与 opinion_cache 下标对齐（空对象会被解析器收成 list，须带字段）
    text = """
    date="1460.6.10"
    player="NE8"
    countries={
      REB={ government_rank=1 }
      HES={
        owned_provinces={ 81 }
        opinion_cache={ 0 0 16 }
        active_relations={
          NE8={
            opinion={ modifier="aggressive_expansion" current_opinion=-58.868 }
            opinion={ modifier="improved_relation" current_opinion=41.500 }
            cached_sum=-19
            attitude="attitude_friendly"
          }
        }
      }
      NE8={ owned_provinces={ 97 } }
    }
    """
    state = parse_save_text(text)
    rel = state.countries["HES"].relations["NE8"]
    assert rel.opinion == 16.0
    assert rel.ae == 58.868
    assert state.countries["HES"].opinion_of["NE8"] == 16.0


def test_landless_tag_excluded_from_coalition_assessment():
    """无地幽灵国（如 POM）不进入包围网名单。"""
    text = """
    date="1460.6.10"
    player="NE8"
    countries={
      NE8={ owned_provinces={ 97 } }
      POM={
        government_rank=1
        owned_provinces={ }
        active_relations={
          NE8={
            opinion={ modifier="aggressive_expansion" current_opinion=-70.0 }
            cached_sum=-80
            attitude="attitude_outraged"
          }
        }
      }
      STE={
        owned_provinces={ 48 }
        active_relations={
          NE8={
            opinion={ modifier="aggressive_expansion" current_opinion=-63.0 }
            cached_sum=-40
            attitude="attitude_neutral"
          }
        }
      }
    }
    """
    state = parse_save_text(text)
    ae = assess_player_ae(
        DiffResult(prev_date="a", curr_date="b", player="NE8", events=[]),
        ae_snapshot=dict(state.countries["NE8"].aggressive_expansion),
        curr=state,
    )
    assert "POM" not in ae.coalition_eligible
    assert "POM" not in ae.coalition_blocked
    assert "STE" in ae.coalition_blocked
