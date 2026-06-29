"""Thin web UI over the existing CLI pipeline.

Run from the project root with:
    uvicorn candidate_transformer.ui:app --reload

The pipeline code (adapters, merge, projection) is unchanged — this module
only wires HTTP requests to the same functions the CLI calls.
"""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .adapters.ats_adapter import extract_ats
from .adapters.csv_adapter import extract_csv
from .adapters.github_adapter import extract_github
from .adapters.notes_adapter import extract_notes
from .merge.engine import merge_fragments
from .models.canonical import MergeState
from .models.config import ProjectionConfig
from .projection.engine import ProjectionError, ProjectionValidationError, project

app = FastAPI(title="Candidate Transformer")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _configs_dir() -> Path:
    """Locate configs/ from CWD (project root) or data/configs/ fallback."""
    for candidate in [
        Path.cwd() / "configs",
        Path.cwd() / "data" / "configs",
    ]:
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        "configs/ directory not found — run uvicorn from the project root."
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@app.post("/run", response_class=HTMLResponse)
async def run_pipeline(
    request: Request,
    sources: list[UploadFile] = File(default=[]),
    config: str = Form(default="default"),
) -> HTMLResponse:
    ctx: dict = {"request": request, "config": config}

    real_uploads = [f for f in sources if f.filename]
    if not real_uploads:
        ctx["error"] = "Please upload at least one source file."
        return templates.TemplateResponse(request, "index.html", ctx)

    # Load chosen config from configs/ directory
    try:
        proj_config = ProjectionConfig.model_validate_json(
            (_configs_dir() / f"{config}.json").read_text()
        )
    except Exception as exc:
        ctx["error"] = f"Could not load '{config}' config: {exc}"
        return templates.TemplateResponse(request, "index.html", ctx)

    # Save uploads to a temp dir, extract fragment groups, then clean up
    all_groups: list[list] = []
    file_log: list[tuple[str, int]] = []

    with tempfile.TemporaryDirectory() as tmp:
        for upload in real_uploads:
            dest = Path(tmp) / (upload.filename or "upload")
            dest.write_bytes(await upload.read())
            groups = _detect_and_extract(dest)
            all_groups.extend(groups)
            file_log.append((upload.filename, len(groups)))

    # Merge across all sources
    profiles = merge_fragments(all_groups)

    # Project each profile through the config
    results: list[dict] = []
    proj_errors = 0
    for prof in profiles:
        try:
            results.append(project(prof, proj_config))
        except (ProjectionError, ProjectionValidationError):
            proj_errors += 1

    confs = [p.overall_confidence for p in profiles]
    ctx.update({
        "file_log": file_log,
        "stats": {
            "total": len(profiles),
            "merged": sum(1 for p in profiles if p.merge_state == MergeState.MERGED),
            "needs_review": sum(
                1 for p in profiles if p.merge_state == MergeState.NEEDS_REVIEW
            ),
            "conf_range": (
                f"{min(confs):.2f} – {max(confs):.2f}" if confs else "n/a"
            ),
            "proj_errors": proj_errors,
        },
        "results_json": json.dumps(results, indent=2, ensure_ascii=False),
    })
    return templates.TemplateResponse(request, "index.html", ctx)


# ── Source detection (mirrors __main__.py without importing it) ────────────

def _detect_and_extract(path: Path) -> list[list]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return extract_csv(content)
    if suffix == ".txt":
        return extract_notes(content)
    if suffix == ".json":
        return _detect_json(content)
    return []


def _detect_json(content: str) -> list[list]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    first = data if isinstance(data, dict) else (data[0] if data else {})
    if isinstance(first, dict) and "login" in first:
        return extract_github(content)
    return extract_ats(content)
