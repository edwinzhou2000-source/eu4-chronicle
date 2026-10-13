"""previous_war：解析、Diff 期内结束、过滤与战局要点。"""

from __future__ import annotations

from pathlib import Path

import pytest

from eu4_chronicle.ae import assess_player_ae
from eu4_chronicle.agents import _mock_war_section, make_brief
from eu4_chronicle.diff import diff_states
from eu4_chronicle.filter import filter_diff
from eu4_chronicle.names import NameResolver
from eu4_chronicle.parser import parse_save_text
from eu4_chronicle.warscore import assess_player_wars, war_guidance_lines

PREV_SAVE = """
date="1447.6.1"
player="TEU"
countries={
  TEU={ name="Teutonic Order" development=90 owned_provinces={ 43 } }
  POL={ name="Poland" development=200 owned_provinces={ 254 } }
  WOL={ name="Wolgast" development=20 owned_provinces={ 47 } }
}
previous_war={
  name="Old Distant War"
  history={
    1400.1.1={ add_attacker="ENG" }
    1400.1.1={ add_defender="FRA" }
  }
}
"""

CURR_SAVE = """
date="1468.6.2"
player="TEU"
countries={
  TEU={ name="Teutonic Order" development=120 owned_provinces={ 43 254 } }
  POL={ name="Poland" development=180 owned_provinces={ 262 } }
  WOL={ name="Wolgast" development=20 owned_provinces={ 47 } }
}
previous_war={
  name="Old Distant War"
  history={
    1400.1.1={ add_attacker="ENG" }
    1400.1.1={ add_defender="FRA" }
  }
}
previous_war={
  name="Teutonic Conquest of Naklo"
  history={
    1448.3.1={ add_attacker="TEU" }
    1448.3.1={ add_defender="POL" }
    1450.6.12={
      battle={
        name="Naklo"
        location=254
        result=yes
        attacker={ infantry=12000 losses=2100 country="TEU" }
        defender={ infantry=9000 losses=6400 country="POL" }
      }
    }
    1454.1.1={ rem_attacker="TEU" }
    1454.1.1={ rem_defender="POL" }
  }
  participants={ value=151.8 tag="TEU" war_score=0.000 }
  participants={ value=318.4 tag="POL" war_score=0.000 }
}
previous_war={
  name="Teutonic Conquest of Stargard"
  history={
    1455.1.1={ add_attacker="TEU" }
    1455.1.1={ add_defender="POL" }
    1458.1.1={ rem_attacker="TEU" }
    1458.1.1={ rem_defender="POL" }
  }
  participants={ value=113.7 tag="TEU" war_score=0.000 }
  participants={ value=40.0 tag="POL" war_score=0.000 }
}
previous_war={
  name="Humiliation of Wolgast"
  history={
    1460.1.1={ add_attacker="TEU" }
    1460.1.1={ add_defender="WOL" }
    1461.1.1={ rem_attacker="TEU" }
    1461.1.1={ rem_defender="WOL" }
  }
  participants={ value=65.3 tag="TEU" war_score=0.000 }
  participants={ value=25.7 tag="WOL" war_score=0.000 }
}
"""


def test_parse_previous_wars():
    state = parse_save_text(CURR_SAVE)
    names = {w.name for w in state.previous_wars}
    assert "Teutonic Conquest of Naklo" in names
    assert "Teutonic Conquest of Stargard" in names
    assert "Humiliation of Wolgast" in names
    naklo = next(w for w in state.previous_wars if "Naklo" in w.name)
    # rem 清空后须回退 lifetime 攻守，不能丢掉 TEU
    assert "TEU" in naklo.attackers
    assert "POL" in naklo.defenders
    assert any(b.name == "Naklo" for b in naklo.battles)
    assert any(p.tag == "TEU" for p in naklo.participants)
    assert state.wars == []


def test_diff_previous_war_set_difference_emits_war_ended():
    prev = parse_save_text(PREV_SAVE)
    curr = parse_save_text(CURR_SAVE)
    result = diff_states(prev, curr)
    ended = [e for e in result.events if e.kind == "war_ended"]
    names = {str((e.detail or {}).get("name")) for e in ended}
    assert "Teutonic Conquest of Naklo" in names
    assert "Teutonic Conquest of Stargard" in names
    assert "Humiliation of Wolgast" in names
    assert "Old Distant War" not in names
    naklo_ev = next(e for e in ended if "Naklo" in str((e.detail or {}).get("name")))
    assert (naklo_ev.detail or {}).get("source") == "previous_war"
    assert "TEU" in (naklo_ev.detail or {}).get("attackers", [])


def test_filter_keeps_player_previous_war_ended():
    prev = parse_save_text(PREV_SAVE)
    curr = parse_save_text(CURR_SAVE)
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    ended = [e for e in filtered.events if e.kind == "war_ended"]
    names = {str((e.detail or {}).get("name")) for e in ended}
    assert "Naklo" in "".join(names)
    assert "Stargard" in "".join(names)
    assert "Wolgast" in "".join(names)


