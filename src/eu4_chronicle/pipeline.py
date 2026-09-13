"""编排：parse → diff → 三角色并行 → 主编合成。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from eu4_chronicle.agents import make_brief, run_diplomat, run_editor, run_historian, run_strategist
from eu4_chronicle.config import Settings, get_settings
from eu4_chronicle.diff import diff_states
from eu4_chronicle.models import ChronicleReport, DiffResult, GameState
from eu4_chronicle.parser import parse_save


async def analyze_saves(
    prev: Path | str,
    curr: Path | str,
    *,
    settings: Settings | None = None,
) -> ChronicleReport:
    settings = settings or get_settings()
    prev_state = await asyncio.to_thread(parse_save, Path(prev))
    curr_state = await asyncio.to_thread(parse_save, Path(curr))
    return await analyze_states(prev_state, curr_state, settings=settings)


async def analyze_states(
    prev: GameState,
    curr: GameState,
    *,
    settings: Settings | None = None,
) -> ChronicleReport:
    settings = settings or get_settings()
    diff = await asyncio.to_thread(diff_states, prev, curr)
    return await synthesize(diff, settings=settings)


async def synthesize(diff: DiffResult, *, settings: Settings | None = None) -> ChronicleReport:
    settings = settings or get_settings()
    brief = make_brief(diff)
    mode = settings.resolved_mode()

    sem = asyncio.Semaphore(max(1, settings.agent_concurrency))

    async def _guard(coro):
        async with sem:
            return await coro

    historian, strategist, diplomat = await asyncio.gather(
        _guard(run_historian(settings, diff, brief)),
        _guard(run_strategist(settings, diff, brief)),
        _guard(run_diplomat(settings, diff, brief)),
    )
    editor = await run_editor(settings, diff, brief, historian, strategist, diplomat)

    title = f"{diff.player or 'EU4'} 战报（{diff.prev_date or '?'} → {diff.curr_date or '?'}）"
    return ChronicleReport(
        title=title,
        prev_date=diff.prev_date,
        curr_date=diff.curr_date,
        player=diff.player,
        mode=mode,
        sections=[historian, strategist, diplomat, editor],
        final_markdown=editor.content,
        event_count=len(diff.events),
    )
