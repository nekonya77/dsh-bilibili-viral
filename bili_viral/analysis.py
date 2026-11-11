"""Load, merge and validate agent-produced analysis/plan JSON."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .util import read_json, write_json

ANALYSIS_REQUIRED = ["bvid", "topic", "why_viral", "cover", "scores"]
PLAN_REQUIRED = ["week", "ideas"]
IDEA_REQUIRED = ["id", "day", "topic", "title_options", "refs", "script_path"]


def load_analyses(data_dir: Path) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    files = sorted((data_dir / "analysis").glob("*.json"))
    for path in files:
        data = read_json(path, default={})
        videos = data.get("videos", []) if isinstance(data, dict) else []
        for item in videos:
            if isinstance(item, dict) and item.get("bvid"):
                item = dict(item)
                item["_analysis_date"] = data.get("date") or path.stem
                merged[item["bvid"]] = item
    return merged


def latest_plan(data_dir: Path, week: Optional[str] = None) -> Optional[Dict[str, Any]]:
    plan_dir = data_dir / "plans"
    if week:
        path = plan_dir / f"{week}.json"
        return read_json(path, default=None)
    files = sorted(plan_dir.glob("*.json"))
    if not files:
        return None
    return read_json(files[-1], default=None)


def analysis_for(video: Dict[str, Any], analyses: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return analyses.get(video.get("bvid", ""), {})


def validate_analysis(data: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(data, dict):
        return ["analysis root must be an object"]
    videos = data.get("videos")
    if not isinstance(videos, list):
        return ["analysis.videos must be a list"]
    seen = set()
    for idx, item in enumerate(videos):
        prefix = f"videos[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for key in ANALYSIS_REQUIRED:
            if key not in item:
                errors.append(f"{prefix}.{key} is required")
        bvid = item.get("bvid")
        if bvid in seen:
            errors.append(f"{prefix}.bvid duplicated: {bvid}")
        seen.add(bvid)
        if not isinstance(item.get("why_viral", []), list):
            errors.append(f"{prefix}.why_viral must be a list")
        if not isinstance(item.get("cover", {}), dict):
            errors.append(f"{prefix}.cover must be an object")
        scores = item.get("scores", {})
        if not isinstance(scores, dict):
            errors.append(f"{prefix}.scores must be an object")
    return errors


def validate_plan(data: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(data, dict):
        return ["plan root must be an object"]
    for key in PLAN_REQUIRED:
        if key not in data:
            errors.append(f"plan.{key} is required")
    ideas = data.get("ideas")
    if not isinstance(ideas, list):
        return errors + ["plan.ideas must be a list"]
    if len(ideas) < 5:
        errors.append(f"plan.ideas should contain 5 ideas, got {len(ideas)}")
    seen = set()
    for idx, idea in enumerate(ideas):
        prefix = f"ideas[{idx}]"
        if not isinstance(idea, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for key in IDEA_REQUIRED:
            if key not in idea:
                errors.append(f"{prefix}.{key} is required")
        idea_id = idea.get("id")
        if idea_id in seen:
            errors.append(f"{prefix}.id duplicated: {idea_id}")
        seen.add(idea_id)
        if not isinstance(idea.get("title_options", []), list):
            errors.append(f"{prefix}.title_options must be a list")
        if not isinstance(idea.get("refs", []), list):
            errors.append(f"{prefix}.refs must be a list")
        if not isinstance(idea.get("outline", []), list):
            errors.append(f"{prefix}.outline must be a list")
    return errors


def load_cover_specs(data_dir: Path) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    spec_dir = data_dir / "cover_specs"
    if not spec_dir.exists():
        return specs
    for path in sorted(spec_dir.glob("*.json")):
        data = read_json(path, default=None)
        if isinstance(data, dict):
            data["_path"] = str(path)
            specs.append(data)
    return specs


def merge_analysis_file(data_dir: Path, path: Path) -> Dict[str, Any]:
    data = read_json(path, default={})
    errors = validate_analysis(data)
    return {"errors": errors, "count": len((data or {}).get("videos", []))}
