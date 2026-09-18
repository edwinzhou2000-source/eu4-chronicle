"""流水线 mock 验收：成稿可分享、不重复粘贴三角色。"""

from __future__ import annotations

from pathlib import Path

import pytest

from eu4_chronicle.config import Settings
from eu4_chronicle.pipeline import analyze_saves

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


@pytest.mark.asyncio
async def test_analyze_samples_mock():
    settings = Settings(mode="mock", openai_api_key=None)
    report = await analyze_saves(
        SAMPLES / "byz_1444.eu4",
        SAMPLES / "byz_1453.eu4",
        settings=settings,
    )
    assert report.mode == "mock"
    assert report.player == "BYZ"
    assert report.event_count > 0
    roles = [s.role for s in report.sections]
    assert roles == ["historian", "strategist", "diplomat", "editor"]
    assert all(s.mock for s in report.sections)
    md = report.final_markdown
    assert md.startswith("# ")
    assert "## 叙事" in md
    assert "## 战局要点" in md
    assert "## 外交与 AE" in md
    assert "拜占庭" in md
    # 不再使用旧空话
    assert "共录" not in md
    assert "可稽之事" not in md
    # 远东战争不得进入默认成稿
    assert "Ito" not in md and "Shimazu" not in md and "伊藤" not in md and "岛津" not in md


@pytest.mark.asyncio
async def test_editor_does_not_paste_three_roles_verbatim():
    settings = Settings(mode="mock", openai_api_key=None)
    report = await analyze_saves(
        SAMPLES / "byz_1444.eu4",
        SAMPLES / "byz_1453.eu4",
        settings=settings,
    )
    hist = next(s.content for s in report.sections if s.role == "historian")
    strat = next(s.content for s in report.sections if s.role == "strategist")
    dipl = next(s.content for s in report.sections if s.role == "diplomat")
    final = report.final_markdown

    # 成稿不得等于「三段原文简单拼接」
    pasted = f"## 编年叙事\n\n{hist}\n\n## 战局研判\n\n{strat}\n\n## 外交与 AE\n\n{dipl}"
    assert pasted not in final
    # 三角色全文不应作为三个独立大段原样出现
    assert final.count(hist) <= 1
    # 三角色标题旧结构不得出现
    assert "## 编年叙事" not in final
    assert "## 战局研判" not in final


@pytest.mark.asyncio
async def test_readable_province_not_raw_bracket_id():
    settings = Settings(mode="mock", openai_api_key=None)
    report = await analyze_saves(
        SAMPLES / "byz_1444.eu4",
        SAMPLES / "byz_1453.eu4",
        settings=settings,
    )
    md = report.final_markdown
    assert "[317]" not in md
    assert "317" not in md or "许达文迪加尔" in md or "Hudavendigar" in md
