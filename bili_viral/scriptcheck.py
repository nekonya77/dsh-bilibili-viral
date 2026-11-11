"""Originality and quality checks for generated scripts."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

from .config import Config
from .util import chinese_char_count, read_text, strip_markdown

NGRAM = 8
FORBIDDEN = [
    "稳赚", "躺赚", "保证收益", "百分百", "无风险", "包赚",
    "一夜暴富", "月入十万", "日入过万",
]
REQUIRED_SECTIONS = ["钩子", "结构", "分镜", "竞品", "事实核查"]


def normalize(text: str) -> str:
    text = strip_markdown(text or "").lower()
    return "".join(re.findall(r"[a-z0-9\u4e00-\u9fff]", text))


def ngrams(text: str, n: int = NGRAM) -> Set[str]:
    clean = normalize(text)
    if len(clean) < n:
        return set()
    return {clean[i: i + n] for i in range(0, len(clean) - n + 1)}


def containment(script: str, reference: str, n: int = NGRAM) -> float:
    a = ngrams(script, n)
    b = ngrams(reference, n)
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a))


def overlap_snippets(script: str, reference: str, n: int = NGRAM, limit: int = 5) -> List[str]:
    a = ngrams(script, n)
    b = ngrams(reference, n)
    common = sorted(a & b)
    return common[:limit]


def check_script(
    script_path: Path,
    ref_bvids: Iterable[str],
    data_dir: Path,
    cfg: Config,
) -> Dict[str, Any]:
    text = read_text(script_path)
    errors: List[str] = []
    warnings: List[str] = []
    if not text:
        return {"ok": False, "errors": ["script is empty"], "warnings": [], "overlaps": {}}
    chars = chinese_char_count(text)
    if chars < 900:
        errors.append(f"脚本汉字数 {chars} < 900")
    if chars > 2200:
        warnings.append(f"脚本汉字数 {chars} > 2200，口播可能超过 6 分钟")
    for section in REQUIRED_SECTIONS:
        if section not in text:
            errors.append(f"缺少小节：{section}")
    refs = list(ref_bvids)
    found = set(re.findall(r"BV[0-9A-Za-z]{10}", text))
    if len(found) < 2:
        errors.append(f"脚本中竞品引用少于 2 个（当前 {len(found)}）")
    for bvid in refs:
        if bvid not in found:
            warnings.append(f"refs 中有 {bvid} 但脚本正文未出现")
    for phrase in FORBIDDEN:
        if phrase in text:
            errors.append(f"出现高风险表述：{phrase}")
    overlaps: Dict[str, Any] = {}
    for bvid in refs:
        ref_path = data_dir / "transcripts" / f"{bvid}.md"
        if not ref_path.exists():
            continue
        ref_text = read_text(ref_path)
        score = containment(text, ref_text)
        overlaps[bvid] = {
            "containment": round(score, 4),
            "snippets": overlap_snippets(text, ref_text),
        }
        if score > 0.15:
            errors.append(f"与 {bvid} 字幕 8-gram 重合度 {score:.1%} > 15%")
    return {
        "ok": not errors,
        "script": str(script_path),
        "chars": chars,
        "refs": refs,
        "errors": errors,
        "warnings": warnings,
        "overlaps": overlaps,
    }
