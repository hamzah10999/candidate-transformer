"""Entry point: python -m candidate_transformer [args]"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from .adapters.ats_adapter import extract_ats
from .adapters.csv_adapter import extract_csv
from .adapters.github_adapter import extract_github
from .adapters.notes_adapter import extract_notes
from .merge.engine import merge_fragments
from .models.canonical import MergeState
from .models.config import ProjectionConfig
from .projection.engine import ProjectionError, ProjectionValidationError, project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m candidate_transformer",
        description="Multi-Source Candidate Data Transformer",
    )
    parser.add_argument(
        "--sources", nargs="+", required=True, metavar="FILE",
        help="Source files: recruiter CSV, ATS JSON, GitHub JSON, notes TXT",
    )
    parser.add_argument(
        "--config", required=True, metavar="FILE",
        help="Projection config JSON (field specs + globals)",
    )
    parser.add_argument(
        "--output", required=True, metavar="FILE",
        help="Output JSON file path",
    )
    args = parser.parse_args(argv)

    # ── Load projection config ────────────────────────────────────────────
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[error] Config file not found: {config_path}", file=sys.stderr)
        return 1
    config = ProjectionConfig.model_validate_json(config_path.read_text(encoding="utf-8"))

    # ── Extract from all sources ──────────────────────────────────────────
    all_groups: list[list] = []
    for src_str in args.sources:
        src = Path(src_str)
        if not src.exists():
            print(f"[warn] Source not found, skipping: {src}", file=sys.stderr)
            continue
        groups = _detect_and_extract(src)
        all_groups.extend(groups)
        print(f"[info] {src.name}: {len(groups)} record(s) extracted")

    if not all_groups:
        print("[warn] No candidate records extracted from any source.", file=sys.stderr)

    # ── Merge ─────────────────────────────────────────────────────────────
    profiles = merge_fragments(all_groups)

    # ── Project ───────────────────────────────────────────────────────────
    results: list[dict] = []
    proj_errors = 0
    for prof in profiles:
        try:
            results.append(project(prof, config))
        except (ProjectionError, ProjectionValidationError) as exc:
            print(
                f"[warn] projection failed for {prof.candidate_id}: {exc}",
                file=sys.stderr,
            )
            proj_errors += 1

    # ── Write output ──────────────────────────────────────────────────────
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── Summary ───────────────────────────────────────────────────────────
    n_merged = sum(1 for p in profiles if p.merge_state == MergeState.MERGED)
    n_review = sum(1 for p in profiles if p.merge_state == MergeState.NEEDS_REVIEW)
    confs = [p.overall_confidence for p in profiles]
    conf_range = (
        f"{min(confs):.2f} – {max(confs):.2f}" if confs else "n/a"
    )

    print()
    print("── Summary ──────────────────────────────")
    print(f"  Candidates   : {len(profiles)}")
    print(f"  Merged       : {n_merged}")
    print(f"  Needs review : {n_review}")
    print(f"  Confidence   : {conf_range}")
    if proj_errors:
        print(f"  Proj errors  : {proj_errors}")
    print(f"  Output       : {out_path}")

    return 0


def _detect_and_extract(path: Path) -> list[list]:
    """Route a source file to the correct adapter by extension and content."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[warn] Cannot read {path}: {exc}", file=sys.stderr)
        return []

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return extract_csv(content)
    if suffix == ".txt":
        return extract_notes(content)
    if suffix == ".json":
        return _detect_json(path.name, content)

    print(f"[warn] Unrecognised extension for {path.name}, skipping", file=sys.stderr)
    return []


def _detect_json(filename: str, content: str) -> list[list]:
    """Distinguish GitHub fixture JSON from ATS JSON by payload shape.

    GitHub profiles carry a 'login' key; ATS records use 'candidate_name'.
    A malformed JSON is caught and logged — never fatal to the batch.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        print(f"[warn] {filename}: JSON parse failed: {exc}", file=sys.stderr)
        return []

    # Single object or first element has 'login' → GitHub profile
    first = data if isinstance(data, dict) else (data[0] if data else {})
    if isinstance(first, dict) and "login" in first:
        return extract_github(content)

    return extract_ats(content)


if __name__ == "__main__":
    sys.exit(main())
