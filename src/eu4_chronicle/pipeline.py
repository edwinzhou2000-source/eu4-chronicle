"""编排：parse → diff → 玩家过滤 → 可读化 → 三角色并行 → 主编成稿。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from eu4_chronicle.ae import AeAssessment, assess_player_ae
from eu4_chronicle.agents import make_brief, run_diplomat, run_editor, run_historian, run_strategist
from eu4_chronicle.config import Settings, get_settings
from eu4_chronicle.diff import diff_states
from eu4_chronicle.filter import filter_diff
from eu4_chronicle.models import ChronicleReport, DiffResult, GameState
from eu4_chronicle.names import NameResolver
from eu4_chronicle.parser import parse_save


async def analyze_saves(
    prev: Path | str,
    curr: Path | str,
    *,
    settings: Settings | None = None,
    include_global: bool = False,
) -> ChronicleReport:
    settings = settings or get_settings()
    prev_state = await asyncio.to_thread(parse_save, Path(prev))
    curr_state = await asyncio.to_thread(parse_save, Path(curr))
    return await analyze_states(
        prev_state,
        curr_state,
        settings=settings,
        include_global=include_global,
    )


async def analyze_states(
    prev: GameState,
    curr: GameState,
    *,
    settings: Settings | None = None,
    include_global: bool = False,
) -> ChronicleReport:
    settings = settings or get_settings()
    raw = await asyncio.to_thread(diff_states, prev, curr)
    raw_count = len(raw.events)
    filtered = filter_diff(raw, prev=prev, curr=curr, include_global=include_global)
    filtered = filtered.model_copy(
        update={
            "raw_event_count": raw_count,
            "filtered": not include_global,
        }
    )
    names = NameResolver.from_states(prev, curr)
    readable = names.rewrite_diff(filtered)
    player = readable.player
    ae_snapshot: dict[str, float] = {}
    if player and player in curr.countries:
        ae_snapshot = dict(curr.countries[player].aggressive_expansion or {})
    ae = assess_player_ae(readable, ae_snapshot=ae_snapshot, country_label=names.country)
    return await synthesize(readable, settings=settings, names=names, ae=ae)


async def synthesize(
    diff: DiffResult,
    *,
    settings: Settings | None = None,
    names: NameResolver | None = None,
    ae: AeAssessment | None = None,
) -> ChronicleReport:
    settings = settings or get_settings()
    names = names or NameResolver()
    if ae is None:
        ae = assess_player_ae(diff, country_label=names.country)
    brief = make_brief(diff, names=names, ae=ae)
    mode = settings.resolved_mode()

    sem = asyncio.Semaphore(max(1, settings.agent_concurrency))

    async def _guard(coro):
        async with sem:
            return await coro

    historian, strategist, diplomat = await asyncio.gather(
        _guard(run_historian(settings, diff, brief, names=names, ae=ae)),
        _guard(run_strategist(settings, diff, brief, names=names, ae=ae)),
        _guard(run_diplomat(settings, diff, brief, names=names, ae=ae)),
    )
    editor = await run_editor(
        settings, diff, brief, historian, strategist, diplomat, names=names, ae=ae
    )

    player_label = names.country(diff.player) if diff.player else "EU4"
    title = f"{player_label} 战报（{diff.prev_date or '?'} → {diff.curr_date or '?'}）"
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
