"""Generate 1280x720 thumbnail variants from reference covers with PIL.

No generative image model is used. The reference cover supplies texture/palette,
and deterministic layouts produce covers that are safe to publish after review.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import Config
from .covers import load_font
from .util import ensure_dir, read_json, truncate_text, write_json

W, H = 1280, 720
STYLES = ["black_yellow", "split_compare", "screenshot_callout", "gradient_tech", "face_bigtext"]
STYLE_LABELS = {
    "black_yellow": "黑黄大字",
    "split_compare": "左右对比",
    "screenshot_callout": "截图标注",
    "gradient_tech": "渐变科技",
    "face_bigtext": "人像大字",
}
DEFAULT_ACCENTS = {
    "black_yellow": "#FFD400",
    "split_compare": "#FF5A3C",
    "screenshot_callout": "#FF7A00",
    "gradient_tech": "#39E6C3",
    "face_bigtext": "#FFD400",
}


def _rgb(value: str, fallback: Tuple[int, int, int] = (255, 212, 0)) -> Tuple[int, int, int]:
    value = (value or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        return fallback
    try:
        return tuple(int(value[i: i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return fallback


def _luminance(rgb: Tuple[int, int, int]) -> float:
    r, g, b = [c / 255.0 for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_text(rgb: Tuple[int, int, int]) -> Tuple[int, int, int]:
    return (16, 16, 16) if _luminance(rgb) > 0.55 else (255, 255, 255)


def _fit(source: Any, size: Tuple[int, int]) -> Image.Image:
    if isinstance(source, Image.Image):
        img = source.convert("RGB")
    else:
        img = Image.open(source).convert("RGB")
    return ImageOps.fit(img, size, method=Image.LANCZOS)


def _blur(img: Image.Image, radius: int = 14) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius))


def _overlay(img: Image.Image, color: Tuple[int, int, int], alpha: int) -> Image.Image:
    layer = Image.new("RGBA", img.size, color + (alpha,))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def _gradient(size: Tuple[int, int], top: Tuple[int, int, int], bottom: Tuple[int, int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    lines: List[str] = []
    current = ""
    for char in text:
        if char == "\n":
            lines.append(current)
            current = ""
            continue
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


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_lines: int,
    start: int,
    minimum: int,
    cfg: Config,
    bold: bool = True,
) -> Tuple[ImageFont.FreeTypeFont, List[str]]:
    size = start
    while size >= minimum:
        font = load_font(cfg, size)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
        size -= 4
    font = load_font(cfg, minimum)
    return font, _wrap(draw, text, font, max_width)[:max_lines]


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    lines: Sequence[str],
    font: ImageFont.FreeTypeFont,
    fill: Tuple[int, int, int],
    line_gap: int = 12,
    stroke: int = 0,
    stroke_fill: Tuple[int, int, int] = (0, 0, 0),
    shadow: bool = False,
) -> int:
    x, y = xy
    for line in lines:
        if shadow:
            draw.text((x + 5, y + 6), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
        box = draw.textbbox((0, 0), line, font=font)
        y += (box[3] - box[1]) + line_gap
    return y


def _badge(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    accent: Tuple[int, int, int],
    cfg: Config,
) -> None:
    font = load_font(cfg, 28)
    box = draw.textbbox((0, 0), text, font=font)
    w = box[2] - box[0] + 36
    h = 52
    x, y = xy
    draw.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=accent)
    draw.text((x + 18, y + 9), text, font=font, fill=_contrast_text(accent))


def _base_cover(cover_path: Optional[str], cfg: Config) -> Image.Image:
    if cover_path and Path(cover_path).exists():
        return _fit(Path(cover_path), (W, H))
    return _gradient((W, H), (18, 20, 28), (40, 30, 50))


def _style_black_yellow(base: Image.Image, spec: Dict[str, Any], accent: Tuple[int, int, int], cfg: Config, variant: int) -> Image.Image:
    img = Image.new("RGB", (W, H), (8, 8, 10))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 22, H], fill=accent)
    # angled accent block
    draw.polygon([(W - 310, 0), (W, 0), (W, 250), (W - 250, 0)], fill=accent)
    _badge(draw, (56, 44), spec.get("badge") or "AI 实操", accent, cfg)
    title = truncate_text(spec.get("title") or "把 AI 用成生产力", 24)
    font, lines = _fit_text(draw, title, W - 180, 3, 112, 64, cfg)
    y = 180 if variant % 2 == 0 else 210
    _draw_lines(draw, (58, y), lines, font, (255, 255, 255), line_gap=16, shadow=True)
    subtitle = truncate_text(spec.get("subtitle") or "一条可复制的工作流", 28)
    sub_font, sub_lines = _fit_text(draw, subtitle, W - 180, 2, 40, 28, cfg, bold=False)
    _draw_lines(draw, (60, H - 165), sub_lines, sub_font, accent, line_gap=8)
    draw.text((60, H - 54), "录屏 + 口播 · 3-6 分钟", font=load_font(cfg, 24), fill=(150, 150, 160))
    return img


def _style_split_compare(base: Image.Image, spec: Dict[str, Any], accent: Tuple[int, int, int], cfg: Config, variant: int) -> Image.Image:
    img = Image.new("RGB", (W, H), (12, 12, 16))
    left = _overlay(_blur(base, 6), (30, 30, 38), 90).convert("L").convert("RGB")
    right = base
    split = 640 + (40 if variant % 2 else -40)
    img.paste(left.crop((0, 0, split, H)), (0, 0))
    img.paste(right.crop((split, 0, W, H)), (split, 0))
    draw = ImageDraw.Draw(img)
    draw.line([(split, 0), (split, H)], fill=accent, width=8)
    draw.polygon([(split - 30, H // 2 - 34), (split + 30, H // 2), (split - 30, H // 2 + 34)], fill=accent)
    small = load_font(cfg, 28)
    draw.rectangle([24, 24, 240, 74], fill=(10, 10, 12))
    draw.text((40, 31), "旧方法", font=small, fill=(220, 220, 225))
    draw.rectangle([W - 250, 24, W - 24, 74], fill=accent)
    draw.text((W - 232, 31), "AI 工作流", font=small, fill=_contrast_text(accent))
    # bottom band
    band_top = H - 190
    draw.rectangle([0, band_top, W, H], fill=(8, 8, 10))
    title = truncate_text(spec.get("title") or "同一个任务，两种做法", 24)
    font, lines = _fit_text(draw, title, W - 80, 2, 58, 38, cfg)
    _draw_lines(draw, (40, band_top + 26), lines, font, (255, 255, 255), line_gap=8)
    sub = truncate_text(spec.get("subtitle") or "差距不在工具，在流程", 34)
    draw.text((42, H - 52), sub, font=load_font(cfg, 28), fill=accent)
    return img


def _style_screenshot_callout(base: Image.Image, spec: Dict[str, Any], accent: Tuple[int, int, int], cfg: Config, variant: int) -> Image.Image:
    img = _overlay(_blur(base, 18), (12, 14, 20), 120)
    draw = ImageDraw.Draw(img)
    # white card + screenshot crop
    card = [70, 90, W - 70, H - 80] if variant % 2 == 0 else [90, 70, W - 60, H - 60]
    draw.rounded_rectangle(card, radius=22, fill=(248, 248, 250))
    inset = 18
    shot_size = (card[2] - card[0] - inset * 2, card[3] - card[1] - inset * 2 - 150)
    if spec.get("_cover_path"):
        shot = _fit(Path(spec["_cover_path"]), shot_size)
    else:
        shot = ImageOps.fit(base, shot_size, method=Image.LANCZOS)
    img.paste(shot, (card[0] + inset, card[1] + inset))
    # callout circle + line
    cx, cy = card[0] + (card[2] - card[0]) // 2 + (80 if variant % 2 else -80), card[1] + 190
    draw.ellipse([cx - 46, cy - 46, cx + 46, cy + 46], outline=accent, width=7)
    draw.line([cx + 46, cy - 46, cx + 150, cy - 120], fill=accent, width=7)
    draw.rounded_rectangle([cx + 120, cy - 170, cx + 120 + 250, cy - 120], radius=8, fill=accent)
    draw.text((cx + 136, cy - 160), spec.get("callout") or "关键一步", font=load_font(cfg, 26), fill=_contrast_text(accent))
    # title band in card
    title = truncate_text(spec.get("title") or "这步没做，AI 白用", 26)
    font, lines = _fit_text(draw, title, card[2] - card[0] - 50, 2, 48, 32, cfg)
    _draw_lines(draw, (card[0] + 26, card[3] - 132), lines, font, (18, 18, 22), line_gap=6)
    draw.rectangle([card[0] + 26, card[3] - 20, card[2] - 26, card[3] - 12], fill=accent)
    _badge(draw, (24, 24), spec.get("badge") or "实测", accent, cfg)
    return img


def _style_gradient_tech(base: Image.Image, spec: Dict[str, Any], accent: Tuple[int, int, int], cfg: Config, variant: int) -> Image.Image:
    img = _gradient((W, H), (10, 14, 26), (26, 10, 36))
    # grid
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(layer)
    step = 64
    for x in range(0, W, step):
        gdraw.line([(x, 0), (x, H)], fill=accent + (26,), width=1)
    for y in range(0, H, step):
        gdraw.line([(0, y), (W, y)], fill=accent + (26,), width=1)
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    # tinted cover panel right
    panel = _overlay(_fit(base, (520, 620)), (0, 0, 0), 40) if base else base
    img.paste(panel, (W - 560, 50))
    draw = ImageDraw.Draw(img)
    draw.rectangle([W - 560, 50, W - 40, H - 50], outline=accent, width=3)
    _badge(draw, (70, 56), spec.get("badge") or "AI 工具", accent, cfg)
    title = truncate_text(spec.get("title") or "普通人也能搭的 AI 工作流", 24)
    font, lines = _fit_text(draw, title, 660, 3, 100, 58, cfg)
    _draw_lines(draw, (68, 170), lines, font, (255, 255, 255), line_gap=14, shadow=True)
    draw.rectangle([68, 170 + len(lines) * 108 + 8, 188, 170 + len(lines) * 108 + 16], fill=accent)
    sub = truncate_text(spec.get("subtitle") or "从 0 到 1 的拆解", 22)
    _draw_lines(draw, (70, H - 150), [sub], load_font(cfg, 36), accent, line_gap=6)
    draw.text((70, H - 70), "收藏 · 照着做", font=load_font(cfg, 26), fill=(190, 190, 205))
    return img


def _style_face_bigtext(base: Image.Image, spec: Dict[str, Any], accent: Tuple[int, int, int], cfg: Config, variant: int) -> Image.Image:
    img = _overlay(_blur(base, 4), (8, 8, 12), 150)
    # right circular portrait / cover focal area
    circle = Image.new("L", (W, H), 0)
    cdraw = ImageDraw.Draw(circle)
    cx, cy, radius = W - 330, H // 2 - 20, 290
    cdraw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=255)
    focal = base if base else img
    img.paste(focal, (0, 0), circle)
    draw = ImageDraw.Draw(img)
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=accent, width=8)
    _badge(draw, (56, 44), spec.get("badge") or "个人 IP", accent, cfg)
    title = truncate_text(spec.get("title") or "不出镜也能做爆款", 20)
    font, lines = _fit_text(draw, title, 680, 3, 112, 62, cfg)
    _draw_lines(draw, (58, 190), lines, font, (255, 255, 255), line_gap=16, shadow=True)
    sub = truncate_text(spec.get("subtitle") or "先做起来，再优化", 22)
    _draw_lines(draw, (60, H - 160), [sub], load_font(cfg, 36), accent, line_gap=6)
    draw.text((60, H - 72), "每周 5 条 · 稳定更新", font=load_font(cfg, 24), fill=(200, 200, 210))
    return img


STYLE_FUNCS = {
    "black_yellow": _style_black_yellow,
    "split_compare": _style_split_compare,
    "screenshot_callout": _style_screenshot_callout,
    "gradient_tech": _style_gradient_tech,
    "face_bigtext": _style_face_bigtext,
}


def render_cover(
    spec: Dict[str, Any],
    out_path: Path,
    cfg: Config,
    variant: int = 1,
    cover_path: Optional[str] = None,
) -> Path:
    style = spec.get("style") if spec.get("style") in STYLE_FUNCS else STYLES[(variant - 1) % len(STYLES)]
    accent = _rgb(spec.get("accent") or DEFAULT_ACCENTS.get(style, "#FFD400"))
    base = _base_cover(cover_path or spec.get("_cover_path"), cfg)
    spec = dict(spec)
    spec["_cover_path"] = cover_path or spec.get("_cover_path")
    img = STYLE_FUNCS[style](base, spec, accent, cfg, variant)
    # consistent brand strip
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, H - 8, W, H], fill=accent)
    ensure_dir(out_path.parent)
    img.save(out_path, "JPEG", quality=92, optimize=True)
    return out_path


def build_specs(plan: Dict[str, Any], videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_bvid = {v["bvid"]: v for v in videos}
    specs: List[Dict[str, Any]] = []
    for idx, idea in enumerate(plan.get("ideas", [])):
        refs = idea.get("refs") or []
        ref = by_bvid.get(refs[0], {}) if refs else {}
        title_options = idea.get("title_options") or [idea.get("title") or idea.get("topic") or "本周选题"]
        specs.append(
            {
                "id": idea.get("id") or f"w{idx + 1:02d}",
                "idea_id": idea.get("id") or f"w{idx + 1:02d}",
                "style": STYLES[idx % len(STYLES)],
                "title": idea.get("cover_title") or title_options[0],
                "subtitle": idea.get("cover_subtitle") or idea.get("hook") or idea.get("topic") or "",
                "badge": idea.get("badge") or "本周选题",
                "accent": (ref.get("palette") or [DEFAULT_ACCENTS[STYLES[idx % len(STYLES)]]])[0],
                "ref_bvid": refs[0] if refs else "",
                "_cover_path": ref.get("cover_path"),
            }
        )
    return specs


def generate_covers(
    specs: List[Dict[str, Any]],
    cfg: Config,
    week: str,
    videos: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    by_bvid = {v["bvid"]: v for v in (videos or [])}
    out_dir = cfg.output_dir / "covers" / "generated" / week
    ensure_dir(out_dir)
    results = []
    for spec in specs:
        ref = by_bvid.get(spec.get("ref_bvid", ""), {})
        cover_path = spec.get("_cover_path") or ref.get("cover_path")
        item = {
            "id": spec.get("id"),
            "idea_id": spec.get("idea_id") or spec.get("id"),
            "style": spec.get("style"),
            "style_label": STYLE_LABELS.get(spec.get("style", ""), spec.get("style")),
            "title": spec.get("title"),
            "variants": [],
        }
        for variant in (1, 2):
            path = out_dir / f"{spec.get('id')}-v{variant}.jpg"
            render_cover(spec, path, cfg, variant=variant, cover_path=cover_path)
            item["variants"].append(str(path))
        results.append(item)
    meta = {"week": week, "generated_at": datetime.datetime.now().isoformat(), "items": results}
    write_json(out_dir / "index.json", meta)
    return meta


def load_specs(data_dir: Path, week: str) -> List[Dict[str, Any]]:
    path = data_dir / "cover_specs" / f"{week}.json"
    data = read_json(path, default=None)
    if isinstance(data, dict):
        return data.get("covers", [])
    return []
