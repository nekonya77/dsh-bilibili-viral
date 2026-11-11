"""Dashboard renderer: a single self-contained HTML page with local assets."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .analysis import load_analyses
from .config import Config
from .store import Store
from .util import clean_title, ensure_dir, human_num, read_json, today_str, write_json

TEMPLATE_DIR = Path(__file__).parent / "templates"
ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _rel(path: Optional[str], base: Path) -> str:
    if not path:
        return ""
    try:
        return os.path.relpath(str(path), str(base))
    except ValueError:
        return str(path)


def _decorate(video: Dict[str, Any], analyses: Dict[str, Dict[str, Any]], base: Path) -> Dict[str, Any]:
    item = dict(video)
    item["title"] = clean_title(video.get("clean_title") or video.get("title"))
    analysis = analyses.get(video.get("bvid", ""), {})
    item["analysis"] = analysis
    item["play_human"] = human_num(video.get("play"))
    item["like_human"] = human_num(video.get("like"))
    item["url"] = f"https://www.bilibili.com/video/{video.get('bvid')}"
    cover = video.get("cover_path") or str(base.parent / "covers" / "library" / f"{video.get('bvid')}.jpg")
    item["cover_rel"] = _rel(cover, base)
    item["cover_exists"] = Path(cover).exists()
    item["pubdate_str"] = __import__("datetime").datetime.fromtimestamp(
        int(video.get("pubdate") or 0)
    ).strftime("%m-%d %H:%M") if video.get("pubdate") else "-"
    item["search_blob"] = " ".join(
        str(x or "") for x in (
            item["title"], clean_title(video.get("owner_name")), clean_title(video.get("keyword_group")),
            clean_title(analysis.get("topic")), clean_title(video.get("keyword")),
        )
    ).lower()
    return item


def _load_json_asset(path: Path, default: Any) -> Any:
    data = read_json(path, default=None)
    return default if data is None else data


def build_data(cfg: Config, store: Store, plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = cfg.output_dir / "dashboard"
    ensure_dir(base)
    analyses = load_analyses(cfg.data_dir)
    videos = store.list_videos(limit=300)
    items = [_decorate(v, analyses, base) for v in videos]
    items.sort(key=lambda v: (bool(v.get("is_hot")), float(v.get("score") or 0), int(v.get("play") or 0)), reverse=True)
    counts = store.counts()
    runs = store.latest_runs(limit=8)
    last_run = runs[0] if runs else {}

    # topic cards from analyses (dedupe by topic)
    topics: List[Dict[str, Any]] = []
    seen_topics = set()
    for video in items:
        analysis = video.get("analysis") or {}
        topic = (analysis.get("topic") or "").strip()
        if not topic or topic in seen_topics:
            continue
        seen_topics.add(topic)
        topics.append(
            {
                "topic": topic,
                "why": analysis.get("why_viral") or [],
                "angle": analysis.get("remake_angle") or "",
                "hook": analysis.get("hook") or "",
                "bvid": video["bvid"],
                "title": video["title"],
                "url": video["url"],
                "cover_rel": video["cover_rel"],
                "score": video.get("score"),
                "play_human": video.get("play_human"),
            }
        )
    topics = topics[:8]

    sheets = []
    sheet_dir = cfg.output_dir / "covers" / "library" / "sheets"
    for path in sorted(sheet_dir.glob("*.jpg")):
        sheets.append({"path": _rel(path, base), "name": path.stem})
    if not sheets:
        for path in sorted((cfg.output_dir / "covers" / "library").glob("sheet-*.jpg")):
            sheets.append({"path": _rel(path, base), "name": path.stem})

    formulas = _load_json_asset(
        cfg.data_dir / "knowledge" / "cover_formulas.json",
        _load_json_asset(Path(__file__).parent / "assets" / "cover_formulas.seed.json", []),
    )
    patterns = _load_json_asset(
        cfg.data_dir / "knowledge" / "script_patterns.json",
        _load_json_asset(Path(__file__).parent / "assets" / "script_patterns.seed.json", []),
    )
    if not isinstance(formulas, list):
        formulas = []
    if not isinstance(patterns, list):
        patterns = []

    scripts: List[Dict[str, Any]] = []
    if plan:
        for idea in plan.get("ideas", []):
            raw = idea.get("script_path")
            if not raw:
                continue
            path = Path(raw)
            if not path.is_absolute():
                path = cfg.root / raw
            html = path.with_suffix(".html")
            if path.exists():
                scripts.append(
                    {
                        "id": idea.get("id"),
                        "day": idea.get("day"),
                        "topic": idea.get("topic"),
                        "title": (idea.get("title_options") or [idea.get("topic") or ""])[0],
                        "md_rel": _rel(path, base),
                        "html_rel": _rel(html, base) if html.exists() else "",
                        "chars": idea.get("script_chars") or "",
                    }
                )
    if not scripts:
        for path in sorted((cfg.output_dir / "scripts").glob("*.html")):
            scripts.append(
                {
                    "id": path.stem,
                    "day": "",
                    "topic": path.stem,
                    "title": path.stem,
                    "md_rel": "",
                    "html_rel": _rel(path, base),
                    "chars": "",
                }
            )

    weekly_rel = ""
    plan_view: Dict[str, Any] = {}
    if plan:
        plan_view = dict(plan)
        plan_view["ideas"] = []
        for idea in plan.get("ideas", []):
            item = dict(idea)
            raw = item.get("script_path")
            if raw:
                path = Path(raw)
                if not path.is_absolute():
                    path = cfg.root / raw
                html = path.with_suffix(".html")
                item["script_rel"] = _rel(html, base) if html.exists() else _rel(path, base)
            plan_view["ideas"].append(item)
        weekly_path = cfg.output_dir / "weekly" / f"{plan.get('week', '')}.md"
        if weekly_path.exists():
            weekly_rel = _rel(weekly_path, base)

    daily = []
    for path in sorted((cfg.output_dir / "daily").glob("*.md"), reverse=True)[:7]:
        daily.append({"name": path.stem, "rel": _rel(path, base)})

    weekly_files = []
    for path in sorted((cfg.output_dir / "weekly").glob("*.md"), reverse=True)[:6]:
        weekly_files.append({"name": path.stem, "rel": _rel(path, base)})

    group_counts: Dict[str, int] = {}
    for video in items:
        group = str(video.get("keyword_group") or "未分组")
        group_counts[group] = group_counts.get(group, 0) + 1

    data = {
        "date": today_str(),
        "stats": {
            "videos": counts.get("videos", 0),
            "hot": counts.get("hot", 0),
            "with_transcript": counts.get("with_transcript", 0),
            "shown": len(items),
            "groups": len(group_counts),
            "last_run": last_run.get("finished_at") or last_run.get("started_at") or "尚未运行",
            "last_status": last_run.get("status") or "unknown",
        },
        "videos": items,
        "top3": items[:3],
        "topics": topics,
        "sheets": sheets,
        "formulas": formulas[:6],
        "patterns": patterns[:6],
        "scripts": scripts,
        "plan": plan_view,
        "weekly_rel": weekly_rel,
        "weekly_files": weekly_files,
        "daily": daily,
        "runs": runs,
        "group_counts": group_counts,
        "has_plan": bool(plan),
    }
    write_json(base / "data.json", data)
    return data


def render_dashboard(
    cfg: Config,
    store: Store,
    plan: Optional[Dict[str, Any]] = None,
) -> Path:
    data = build_data(cfg, store, plan)
    template = ENV.get_template("dashboard.html.j2")
    data_json = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    html = template.render(data=data, data_json=data_json)
    out = cfg.output_dir / "dashboard" / "index.html"
    ensure_dir(out.parent)
    out.write_text(html, encoding="utf-8")
    return out


def open_path(path: Path) -> None:
    """Best-effort helper used by CLI --open."""
    import subprocess
    import sys

    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform.startswith("linux"):
        subprocess.run(["xdg-open", str(path)], check=False)
    else:
        os.startfile(str(path))  # type: ignore[attr-defined]
