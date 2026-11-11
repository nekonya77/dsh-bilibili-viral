"""Cover download, colour extraction and contact sheets for agent review."""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .bilibili import BiliClient
from .config import Config
from .util import ensure_dir, human_num

COVER_W, COVER_H = 800, 450


def _base_pic(pic: str) -> str:
    if not pic:
        return ""
    return pic.split("@", 1)[0]


def cover_candidates(pic: str) -> List[str]:
    base = _base_pic(pic)
    if not base:
        return []
    return [base + "@800w_450h_1c.webp", base]


def load_font(cfg: Config, size: int) -> ImageFont.FreeTypeFont:
    path = cfg.font_path
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def make_placeholder(path: Path, label: str = "NO COVER") -> Path:
    ensure_dir(path.parent)
    img = Image.new("RGB", (COVER_W, COVER_H), (24, 24, 30))
    draw = ImageDraw.Draw(img)
    draw.rectangle([8, 8, COVER_W - 8, COVER_H - 8], outline=(70, 70, 85), width=2)
    draw.text((COVER_W // 2 - 60, COVER_H // 2 - 10), label, fill=(180, 180, 190))
    img.save(path, "JPEG", quality=85)
    return path


def extract_palette(path: Path, n: int = 6) -> List[str]:
    try:
        img = Image.open(path).convert("RGB").resize((120, 68))
        quant = img.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
        palette = quant.getpalette() or []
        counts = quant.getcolors() or []
        colors: List[Tuple[int, Tuple[int, int, int]]] = []
        for count, idx in counts:
            if idx * 3 + 2 < len(palette):
                rgb = tuple(palette[idx * 3: idx * 3 + 3])
                colors.append((count, rgb))  # type: ignore[arg-type]
        colors.sort(reverse=True)
        out = []
        for _, (r, g, b) in colors:
            out.append(f"#{r:02x}{g:02x}{b:02x}")
        return out[:n]
    except Exception:
        return []


def download_cover(
    session: Any,
    pic: str,
    bvid: str,
    out_dir: Path,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    logger = logger or logging.getLogger("bili_viral.covers")
    ensure_dir(out_dir)
    target = out_dir / f"{bvid}.jpg"
    if target.exists() and target.stat().st_size > 3000:
        return {"status": "cached", "path": str(target), "palette": extract_palette(target)}
    errors = []
    for url in cover_candidates(pic):
        try:
            resp = session.get(
                url,
                headers={"Referer": "https://www.bilibili.com/"},
                timeout=25,
            )
            if resp.status_code != 200 or not resp.content:
                errors.append(f"{resp.status_code} {url}")
                continue
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            img = ImageOps.fit(img, (COVER_W, COVER_H), method=Image.LANCZOS)
            img.save(target, "JPEG", quality=88, optimize=True)
            return {
                "status": "ok",
                "path": str(target),
                "palette": extract_palette(target),
                "bytes": target.stat().st_size,
            }
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    logger.warning("Cover failed for %s: %s", bvid, "; ".join(errors[:2]))
    make_placeholder(target, bvid)
    return {"status": "placeholder", "path": str(target), "palette": [], "errors": errors}


def download_covers(
    client: BiliClient,
    videos: List[Dict[str, Any]],
    cfg: Config,
    logger: Optional[logging.Logger] = None,
) -> List[Dict[str, Any]]:
    out_dir = cfg.output_dir / "covers" / "library"
    results = []
    for video in videos:
        result = download_cover(
            client.session, video.get("pic") or "", video["bvid"], out_dir, logger
        )
        video["cover_path"] = result.get("path")
        video["palette"] = result.get("palette", [])
        result["bvid"] = video["bvid"]
        results.append(result)
    return results


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    lines: List[str] = []
    current = ""
    for char in text:
        candidate = current + char
        box = draw.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def contact_sheet(
    videos: List[Dict[str, Any]],
    out_path: Path,
    cfg: Config,
    cols: int = 3,
    rows: int = 2,
    cell_w: int = 480,
    cell_h: int = 270,
) -> Path:
    pad = 24
    label_h = 64
    width = cols * cell_w + (cols + 1) * pad
    height = rows * (cell_h + label_h) + (rows + 1) * pad + 50
    canvas = Image.new("RGB", (width, height), (16, 16, 22))
    draw = ImageDraw.Draw(canvas)
    header_font = load_font(cfg, 24)
    label_font = load_font(cfg, 18)
    draw.text((pad, 14), "B站爆款封面接触表", fill=(255, 255, 255), font=header_font)
    for idx, video in enumerate(videos[: cols * rows]):
        row, col = divmod(idx, cols)
        x = pad + col * (cell_w + pad)
        y = 50 + pad + row * (cell_h + label_h + pad)
        cover = Path(video.get("cover_path") or "")
        if not cover.exists():
            cover = cfg.output_dir / "covers" / "library" / f"{video['bvid']}.jpg"
        if cover.exists():
            img = Image.open(cover).convert("RGB")
            img = ImageOps.fit(img, (cell_w, cell_h), method=Image.LANCZOS)
            canvas.paste(img, (x, y))
        else:
            draw.rectangle([x, y, x + cell_w, y + cell_h], fill=(40, 40, 50))
            draw.text((x + 20, y + 20), "NO IMAGE", fill=(180, 180, 190), font=label_font)
        label = f"#{idx + 1} {video['bvid']}"
        meta = f"播放 {human_num(video.get('play'))} | 分 {video.get('score', 0)}"
        draw.text((x, y + cell_h + 6), label, fill=(255, 255, 255), font=label_font)
        draw.text((x, y + cell_h + 30), meta, fill=(180, 180, 200), font=label_font)
    ensure_dir(out_path.parent)
    canvas.save(out_path, "JPEG", quality=88, optimize=True)
    return out_path


def write_contact_sheets(
    videos: List[Dict[str, Any]],
    out_dir: Path,
    cfg: Config,
    per_sheet: int = 6,
) -> List[str]:
    ensure_dir(out_dir)
    paths: List[str] = []
    for start in range(0, len(videos), per_sheet):
        chunk = videos[start: start + per_sheet]
        path = out_dir / f"sheet-{start // per_sheet + 1}.jpg"
        contact_sheet(chunk, path, cfg)
        paths.append(str(path))
    return paths
