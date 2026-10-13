"""事件和谈残留的幽灵 active_war：对侧全无地则剔除。"""

from __future__ import annotations

from pathlib import Path

import pytest

from eu4_chronicle.parser import is_ghost_active_war, parse_save, parse_save_text


def test_prune_when_all_foes_landless():
    text = """
    date="1460.6.10"
    player="NE8"
    ironman=no
    countries={
      NE8={ owned_provinces={ 97 98 } raw_development=400 }
      EN3={ owned_provinces={ 236 } }
      HOL={ owned_provinces={ } }
      BRB={ }
    }
    active_war={
      name="Ghost Dutch War"
      attackers={ NE8 EN3 }
      defenders={ HOL BRB }
      last_warscore_quarter=100
      attacker_score=25
      participants={ value=1 tag="NE8" side="attackers" }
      participants={ value=1 tag="EN3" side="attackers" }
      participants={ value=1 tag="HOL" side="defenders" }
      participants={ value=1 tag="BRB" side="defenders" }
    }
    """
    state = parse_save_text(text)
    assert state.wars == []
    assert state.raw_meta.get("ghost_wars_pruned") == 1


def test_keep_when_at_least_one_foe_alive():
    text = """
    date="1460.6.10"
    player="NE8"
    ironman=no
    countries={
      NE8={ owned_provinces={ 97 } }
      GOT={ owned_provinces={ 25 } }
      HSA={ owned_provinces={ } }
    }
    active_war={
      name="Real War"
      attackers={ NE8 }
      defenders={ GOT HSA }
      last_warscore_quarter=45
      participants={ value=1 tag="NE8" side="attackers" }
      participants={ value=1 tag="GOT" side="defenders" }
      participants={ value=1 tag="HSA" side="defenders" }
    }
    """
    state = parse_save_text(text)
    assert len(state.wars) == 1
    assert state.wars[0].name == "Real War"
    assert not is_ghost_active_war(state.wars[0], state)


NED_SAVE = Path(
    "/mnt/c/Users/Edwin/Documents/Paradox Interactive/"
    "Europa Universalis IV/save games/尼德兰1460_06_10.eu4"
)


@pytest.mark.skipif(not NED_SAVE.is_file(), reason="本机无尼德兰真档")
def test_real_ned_save_has_no_player_ghost_active_war():
    state = parse_save(NED_SAVE)
    player = state.player
    player_wars = [
        w
        for w in state.wars
        if player in w.attackers or player in w.defenders
    ]
    assert player_wars == []
