"""流水线 mock 验收。"""

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
    assert "## 编年叙事" in md
    assert "## 战局研判" in md
    assert "## 外交与 AE" in md
    assert "## 主编按语" in md
    assert "BYZ" in md
