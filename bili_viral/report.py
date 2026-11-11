"""Markdown daily/weekly reports and standalone script HTML."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Config
from .rank import trend_terms
from .util import clean_title, ensure_dir, human_num, read_text, truncate_text, write_json

TEMPLATE_DIR = Path(__file__).parent / "templates"
ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _decorate(video: Dict[str, Any], analyses: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    item = dict(video)
    item["title"] = clean_title(video.get("clean_title") or video.get("title"))
    item["analysis"] = analyses.get(video.get("bvid", ""), {})
    item["play_human"] = human_num(video.get("play"))
    item["like_human"] = human_num(video.get("like"))
    item["url"] = f"https://www.bilibili.com/video/{video.get('bvid')}"
    item["cover_rel"] = f"../covers/library/{video.get('bvid')}.jpg"
    item["why"] = item["analysis"].get("why_viral") or []
    return item


def render_daily(
    date: str,
    videos: List[Dict[str, Any]],
    analyses: Dict[str, Dict[str, Any]],
    cfg: Config,
) -> Path:
    ensure_dir(cfg.output_dir / "daily")
    items = [_decorate(v, analyses) for v in videos]
    trend = trend_terms(videos, top_n=18)
    template = ENV.get_template("daily.md.j2")
    text = template.render(
        date=date,
        items=items,
        trend=trend,
        total=len(items),
        subtitle_count=sum(1 for v in videos if v.get("transcript_status") == "ok"),
    )
    path = cfg.output_dir / "daily" / f"{date}.md"
    path.write_text(text, encoding="utf-8")
    return path


def render_weekly(
    week: str,
    plan: Dict[str, Any],
    videos: List[Dict[str, Any]],
    analyses: Dict[str, Dict[str, Any]],
    cfg: Config,
    cover_meta: Optional[Dict[str, Any]] = None,
) -> Path:
    ensure_dir(cfg.output_dir / "weekly")
    by_bvid = {v.get("bvid"): v for v in videos}
    ideas = []
    for idea in plan.get("ideas", []):
        item = dict(idea)
        refs = []
        for bvid in idea.get("refs", []):
            video = by_bvid.get(bvid)
            if video:
                refs.append(_decorate(video, analyses))
        item["ref_items"] = refs
        script = idea.get("script_path") or ""
        if script:
            abs_script = Path(script)
            if not abs_script.is_absolute():
                abs_script = cfg.root / script
            item["script_rel"] = os.path.relpath(str(abs_script), str(cfg.output_dir / "weekly"))
        else:
            item["script_rel"] = ""
        item["cover_v1"] = f"../covers/generated/{week}/{item.get('id')}-v1.jpg"
        item["cover_v2"] = f"../covers/generated/{week}/{item.get('id')}-v2.jpg"
        item["cover_title"] = item.get("cover_title") or (item.get("title_options") or [""])[0]
        ideas.append(item)
    template = ENV.get_template("weekly.md.j2")
    text = template.render(week=week, plan=plan, ideas=ideas, cover_meta=cover_meta or {})
    path = cfg.output_dir / "weekly" / f"{week}.md"
    path.write_text(text, encoding="utf-8")
    return path


def render_script_html(script_path: Path, cfg: Config) -> Path:
    source = read_text(script_path)
    body = md.markdown(source, extensions=["tables", "fenced_code", "sane_lists"])
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{script_path.stem}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ max-width: 860px; margin: 0 auto; padding: 32px 20px 80px; font: 16px/1.8 -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", sans-serif; }}
h1,h2,h3 {{ line-height: 1.35; }}
h2 {{ margin-top: 2em; border-left: 5px solid #fb7299; padding-left: 12px; }}
code, pre {{ background: rgba(127,127,127,.12); border-radius: 6px; }}
pre {{ padding: 14px; overflow: auto; }}
blockquote {{ border-left: 4px solid #fb7299; margin-left: 0; padding-left: 16px; color: #666; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid rgba(127,127,127,.35); padding: 8px 10px; }}
a {{ color: #fb7299; }}
</style></head><body>
{body}
</body></html>"""
    out = cfg.output_dir / "scripts" / f"{script_path.stem}.html"
    ensure_dir(out.parent)
    out.write_text(html, encoding="utf-8")
    return out


def render_all_script_html(cfg: Config, plan: Optional[Dict[str, Any]] = None) -> List[str]:
    paths: List[str] = []
    targets: List[Path] = []
    if plan:
        for idea in plan.get("ideas", []):
            raw = idea.get("script_path")
            if raw:
                p = Path(raw)
                if not p.is_absolute():
                    p = cfg.root / raw
                targets.append(p)
    if not targets:
        targets = sorted((cfg.output_dir / "scripts").glob("*.md"))
    for path in targets:
        if path.exists():
            paths.append(str(render_script_html(path, cfg)))
    return paths


def write_plan_index(plan: Dict[str, Any], cfg: Config) -> Path:
    week = plan.get("week") or "unknown"
    path = cfg.data_dir / "plans" / f"{week}.json"
    ensure_dir(path.parent)
    write_json(path, plan)
    return path
