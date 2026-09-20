"""CLI：eu4-chronicle analyze / dump-war-scores / serve / list-saves。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer

from eu4_chronicle.config import get_settings
from eu4_chronicle.pipeline import analyze_saves

app = typer.Typer(
    name="eu4-chronicle",
    help="EU4 本机存档 Diff 与多角色战报（白银段）",
    no_args_is_help=True,
)


@app.command("list-saves")
def list_saves(
    save_dir: Optional[Path] = typer.Option(
        None,
        "--save-dir",
        help="存档目录；默认读 EU4_SAVE_DIR 或 Windows 默认路径",
    ),
) -> None:
    """列出目录中的 .eu4 文件。"""
    settings = get_settings()
    directory = Path(save_dir) if save_dir else settings.save_dir
    if not directory.exists():
        typer.echo(f"存档目录不存在: {directory}", err=True)
        raise typer.Exit(code=1)
    files = sorted(directory.glob("*.eu4"))
    if not files:
        typer.echo(f"未找到 .eu4：{directory}")
        return
    for f in files:
        typer.echo(f"{f.name}\t{f.stat().st_size}\t{f}")


@app.command("dump-war-scores")
def dump_war_scores_cmd(
    save: Path = typer.Option(..., "--save", exists=True, dir_okay=False, help="要检查的 .eu4 存档"),
    all_wars: bool = typer.Option(
        False,
        "--all-wars",
        help="输出全部 active_war（默认只打玩家参与的）",
    ),
) -> None:
    """打印玩家参与战争的原始战分相关字段，便于贴回钉死总战分/ticking 映射。"""
    from eu4_chronicle.parser import IronmanSaveError, SaveParseError, dump_war_scores

    try:
        text = dump_war_scores(save, player_only=not all_wars)
    except IronmanSaveError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    except SaveParseError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(text)


@app.command("analyze")
def analyze(
    prev: Path = typer.Option(..., "--prev", exists=True, dir_okay=False, help="较早存档"),
    curr: Path = typer.Option(..., "--curr", exists=True, dir_okay=False, help="较新存档"),
    out: Optional[Path] = typer.Option(None, "--out", help="将最终 Markdown 写入文件"),
    mode: Optional[str] = typer.Option(None, "--mode", help="mock 或 llm（覆盖环境变量）"),
    include_global: bool = typer.Option(
        False,
        "--include-global",
        help="保留全球无关战争/远方内政（默认只保留玩家强相关事件）",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="额外打印史官/军师/外交官草稿，以及 curr 档原始战分字段一行（调试用）",
    ),
) -> None:
    """解析两档 → 玩家过滤 Diff → 史官/军师/外交官 → 主编成稿。"""
    from eu4_chronicle.agents.llm import LLMError

    settings = get_settings()
    if mode:
        settings = settings.model_copy(update={"mode": mode})
    try:
        report = asyncio.run(
            analyze_saves(prev, curr, settings=settings, include_global=include_global)
        )
    except LLMError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        f"# 模式: {report.mode} | 事件: {report.event_count} | 玩家: {report.player}"
        f"{' | 含全球' if include_global else ' | 玩家过滤'}"
    )
    typer.echo("")
    if verbose:
        from eu4_chronicle.parser import parse_save

        for section in report.sections:
            if section.role == "editor":
                continue
            typer.echo(f"## {section.title}{'（mock）' if section.mock else ''}")
            typer.echo(section.content)
            typer.echo("")
        typer.echo("---")
        typer.echo("")
        try:
            curr_state = parse_save(curr)
            for w in curr_state.wars:
                if report.player:
                    in_war = (
                        report.player in w.attackers
                        or report.player in w.defenders
                        or any(p.tag == report.player for p in w.participants)
                    )
                    if not in_war:
                        continue
                bits = [
                    f"war={w.name!r}",
                    f"last_warscore_quarter={w.last_warscore_quarter}",
                    f"last_warscore_year={w.last_warscore_year}",
                    f"attacker_score={w.attacker_score}",
                    f"defender_score={w.defender_score}",
                    f"total_src={w.total_score_source}",
                    f"total={w.total_attacker_score}",
                    f"ticking_src={w.ticking_score_source}",
                    f"ticking={w.ticking_attacker_score}",
                ]
                if w.raw_score_fields:
                    compact = ", ".join(
                        f"{k}={v}" for k, v in sorted(w.raw_score_fields.items())[:24]
                    )
                    bits.append(f"raw=[{compact}]")
                typer.echo("raw_war_scores: " + " | ".join(bits))
        except Exception as exc:  # noqa: BLE001 — verbose 辅助，不影响成稿
            typer.echo(f"raw_war_scores: (无法读取 curr: {exc})")
        typer.echo("")
        typer.echo("---")
        typer.echo("")
        typer.echo(
            f"(完整原始字段: uv run eu4-chronicle dump-war-scores --save {curr})",
            err=True,
        )

    typer.echo(report.final_markdown)
    if out:
        out.write_text(report.final_markdown, encoding="utf-8")
        typer.echo(f"\n已写入 {out}", err=True)


@app.command("serve")
def serve(
    host: Optional[str] = typer.Option(None, "--host"),
    port: Optional[int] = typer.Option(None, "--port"),
) -> None:
    """启动本机 FastAPI（默认 127.0.0.1:18765）。"""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "eu4_chronicle.server:app",
        host=host or settings.host,
        port=port or settings.port,
        reload=False,
    )


if __name__ == "__main__":
    app()
