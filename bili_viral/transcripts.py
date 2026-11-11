"""Fetch Bilibili AI subtitles and turn them into readable competitor scripts."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .bilibili import BiliClient
from .config import Config
from .util import chinese_char_count, ensure_dir, read_text, truncate_text, write_json

MAX_TRANSCRIPT_CHARS = 30000
COMPACT_CHARS = 12000


def format_ts(seconds: Any) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return "00:00"
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


def group_cues(cues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group subtitle cues into readable paragraphs with a start timestamp."""
    paragraphs: List[Dict[str, Any]] = []
    current: List[str] = []
    start = None
    last_to = None
    for cue in cues:
        content = str(cue.get("content") or "").strip()
        if not content:
            continue
        try:
            frm = float(cue.get("from") or 0)
            to = float(cue.get("to") or frm)
        except (TypeError, ValueError):
            frm, to = 0.0, 0.0
        if start is None:
            start = frm
        gap = (frm - last_to) if last_to is not None else 0
        current_chars = sum(len(x) for x in current)
        if current and (gap > 1.2 or current_chars > 220):
            paragraphs.append({"from": start, "text": "".join(current)})
            current = []
            start = frm
        current.append(content)
        last_to = to
    if current:
        paragraphs.append({"from": start or 0, "text": "".join(current)})
    return paragraphs


def cues_to_markdown(
    cues: List[Dict[str, Any]],
    title: str,
    bvid: str,
    lan: str = "",
) -> str:
    lines = [
        f"# {title}",
        "",
        f"- BVID: `{bvid}`",
        f"- 字幕语言: {lan or 'unknown'}（B站 AI 字幕，可能有错别字/漏句）",
        f"- 时长: {format_ts(cues[-1].get('to', 0)) if cues else '0:00'}",
        "",
        "## 口播转写",
        "",
    ]
    for para in group_cues(cues):
        lines.append(f"**[{format_ts(para['from'])}]** {para['text']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def fetch_transcript(
    client: BiliClient,
    video: Dict[str, Any],
    data_dir: Path,
    cfg: Config,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    logger = logger or logging.getLogger("bili_viral.transcripts")
    bvid = video["bvid"]
    title = video.get("clean_title") or video.get("title") or bvid
    out_dir = ensure_dir(data_dir / "transcripts")
    md_path = out_dir / f"{bvid}.md"
    json_path = out_dir / f"{bvid}.json"
    existing = video.get("transcript_status")
    if existing == "ok" and md_path.exists():
        return {
            "status": "ok",
            "path": str(md_path),
            "json_path": str(json_path),
            "lan": "",
            "cues": 0,
            "chars": chinese_char_count(read_text(md_path)),
            "cached": True,
        }
    cid = video.get("cid")
    try:
        if not cid:
            view = client.view(bvid)
            cid = view.get("cid")
            video["cid"] = cid
        if not cid:
            return _missing(md_path, "no cid")
        player = client.player(bvid, int(cid))
        chosen = client.choose_subtitle(player)
        if not chosen:
            return _missing(md_path, "no subtitle track")
        url = chosen.get("subtitle_url")
        if not url:
            return _missing(md_path, "empty subtitle url")
        cues = client.subtitle_json(url)
        if not cues:
            return _missing(md_path, "empty subtitle body")
        md = cues_to_markdown(cues, title, bvid, chosen.get("lan", ""))
        md = truncate_text(md, MAX_TRANSCRIPT_CHARS)
        md_path.write_text(md, encoding="utf-8")
        write_json(
            json_path,
            {
                "bvid": bvid,
                "title": title,
                "lan": chosen.get("lan", ""),
                "lan_doc": chosen.get("lan_doc", ""),
                "cues": cues,
            },
        )
        return {
            "status": "ok",
            "path": str(md_path),
            "json_path": str(json_path),
            "lan": chosen.get("lan", ""),
            "cues": len(cues),
            "chars": chinese_char_count(md),
            "cached": False,
        }
    except Exception as exc:
        logger.warning("Transcript failed for %s: %s", bvid, exc)
        return _missing(md_path, str(exc))


def _missing(md_path: Path, reason: str) -> Dict[str, Any]:
    return {
        "status": "missing",
        "path": str(md_path) if md_path.exists() else "",
        "json_path": "",
        "lan": "",
        "cues": 0,
        "chars": 0,
        "reason": reason,
        "cached": False,
    }


def compact_transcript(md_path: Path, limit: int = COMPACT_CHARS) -> str:
    text = read_text(md_path)
    if not text:
        return ""
    # Remove metadata lines, keep the transcript body.
    if "## 口播转写" in text:
        text = text.split("## 口播转写", 1)[1].strip()
    return truncate_text(text, limit)


def write_compact_pack(
    videos: List[Dict[str, Any]],
    data_dir: Path,
    out_path: Path,
    limit: int = COMPACT_CHARS,
) -> Path:
    lines = ["# 竞品字幕 compact pack", ""]
    for video in videos:
        bvid = video["bvid"]
        md_path = data_dir / "transcripts" / f"{bvid}.md"
        lines.append(f"## {bvid} | {video.get('clean_title') or video.get('title')}")
        lines.append(f"- 播放: {video.get('play')} | 分数: {video.get('score')}")
        if md_path.exists():
            lines.append("")
            lines.append(compact_transcript(md_path, limit))
        else:
            lines.append("")
            lines.append("（无字幕：只能从标题、封面、评论判断）")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
