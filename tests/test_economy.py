"""国库 / 月收入 / 月支出 / 净收入：解析、Diff、叙事硬数字。"""

from __future__ import annotations

from pathlib import Path

from eu4_game_report.agents import _narrative_fact_bits, make_brief
from eu4_game_report.diff import diff_states
from eu4_game_report.filter import filter_diff
from eu4_game_report.names import NameResolver
from eu4_game_report.parser import parse_save, parse_save_text

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_parse_economy_from_sample():
    prev = parse_save(SAMPLES / "byz_1444.eu4")
    curr = parse_save(SAMPLES / "byz_1453.eu4")
    a, b = prev.countries["BYZ"], curr.countries["BYZ"]
    assert a.treasury == 45
    assert a.income == 8.5
    assert a.expenses == 7.2
    assert abs(a.net_income - 1.3) < 1e-6
    assert b.treasury == 12
    assert b.income == 11.0
    assert b.expenses == 9.5
    assert abs(b.net_income - 1.5) < 1e-6


def test_parse_economy_ledger_fallback_without_emi():
    text = """
    date="1444.11.11"
    player="TST"
    countries={
      TST={
        name="Test"
        treasury=100
        ledger={
          lastmonthincome=20
          lastmonthexpense=50
          last_months_recurring_income=18
          last_months_recurring_expenses=15
        }
        owned_provinces={ 1 }
      }
    }
    """
    st = parse_save_text(text)
    c = st.countries["TST"]
    assert c.treasury == 100
    assert c.income == 18  # recurring income when EMI missing
    assert c.expenses == 15  # recurring expenses preferred
    assert abs(c.net_income - 3.0) < 1e-6


def test_diff_treasury_and_income_events():
    prev = parse_save(SAMPLES / "byz_1444.eu4")
    curr = parse_save(SAMPLES / "byz_1453.eu4")
    diff = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    kinds = {e.kind for e in diff.events if e.tag == "BYZ"}
    assert "treasury_changed" in kinds
    assert "income_changed" in kinds
    tre = next(e for e in diff.events if e.kind == "treasury_changed")
    assert tre.detail["from"] == 45
    assert tre.detail["to"] == 12
    inc = next(e for e in diff.events if e.kind == "income_changed")
    assert inc.detail["from"] == 8.5
    assert inc.detail["to"] == 11.0
    assert inc.detail["expenses_from"] == 7.2
    assert inc.detail["net_to"] == 1.5


def test_narrative_and_brief_include_economy():
    prev = parse_save(SAMPLES / "byz_1444.eu4")
    curr = parse_save(SAMPLES / "byz_1453.eu4")
    diff = filter_diff(diff_states(prev, curr), prev=prev, curr=curr)
    names = NameResolver()
    bits = _narrative_fact_bits(diff, names)
    joined = "；".join(bits)
    assert "国库" in joined
    assert "月收入" in joined
    assert "月支出" in joined
    assert "净收入" in joined
    brief = make_brief(diff, names=names)
    assert "国库" in brief
    assert "叙事内政硬数字" in brief


def test_parse_real_save_economy_if_present():
    root = Path(
        "/mnt/c/Users/Edwin/Documents/Paradox Interactive/"
        "Europa Universalis IV/save games"
    )
    path = root / "尼德兰1454_02_11.eu4"
    if not path.is_file():
        return
    st = parse_save(path)
    c = st.countries[st.player]
    assert c.treasury > 0
    assert c.income > 0
    assert c.expenses > 0
    # 经常性净收入应接近小正值（上月总支出可能含大额军费，不在此断言）
    assert abs(c.net_income - (c.income - c.expenses)) < 1e-6
