"""解析关键路径测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from eu4_chronicle.parser import IronmanSaveError, parse_save, parse_save_text
from eu4_chronicle.parser.clausewitz import parse_clausewitz_v2

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_clausewitz_object_and_list():
    text = """
    date="1444.11.11"
    player="BYZ"
    countries={
      BYZ={
        allies={ WAL TUR }
        development=10
      }
    }
    """
    root = parse_clausewitz_v2(text)
    assert root.get_str("date") == "1444.11.11"
    assert root.get_str("player") == "BYZ"
    byz = root.get_object("countries").get_object("BYZ")
    assert byz.get_float("development") == 10
    assert byz.get_list("allies") == ["WAL", "TUR"]


def test_parse_sample_prev():
    state = parse_save(SAMPLES / "byz_1444.eu4")
    assert state.date == "1444.11.11"
    assert state.player == "BYZ"
    assert not state.ironman
    byz = state.countries["BYZ"]
    assert 151 in byz.owned_provinces
    assert "WAL" in byz.allies
    assert "TUR" in byz.rivals
    assert byz.monarch is not None
    assert byz.monarch.mil == 4
    assert byz.aggressive_expansion.get("TUR") == 5


def test_parse_sample_curr_wars():
    state = parse_save(SAMPLES / "byz_1453.eu4")
    assert state.date == "1453.5.29"
    assert len(state.wars) == 1
    war = state.wars[0]
    assert "BYZ" in war.attackers
    assert "TUR" in war.defenders
    assert "ATH" in state.countries["BYZ"].subjects


def test_ironman_binary_rejected(tmp_path: Path):
    path = tmp_path / "iron.eu4"
    path.write_bytes(b"EU4bin" + b"\x00" * 100)
    with pytest.raises(IronmanSaveError):
        parse_save(path)


def test_zip_save(tmp_path: Path):
    import zipfile

    content = Path(SAMPLES / "byz_1444.eu4").read_text(encoding="utf-8")
    zpath = tmp_path / "zipped.eu4"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("gamestate", content)
        zf.writestr("meta", 'date="1444.11.11"\n')
    state = parse_save(zpath)
    assert state.player == "BYZ"


def test_parse_save_text_roundtrip_fields():
    text = """
    date="1500.1.1"
    player="FRA"
    countries={
      FRA={
        name="France"
        religion="catholic"
        owned_provinces={ 183 184 }
        core_provinces={ 183 }
        technology={ adm_tech=5 dip_tech=5 mil_tech=6 }
      }
    }
    """
    state = parse_save_text(text)
    assert state.countries["FRA"].technology["mil_tech"] == 6
    assert state.countries["FRA"].cores == [183]
