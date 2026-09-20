"""本机 FastAPI：列表存档、触发分析、返回战报；并托管选档前端。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from eu4_chronicle.agents.llm import LLMError
from eu4_chronicle.config import format_save_dir, get_settings
from eu4_chronicle.pipeline import analyze_saves

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"

app = FastAPI(
    title="EU4 Chronicle",
    description="本机 EU4 存档 Diff 与多角色战报服务（仅绑定本机回环地址）",
    version="0.1.0",
)


@app.get("/")
def ui_index() -> FileResponse:
    """选档 / 出战报前端（简体中文）。"""
    if not INDEX_HTML.is_file():
        raise HTTPException(status_code=500, detail="前端页面缺失：static/index.html")
    return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")


class AnalyzeRequest(BaseModel):
    prev: str = Field(..., description="较早存档文件名或绝对路径")
    curr: str = Field(..., description="较新存档文件名或绝对路径")
    mode: str | None = Field(None, description="mock 或 llm")
    include_global: bool = Field(
        False,
        description="为 True 时保留全球无关事件；默认玩家中心过滤",
    )


def _resolve_save(path_or_name: str) -> Path:
    settings = get_settings()
    p = Path(path_or_name)
    if p.is_file():
        return p
    candidate = settings.save_dir / path_or_name
    if candidate.is_file():
        return candidate
    raise HTTPException(status_code=404, detail=f"找不到存档: {path_or_name}")


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    save_dir = format_save_dir(settings.save_dir)
    return {
        "ok": True,
        "mode": settings.resolved_mode(),
        "save_dir": save_dir,
        "save_dir_exists": Path(save_dir).exists(),
    }


@app.get("/saves")
def list_saves() -> dict:
    settings = get_settings()
    directory = settings.save_dir
    save_dir_text = format_save_dir(directory)
    if not directory.exists():
        raise HTTPException(
            status_code=400,
            detail=(
                f"存档目录不存在: {save_dir_text}。"
                "请在项目根目录 .env 设置 EU4_SAVE_DIR"
                "（WSL 示例见 README），或确认 Windows 存档已挂到 /mnt/c/Users/...。"
            ),
        )
    files = []
    for f in sorted(directory.glob("*.eu4")):
        files.append(
            {
                "name": f.name,
                "path": str(f),
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
            }
        )
    return {"save_dir": save_dir_text, "files": files}


@app.post("/analyze")
async def analyze(body: AnalyzeRequest) -> dict:
    settings = get_settings()
    if body.mode:
        settings = settings.model_copy(update={"mode": body.mode})
    prev = _resolve_save(body.prev)
    curr = _resolve_save(body.curr)
    try:
        report = await analyze_saves(
            prev,
            curr,
            settings=settings,
            include_global=body.include_global,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return report.model_dump()