def test_assess_and_mock_war_lists_ended_without_force_dump():
    prev = parse_save_text(PREV_SAVE)
    curr = parse_save_text(CURR_SAVE)
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    # 附加编制跳变：无总战分时不得塞进战局要点
    from eu4_chronicle.models import DiffEvent

    filtered.events.append(
        DiffEvent(
            kind="army_changed",
            tag="TEU",
            summary="陆军编制 32→66",
            detail={"from": 32.0, "to": 66.0},
        )
    )
    filtered.events.append(
        DiffEvent(
            kind="manpower_changed",
            tag="TEU",
            summary="当前人力 15.2k→17.8k",
            detail={"from": 15.2, "to": 17.8},
        )
    )
    assessment = assess_player_wars(filtered)
    assert assessment.standings
    assert any("Naklo" in s.war_name for s in assessment.standings)
    guidance = "\n".join(war_guidance_lines(assessment))
    assert guidance.startswith("「")
    assert "本区间无玩家参与的可稽战争" not in guidance
    assert "Naklo" in guidance
    assert "禁止假称" in guidance

    names = NameResolver(country_names={"TEU": "条顿骑士团", "POL": "波兰", "WOL": "沃尔加斯特"})
    ae = assess_player_ae(filtered)
    war = _mock_war_section(filtered, names, ae, heading=False)
    assert "Naklo" in war or "纳克洛" in war or "Conquest" in war
    assert "无可稽战争" not in war
    assert "陆军编制" not in war
    assert "15.2" not in war

    brief = make_brief(filtered, names=names, ae=ae)
    assert "Naklo" in brief
    assert "禁止假称" in brief


def test_active_war_ended_dedupes_against_previous():
    """从 active 消失并发出的 war_ended 不因 previous 差集重复。"""
    prev_text = """
date="1450.1.1"
player="TEU"
countries={ TEU={ development=90 } POL={ development=200 } }
active_war={
  name="Teutonic Conquest of Naklo"
  history={
    1448.3.1={ add_attacker="TEU" }
    1448.3.1={ add_defender="POL" }
  }
}
"""
    curr_text = """
date="1468.6.2"
player="TEU"
countries={ TEU={ development=120 } POL={ development=180 } }
previous_war={
  name="Teutonic Conquest of Naklo"
  history={
    1448.3.1={ add_attacker="TEU" }
    1448.3.1={ add_defender="POL" }
  }
}
"""
    result = diff_states(parse_save_text(prev_text), parse_save_text(curr_text))
    ended = [e for e in result.events if e.kind == "war_ended"]
    naklo = [e for e in ended if (e.detail or {}).get("name") == "Teutonic Conquest of Naklo"]
    assert len(naklo) == 1
    assert (naklo[0].detail or {}).get("source") == "active_war"


def test_optional_real_teu_saves_detect_naklo():
    """若本机有条顿 1447→1468 真档，过滤后应含 Naklo 等结束战争。"""
    from eu4_chronicle.parser import parse_save

    candidates: list[Path] = [
        Path.home()
        / "Documents"
        / "Paradox Interactive"
        / "Europa Universalis IV"
        / "save games",
    ]
    users = Path("/mnt/c/Users")
    if users.is_dir():
        for base in users.iterdir():
            p = (
                base
                / "Documents"
                / "Paradox Interactive"
                / "Europa Universalis IV"
                / "save games"
            )
            if p.is_dir():
                candidates.append(p)
    prev_path = curr_path = None
    for folder in candidates:
        if not folder.is_dir():
            continue
        teu_1447 = sorted(
            f
            for f in folder.glob("*.eu4")
            if "1447" in f.name
            and ("teu" in f.name.lower() or "teutonic" in f.name.lower())
            and "backup" not in f.name.lower()
        )
        teu_1468 = sorted(
            f
            for f in folder.glob("*.eu4")
            if "1468" in f.name
            and ("teu" in f.name.lower() or "teutonic" in f.name.lower())
            and "backup" not in f.name.lower()
        )
        # 优先 1447_06_01（计划对照档），否则取最早一份
        for f in teu_1447:
            if "06_01" in f.name or "06.01" in f.name:
                prev_path = f
                break
        if prev_path is None and teu_1447:
            prev_path = teu_1447[0]
        if teu_1468:
            curr_path = teu_1468[0]
        if prev_path and curr_path:
            break
    if not prev_path or not curr_path:
        pytest.skip("未找到 Teutonic 1447/1468 真档")

    prev = parse_save(prev_path)
    curr = parse_save(curr_path)
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    blob = " ".join(
        str((e.detail or {}).get("name") or "")
        for e in filtered.events
        if e.kind == "war_ended"
    )
    assert "Naklo" in blob or "Stargard" in blob
