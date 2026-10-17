"""附庸类型（dependency.subject_type）与附庸发展度叙事。"""

from __future__ import annotations

from eu4_game_report.agents import _mock_diplo_section, _narrative_fact_bits, make_brief
from eu4_game_report.ae import assess_player_ae
from eu4_game_report.diff import diff_states
from eu4_game_report.filter import filter_diff
from eu4_game_report.names import NameResolver, subject_type_label
from eu4_game_report.parser import parse_save_text


PREV = """
date="1444.11.11"
player="HOL"
countries={
  HOL={
    name="Holland"
    development=50
    subjects={ }
    owned_provinces={ 97 }
  }
  PIC={
    name="Picardy"
    development=40
    owned_provinces={ 89 }
  }
  FLA={
    name="Flanders"
    development=30
    owned_provinces={ 90 }
  }
}
diplomacy={
}
"""

CURR = """
date="1450.1.1"
player="HOL"
countries={
  HOL={
    name="Holland"
    development=55
    subjects={ PIC FLA }
    owned_provinces={ 97 }
  }
  PIC={
    name="Picardy"
    development=52
    owned_provinces={ 89 }
  }
  FLA={
    name="Flanders"
    development=33
    owned_provinces={ 90 }
  }
}
diplomacy={
  dependency={
    first="HOL"
    second="PIC"
    subject_type="vassal"
  }
  dependency={
    first="HOL"
    second="FLA"
    subject_type="DD_fanwang_subject"
  }
}
"""


def test_subject_type_label_vanilla_and_mod():
    assert subject_type_label("vassal") == "附庸"
    assert subject_type_label("march") == "卫戍"
    assert subject_type_label("personal_union") == "联合统治"
    # Mod 无中文映射时保留原文 id
    assert subject_type_label("DD_fanwang_subject") == "DD_fanwang_subject"


def test_parse_subject_types_from_dependency():
    curr = parse_save_text(CURR)
    hol = curr.countries["HOL"]
    assert set(hol.subjects) == {"PIC", "FLA"}
    assert hol.subject_types["PIC"] == "vassal"
    assert hol.subject_types["FLA"] == "DD_fanwang_subject"


def test_subject_changed_detail_has_types():
    prev = parse_save_text(PREV)
    curr = parse_save_text(CURR)
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    sub = next(e for e in filtered.events if e.kind == "subject_changed")
    assert set(sub.detail.get("gained") or []) == {"PIC", "FLA"}
    assert (sub.detail.get("gained_types") or {}).get("PIC") == "vassal"
    assert (sub.detail.get("gained_types") or {}).get("FLA") == "DD_fanwang_subject"


def test_subject_development_in_narrative_and_brief():
    prev = parse_save_text(PREV)
    curr = parse_save_text(CURR)
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    kinds = [e.kind for e in filtered.events]
    assert "subject_development_changed" in kinds
    names = NameResolver(
        country_names={"HOL": "荷兰", "PIC": "皮卡第", "FLA": "佛兰德"}
    )
    bits = "；".join(_narrative_fact_bits(filtered, names))
    assert "附庸 2 国" in bits
    assert "发展度合计" in bits
    assert "70→85" in bits or "70.0→85.0" in bits
    assert "附庸皮卡第" not in bits
    assert "DD_fanwang_subject" not in bits

    brief = make_brief(filtered, names=names)
    assert "附庸 2 国" in brief
    assert "可靠战分" not in brief

    ae = assess_player_ae(filtered)
    diplo = _mock_diplo_section(filtered, names, ae, heading=False)
    assert "收附" in diplo
    assert "皮卡第（附庸）" in diplo
    assert "佛兰德（DD_fanwang_subject）" in diplo


def test_subject_dev_is_sum_not_per_country():
    """只写附庸数量与发展度合计；旧值用该国当时发展度。"""
    prev = parse_save_text(PREV)
    curr = parse_save_text(CURR)
    filtered = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    evs = [e for e in filtered.events if e.kind == "subject_development_changed"]
    assert len(evs) == 1
    detail = evs[0].detail
    assert detail["subject_count"] == 2
    assert detail["from"] == 70
    assert detail["to"] == 85
