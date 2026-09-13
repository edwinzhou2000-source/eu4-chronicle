"""CLI：eu4-chronicle analyze / serve / list-saves。"""

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


@app.command("analyze")
def analyze(
    prev: Path = typer.Option(..., "--prev", exists=True, dir_okay=False, help="较早存档"),
    curr: Path = typer.Option(..., "--curr", exists=True, dir_okay=False, help="较新存档"),
    out: Optional[Path] = typer.Option(None, "--out", help="将最终 Markdown 写入文件"),
    mode: Optional[str] = typer.Option(None, "--mode", help="mock 或 llm（覆盖环境变量）"),
) -> None:
    """解析两档 → Diff → 史官/军师/外交官 → 主编合成。"""
    settings = get_settings()
    if mode:
        settings = settings.model_copy(update={"mode": mode})
    report = asyncio.run(analyze_saves(prev, curr, settings=settings))
    typer.echo(f"# 模式: {report.mode} | 事件: {report.event_count} | 玩家: {report.player}")
    typer.echo("")
    for section in report.sections:
        if section.role == "editor":
            continue
        typer.echo(f"## {section.title}{'（mock）' if section.mock else ''}")
        typer.echo(section.content)
        typer.echo("")
    typer.echo("---")
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
