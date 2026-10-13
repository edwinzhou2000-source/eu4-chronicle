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
    assert len(state.wars) >= 1
    byz_wars = [w for w in state.wars if "BYZ" in w.attackers or "BYZ" in w.defenders]
    assert byz_wars
    war = byz_wars[0]
    assert "BYZ" in war.attackers
    assert "TUR" in war.defenders
    assert "ATH" in state.countries["BYZ"].subjects
    assert state.province_names.get(151) == "Constantinople"


def test_province_names_abs_negative_keys_skip_garbled():
    """真档 provinces 键为 -id；乱码 name 不入库。"""
    text = """
    date="1460.6.10"
    player="NED"
    countries={ NED={ government_rank=1 } }
    provinces={
      -54={ name="Stade" }
      -55={ name="\x11Xe" }
    }
    """
    state = parse_save_text(text)
    assert state.province_names.get(54) == "Stade"
    assert 55 not in state.province_names
    assert -54 not in state.province_names


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


def test_development_prefers_raw_over_homeland():
    """UI 总发展度用 raw_development；勿被较小的 development（本土）抢走。"""
    text = """
    date="1460.1.1"
    player="NED"
    countries={
      NED={
        name="Netherlands"
        development=268
        raw_development=431
        owned_provinces={ 1 2 3 }
      }
    }
    """
    state = parse_save_text(text)
    assert state.countries["NED"].development == 431.0


def test_development_falls_back_to_development_field():
    text = """
    date="1460.1.1"
    player="NED"
    countries={
      NED={
        development=218
        owned_provinces={ 1 2 }
      }
    }
    """
    state = parse_save_text(text)
    assert state.countries["NED"].development == 218.0


def test_count_ships_and_regiments_once_not_doubled():
    """真档 navy/army 为重复键块；舰/团只计一次，禁止 35→70 双计。"""
    text = """
    date="1460.6.10"
    player="NE8"
    countries={
      NE8={
        owned_provinces={ 97 }
        navy={
          id={ id=1 type=54 }
          ship={ id={ id=1 type=54 } type="cog" }
          ship={ id={ id=2 type=54 } type="cog" }
          ship={ id={ id=3 type=54 } type="barque" }
        }
        army={
          id={ id=10 type=50 }
          regiment={ id={ id=10 type=50 } type="infantry" }
          regiment={ id={ id=11 type=50 } type="infantry" }
        }
        army={
          id={ id=12 type=50 }
          regiment={ id={ id=12 type=50 } type="cavalry" }
        }
      }
    }
    """
    state = parse_save_text(text)
    c = state.countries["NE8"]
    assert c.navy_size == 3.0
    assert c.army_size == 3.0
