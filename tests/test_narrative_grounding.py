"""LLM 成稿叙事段须落地 Diff 硬数字，不得保留提示词示例数。"""

from __future__ import annotations

from eu4_game_report.ae import assess_player_ae
from eu4_game_report.agents import (
    _mock_narrative_paragraph,
    _splice_grounded_narrative,
    make_brief,
)
from eu4_game_report.models import DiffEvent, DiffResult
from eu4_game_report.names import NameResolver


def _diff() -> DiffResult:
    return DiffResult(
        prev_date="1457.4.3",
        curr_date="1460.6.10",
        player="NE8",
        events=[
            DiffEvent(
                kind="province_gained",
                tag="NE8",
                summary="得地",
                detail={"provinces": [54, 55]},
            ),
            DiffEvent(
                kind="manpower_changed",
                tag="NE8",
                summary="人力",
                detail={
                    "from": 17.275,
                    "to": 14.426,
                    "max_from": 21.933,
                    "max_to": 26.078,
                },
            ),
            DiffEvent(
                kind="navy_changed",
                tag="NE8",
                summary="海军",
                detail={"from": 23.0, "to": 35.0},
            ),
            DiffEvent(
                kind="development_changed",
                tag="NE8",
                summary="发展",
                detail={"from": 391.0, "to": 431.0},
            ),
            DiffEvent(
                kind="stability_changed",
                tag="NE8",
                summary="稳定",
                detail={"from": 2, "to": 3},
            ),
        ],
    )


def test_splice_replaces_hallucinated_narrative_numbers():
    names = NameResolver(country_names={"NE8": "尼德兰"}, province_names={54: "施塔德", 55: "奥尔登堡"})
    diff = _diff()
    ae = assess_player_ae(diff)
    hallucinated = """# 尼德兰战报

**时间** 1457.4.3 → 1460.6.10  ·  **主角** 尼德兰

## 叙事

本区间尼德兰北向用兵，取得数处要地。内政方面，当前人力 15.2k→17.8k，人力上限约 42.0k，海军约 12→15，发展度约 180→205，稳定度 +1→+2。本区间共 1 场战事，详见战局。

## 战局要点

- 战争进行中

## 外交与 AE

- 当前未见高 AE
"""
    out = _splice_grounded_narrative(hallucinated, diff, names, ae)
    grounded = _mock_narrative_paragraph(diff, names, ae)
    assert "## 叙事" in out
    assert grounded in out
    assert "15.2k→17.8k" not in out
    assert "42.0k" not in out
    assert "12→15" not in out
    assert "180→205" not in out
    assert "17.3k→14.4k" in out or "17.275" in grounded
    assert "23→35" in out
    assert "391→431" in out
    assert "稳定度 2→3" in out
    assert "施塔德" in out and "奥尔登堡" in out
    # 其它段保留
    assert "## 战局要点" in out
    assert "战争进行中" in out


def test_brief_lists_domestic_hard_numbers():
    names = NameResolver(country_names={"NE8": "尼德兰"})
    diff = _diff()
    brief = make_brief(diff, names=names)
    assert "叙事内政硬数字" in brief
    assert "当前人力" in brief and "人力上限" in brief
    assert "17.3k→14.4k" in brief
    assert "海军约 23→35" in brief
    assert "发展度 391→431" in brief
    assert "稳定度 2→3" in brief
    assert "15.2k→17.8k" not in brief  # 不得再把示例数写进 brief
