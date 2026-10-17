"""active_war 攻守补全与乱码战名可读化。"""

from __future__ import annotations

from eu4_game_report.names.wars import _is_garbled_war_name, translate_war_name
from eu4_game_report.parser import parse_save_text


def test_merge_defenders_from_participant_sides():
    text = """
    date="1460.6.10"
    player="NE8"
    ironman=no
    countries={
      NE8={ name="Netherlands" owned_provinces={ 97 } raw_development=431 development=268 }
      HOL={ name="Holland" owned_provinces={ 98 } }
      EN3={ name="EN3" owned_provinces={ 99 } }
    }
    active_war={
      name="garbled"
      attackers={ NE8 EN3 }
      defenders={ }
      attacker_score=25.0
      last_warscore_quarter=100.0
      participants={ value=10 tag="NE8" side="attackers" war_score=0 }
      participants={ value=5 tag="EN3" side="attackers" war_score=0 }
      participants={ value=20 tag="HOL" side="defenders" war_score=0 }
      history={
        1458.1.1={ add_attacker="NE8" add_attacker="EN3" add_defender="HOL" }
      }
    }
    """
    # force garbled-looking name via private-use chars
    text = text.replace('name="garbled"', 'name="\ue000\ue001\ue002\ue003"')
    state = parse_save_text(text)
    assert state.countries["NE8"].development == 431.0
    assert len(state.wars) == 1
    w = state.wars[0]
    assert "NE8" in w.attackers and "EN3" in w.attackers
    assert "HOL" in w.defenders
    zh = translate_war_name(w.name, attackers=w.attackers, defenders=w.defenders)
    assert "HOL" in zh or "荷兰" in zh or "Holland" in zh or "对" in zh
    assert _is_garbled_war_name(w.name)


def test_filter_keeps_war_when_player_only_on_attacker_list_after_merge():
    from eu4_game_report.diff import diff_states
    from eu4_game_report.filter import filter_diff
    from eu4_game_report.parser import parse_save_text

    prev = parse_save_text(
        """
        date="1457.1.1" player="NE8" ironman=no
        countries={ NE8={ owned_provinces={ 1 } } HOL={ owned_provinces={ 2 } } }
        """
    )
    curr = parse_save_text(
        """
        date="1460.1.1" player="NE8" ironman=no
        countries={
          NE8={ owned_provinces={ 1 } raw_development=400 }
          HOL={ owned_provinces={ 2 } }
          EN3={ owned_provinces={ 3 } }
        }
        active_war={
          name="Dutch Conquest of Holland"
          attackers={ NE8 EN3 }
          defenders={ }
          last_warscore_quarter=100
          attacker_score=25
          participants={ value=1 tag="NE8" side="attackers" }
          participants={ value=1 tag="EN3" side="attackers" }
          participants={ value=1 tag="HOL" side="defenders" }
        }
        """
    )
    raw = diff_states(prev, curr)
    filt = filter_diff(raw, prev=prev, curr=curr)
    wars = [e for e in filt.events if e.kind in {"war_started", "war_score_changed"}]
    assert wars
    ended_or_started = next(e for e in filt.events if e.kind == "war_started")
    assert "HOL" in (ended_or_started.detail.get("defenders") or [])
    assert "NE8" in (ended_or_started.detail.get("attackers") or [])


def test_original_defender_leads_and_loi_is_isles_not_lorraine():
    text = """
    date="1482.8.1"
    player="NE8"
    countries={
      NE8={ name="Netherlands" owned_provinces={ 1 } }
      ALE={ name="Alencon" owned_provinces={ 2 } }
      LOI={ name="LOI" owned_provinces={ 3 } }
      ASU={ name="ASU" owned_provinces={ 4 } }
      LOR={ name="LOR" owned_provinces={ 5 } }
    }
    previous_war={
      name="garbled"
      original_attacker="NE8"
      original_defender="LOI"
      outcome=2
      action=1482.8.1
      attackers={ ALE NE8 }
      defenders={ ASU LOI }
      history={
        1480.1.1={ add_attacker="NE8" add_attacker="ALE" add_defender="LOI" add_defender="ASU" }
        1482.8.1={ rem_attacker="NE8" rem_attacker="ALE" rem_defender="LOI" rem_defender="ASU" }
      }
    }
    """
    state = parse_save_text(text)
    w = state.previous_wars[0]
    assert w.attackers[0] == "NE8"
    assert w.defenders[0] == "LOI"
    assert w.original_defender == "LOI"
    from eu4_game_report.names import NameResolver

    names = NameResolver()
    assert names.country("LOI") == "群岛"
    assert names.country("LOR") == "洛林"
    zh = names.war(w.name, attackers=w.attackers, defenders=w.defenders)
    assert "群岛" in zh
    assert "洛林" not in zh
    assert "阿朗松" not in zh

