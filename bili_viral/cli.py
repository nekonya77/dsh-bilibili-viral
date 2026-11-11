"""Command line entry points for the Bilibili viral radar."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .analysis import (
    latest_plan,
    load_analyses,
    validate_analysis,
    validate_plan,
)
from .bilibili import BiliAuthError, BiliClient, BiliError
from .config import Config, load_config
from .cookies import CookieStore, cookie_summary
from .covergen import build_specs, generate_covers, load_specs
from .covers import contact_sheet, download_covers, write_contact_sheets
from .rank import dedupe, passes_filters, relevance, score_videos, select_top
from .render import open_path, render_dashboard
from .report import render_all_script_html, render_daily, render_weekly, write_plan_index
from .scriptcheck import check_script
from .store import Store
from .transcripts import fetch_transcript, write_compact_pack
from .util import (
    days_ago_ts,
    disk_free_gb,
    ensure_dir,
    human_num,
    now_cn,
    read_json,
    setup_logging,
    today_str,
    week_key,
    write_json,
)


def _cfg(args: argparse.Namespace) -> Config:
    path = Path(args.config) if getattr(args, "config", None) else None
    return load_config(path)


def _client(cfg: Config, logger: logging.Logger, refresh: bool = False) -> Tuple[BiliClient, bool, Dict[str, Any], CookieStore]:
    store = CookieStore(cfg, logger)
    session, logged_in, info = store.ensure(force_chrome=refresh)
    client = BiliClient(cfg, session, logger)
    client.bootstrap()
    return client, logged_in, info, store


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    logger = setup_logging(cfg.data_dir / "logs", "bili_viral.doctor")
    checks: List[Dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, fatal: bool = False) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "fatal": fatal})

    add("python", sys.version_info >= (3, 9), sys.version.split()[0], True)
    for module in ("curl_cffi", "PIL", "yaml", "jinja2", "markdown", "yt_dlp"):
        try:
            __import__(module)
            add(f"python:{module}", True, "ok")
        except Exception as exc:
            add(f"python:{module}", False, str(exc), True)
    font = cfg.font_path
    add("cjk-font", bool(font), font or "未找到中文字体，封面会退化", True)
    add("disk", disk_free_gb(cfg.root) >= float(cfg.project.get("disk_guard_gb", 1.5)),
        f"{disk_free_gb(cfg.root):.2f} GB free", True)
    store = Store(cfg.db_path)
    health = store.health()
    add("sqlite", health["db_ok"], f"{health['path']} ({health['size_mb']} MB)")
    add("db-counts", True, json.dumps(health["counts"], ensure_ascii=False))

    logger.info("Checking cookies / login ...")
    client, logged_in, info, cookie_store = _client(cfg, logger)
    add("cookies", bool(info.get("count")), f"source={info.get('source')} count={info.get('count')} logged_in={logged_in}")
    add("bilibili-login", logged_in, "Chrome/SESSDATA 登录态" if logged_in else "未登录：字幕会缺失，搜索可能 412")
    api_ok = False
    api_detail = ""
    try:
        begin = days_ago_ts(7)
        end = int(now_cn().timestamp())
        results = client.search(cfg.keywords[0]["term"], "click", begin, end, 1, cfg.keywords[0].get("group", ""))
        api_ok = True
        api_detail = f"search returned {len(results)} videos"
    except BiliAuthError as exc:
        api_detail = f"auth error: {exc}"
    except BiliError as exc:
        api_detail = f"api error: {exc}"
    except Exception as exc:
        api_detail = f"{type(exc).__name__}: {exc}"
    add("bilibili-search", api_ok, api_detail, True)
    add("dashboard", (cfg.output_dir / "dashboard" / "index.html").exists(), "尚未生成" if not (cfg.output_dir / "dashboard" / "index.html").exists() else "已生成")
    client.close()
    store.close()

    fatal = any(c["fatal"] and not c["ok"] for c in checks)
    print(json.dumps({"ok": not fatal, "checks": checks}, ensure_ascii=False, indent=2))
    write_json(cfg.data_dir / "runs" / "doctor.json", {"ok": not fatal, "checks": checks})
    return 0 if not fatal else 1


def cmd_collect(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    logger = setup_logging(cfg.data_dir / "logs", "bili_viral.collect")
    store = Store(cfg.db_path)
    run_id = now_cn().strftime("%Y%m%d-%H%M%S")
    days = int(args.days or cfg.filters.get("daily_window_days", 2))
    begin = days_ago_ts(days)
    end = int(now_cn().timestamp())
    keywords = [k for k in cfg.keywords if k.get("term")]
    store.start_run(run_id, days, [k["term"] for k in keywords])

    counts: Dict[str, Any] = {
        "fetched": 0, "kept": 0, "details": 0, "transcripts_ok": 0,
        "transcripts_missing": 0, "covers": 0, "errors": 0,
    }
    errors: List[str] = []
    client = None
    try:
        client, logged_in, info, _ = _client(cfg, logger, refresh=args.refresh_cookies)
        logger.info("Run %s | window=%s days | login=%s | cookies=%s", run_id, days, logged_in, info)
        if not logged_in:
            logger.warning("Bilibili is not logged in; subtitles may be missing.")

        candidates: Dict[str, Dict[str, Any]] = {}
        pages = int(args.pages or cfg.limits.get("search_pages", 2))
        for keyword in keywords:
            term = keyword["term"]
            group = keyword.get("group") or "默认"
            for order in ("click", "pubdate"):
                for page in range(1, pages + 1):
                    try:
                        results = client.search(term, order, begin, end, page, group)
                    except BiliAuthError as exc:
                        logger.error("Auth error on %s/%s: %s", term, order, exc)
                        errors.append(f"{term}/{order}: {exc}")
                        raise
                    except BiliError as exc:
                        logger.warning("Search failed %s/%s p%s: %s", term, order, page, exc)
                        errors.append(f"{term}/{order}/p{page}: {exc}")
                        continue
                    counts["fetched"] += len(results)
                    for item in results:
                        bvid = item.get("bvid")
                        if not bvid or not passes_filters(item, cfg, begin, end):
                            continue
                        item["relevance"] = relevance(item, term)
                        old = candidates.get(bvid)
                        if old is None or item["relevance"] > old.get("relevance", 0):
                            candidates[bvid] = item
            logger.info("Keyword %s done, candidates=%s", term, len(candidates))

        videos = list(candidates.values())
        logger.info("Candidates after filters: %s", len(videos))
        score_videos(videos, cfg)
        selected = select_top(videos, int(cfg.limits.get("max_videos_per_run", 120)))
        counts["kept"] = len(selected)
        for video in selected:
            store.upsert_video(video)

        # Details for the strongest candidates.
        details_limit = int(cfg.limits.get("max_details", 30))
        for video in selected[:details_limit]:
            try:
                detail = client.view(video["bvid"])
                for key in ("keyword", "keyword_group", "relevance"):
                    detail[key] = video.get(key)
                video.update(detail)
                video["score"] = video.get("score")
                mid = video.get("owner_mid")
                if mid:
                    follower = client.follower(int(mid))
                    video["follower"] = follower
                    store.upsert_up(int(mid), video.get("owner_name") or "", follower)
                store.upsert_video(video)
                counts["details"] += 1
            except Exception as exc:
                counts["errors"] += 1
                errors.append(f"view {video['bvid']}: {exc}")
                logger.warning("View failed %s: %s", video["bvid"], exc)

        score_videos(selected, cfg)
        for video in selected:
            store.update_video(
                video["bvid"],
                play=video.get("play"), like=video.get("like"),
                favorite=video.get("favorite"), coin=video.get("coin"),
                share=video.get("share"), reply=video.get("reply"),
                danmaku=video.get("danmaku"), follower=video.get("follower"),
                score=video.get("score"), score_json=video.get("score_json"),
                is_hot=video.get("is_hot"),
            )
        selected.sort(key=lambda v: (float(v.get("score") or 0), int(v.get("play") or 0)), reverse=True)

        if not args.no_transcripts and logged_in:
            for video in selected[: int(cfg.limits.get("max_transcripts", 15))]:
                if video.get("transcript_status") == "ok" and (cfg.data_dir / "transcripts" / f"{video['bvid']}.md").exists():
                    counts["transcripts_ok"] += 1
                    continue
                result = fetch_transcript(client, video, cfg.data_dir, cfg, logger)
                video["transcript_status"] = result["status"]
                store.update_video(
                    video["bvid"],
                    transcript_status=result["status"],
                    cid=video.get("cid"),
                )
                if result["status"] == "ok":
                    counts["transcripts_ok"] += 1
                else:
                    counts["transcripts_missing"] += 1

        if not args.no_covers:
            cover_targets = selected[: int(cfg.limits.get("max_covers", 30))]
            results = download_covers(client, cover_targets, cfg, logger)
            for video, result in zip(cover_targets, results):
                if result.get("path"):
                    store.update_video(video["bvid"], cover_path=result["path"])
                    counts["covers"] += 1
            sheet_dir = cfg.output_dir / "covers" / "library" / "sheets"
            write_contact_sheets(cover_targets, sheet_dir, cfg, per_sheet=6)

        # Reports, plan, dashboard.
        top = store.list_videos(since_ts=begin, limit=20)
        analyses = load_analyses(cfg.data_dir)
        daily_path = render_daily(today_str(), top, analyses, cfg) if not args.no_report else None
        week = week_key()
        plan = latest_plan(cfg.data_dir, week)
        weekly_path = None
        if plan:
            weekly_path = render_weekly(week, plan, top, analyses, cfg)
            render_all_script_html(cfg, plan)
        dashboard = render_dashboard(cfg, store, plan) if not args.no_render else None
        pack_dir = create_analysis_pack(cfg, store, top_n=int(args.pack_top or 20)) if not args.no_pack else None

        counts.update(
            {
                "transcripts_ok": counts["transcripts_ok"],
                "transcripts_missing": counts["transcripts_missing"],
                "errors": counts["errors"],
                "errors_sample": errors[:5],
            }
        )
        store.finish_run(run_id, counts, "ok" if counts["kept"] else "empty")
        print(json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "counts": counts,
                "daily": str(daily_path) if daily_path else "",
                "weekly": str(weekly_path) if weekly_path else "",
                "dashboard": str(dashboard) if dashboard else "",
                "analysis_pack": str(pack_dir) if pack_dir else "",
            },
            ensure_ascii=False,
            indent=2,
        ))
        if args.open and dashboard:
            open_path(dashboard)
        return 0
    except BiliAuthError as exc:
        counts["errors"] += 1
        errors.append(str(exc))
        store.finish_run(run_id, counts, "error", str(exc))
        logger.error("Collect failed: %s", exc)
        print(json.dumps({"ok": False, "error": str(exc), "hint": "Chrome 未登录或 cookies 失效；先打开 bilibili.com 登录，再跑 collect --refresh-cookies"}, ensure_ascii=False, indent=2))
        return 2
    except Exception as exc:
        counts["errors"] += 1
        errors.append(f"{type(exc).__name__}: {exc}")
        store.finish_run(run_id, counts, "error", str(exc))
        logger.exception("Collect failed")
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 1
    finally:
        if client:
            client.close()
        store.close()


def create_analysis_pack(cfg: Config, store: Store, top_n: int = 20) -> Path:
    date = today_str()
    out = ensure_dir(cfg.data_dir / "analysis" / date)
    videos = store.list_videos(since_ts=days_ago_ts(7), limit=top_n)
    pack_videos = []
    for video in videos:
        item = dict(video)
        transcript = cfg.data_dir / "transcripts" / f"{video['bvid']}.md"
        item["transcript_exists"] = transcript.exists()
        item["transcript_chars"] = transcript.stat().st_size if transcript.exists() else 0
        item["transcript_path"] = str(transcript) if transcript.exists() else ""
        item["cover_exists"] = bool(video.get("cover_path") and Path(video["cover_path"]).exists())
        pack_videos.append(item)
    write_json(
        out / "top.json",
        {
            "date": date,
            "week": week_key(),
            "creator": cfg.creator,
            "keywords": [k.get("term") for k in cfg.keywords],
            "videos": pack_videos,
        },
    )
    write_compact_pack(videos, cfg.data_dir, out / "transcripts.md")
    with_cover = [v for v in videos if v.get("cover_path") and Path(v["cover_path"]).exists()]
    if with_cover:
        contact_sheet(with_cover[:6], out / "contact-sheet.jpg", cfg)
    _write_analysis_prompt(out, cfg, len(videos))
    return out


def _write_analysis_prompt(out: Path, cfg: Config, count: int) -> None:
    week = week_key()
    prompt = f"""# B站爆款内容分析任务包 · {today_str()}

本目录包含 {count} 条近 7 天爆款候选。请按 `.dsh/skills/bilibili-viral/SKILL.md` 的流程完成分析、周计划、脚本和封面规格。

## 输入文件

- `top.json`：视频元数据、统计、关键词、封面路径、字幕路径。
- `transcripts.md`：竞品口播压缩包（无字幕的条目标注原因）。
- `contact-sheet.jpg`：封面接触表（如果生成）。

## 输出 1：单条分析

写到 `data/analysis/{today_str()}.json`，结构：

```json
{{
  "date": "{today_str()}",
  "videos": [
    {{
      "bvid": "BV...",
      "topic": "一句话选题（不是标题复述）",
      "why_viral": ["爆点1", "爆点2", "爆点3"],
      "hook": "前 3 秒钩子的逐字拆解",
      "structure": ["0:00 钩子", "0:15 冲突", "..."],
      "remake_angle": "我能怎么差异化重做，必须具体",
      "audience": "谁会被打动，为什么",
      "cover": {{
        "style": "黑黄大字/左右对比/截图标注/渐变科技/人像大字",
        "text": "封面大字",
        "color": "主色 hex + 辅助色",
        "why": "为什么这个封面能提高点击",
        "formula": "可复用公式"
      }},
      "scores": {{"topic": 8, "cover": 7, "script": 8, "production": 6}},
      "risks": ["事实/版权/合规风险"]
    }}
  ]
}}
```

## 输出 2：本周 5 条计划

写到 `data/plans/{week}.json`，结构：

```json
{{
  "week": "{week}",
  "theme": "本周主题",
  "summary": "一句话策略",
  "ideas": [
    {{
      "id": "w01",
      "day": "周一",
      "topic": "选题",
      "title_options": ["标题1", "标题2", "标题3"],
      "hook": "前 3 秒",
      "angle": "差异化",
      "why_now": "为什么现在做",
      "outline": ["0:00 ...", "0:20 ...", "..."],
      "refs": ["BV...", "BV..."],
      "cover_title": "封面大字",
      "cover_subtitle": "封面副标题",
      "badge": "AI 工具",
      "difficulty": "低/中/高",
      "fact_checks": ["需要核实的事实"],
      "script_path": "output/scripts/{week}-w01-xxx.md"
    }}
  ]
}}
```

约束：5 条；至少 2 条来自 AI 工具/效率，至少 1 条来自副业/个人 IP；每条引用至少 2 个真实 BV；不出镜、录屏+口播、3-6 分钟。

## 输出 3：脚本

每条写到 `output/scripts/{week}-<id>-<slug>.md`，必须包含：

1. `## 钩子` 前 3 秒逐字稿
2. `## 结构` 时间轴/段落
3. `## 口播正文` 900-1800 字，口语化，可直接念
4. `## 分镜/录屏清单` 每个画面拍什么
5. `## 竞品参考` 至少 2 个 BV + 借鉴点 + 不照抄的差异化
6. `## 事实核查` 工具版本/价格/数据来源
7. `## 发布信息` 标题 3 个、封面大字、简介、标签

不要复制竞品原句；8-gram 重合必须 <15%。

## 输出 4：封面规格

写到 `data/cover_specs/{week}.json`：

```json
{{
  "week": "{week}",
  "covers": [
    {{
      "id": "w01",
      "idea_id": "w01",
      "style": "black_yellow",
      "title": "封面大字",
      "subtitle": "副标题",
      "badge": "AI 工具",
      "accent": "#FFD400",
      "ref_bvid": "BV..."
    }}
  ]
}}
```

## 完成后自检

```bash
python3 -m bili_viral validate
python3 -m bili_viral scriptcheck --week {week}
python3 -m bili_viral cover --week {week}
python3 -m bili_viral render
```
"""
    (out / "prompt.md").write_text(prompt, encoding="utf-8")


def cmd_analyze_pack(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    store = Store(cfg.db_path)
    try:
        out = create_analysis_pack(cfg, store, top_n=int(args.top or 20))
        print(json.dumps({"ok": True, "pack": str(out), "prompt": str(out / "prompt.md")}, ensure_ascii=False, indent=2))
        return 0
    finally:
        store.close()


def cmd_render(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    store = Store(cfg.db_path)
    try:
        plan = latest_plan(cfg.data_dir)
        if plan:
            render_all_script_html(cfg, plan)
        path = render_dashboard(cfg, store, plan)
        print(json.dumps({"ok": True, "dashboard": str(path)}, ensure_ascii=False, indent=2))
        if args.open:
            open_path(path)
        return 0
    finally:
        store.close()


def cmd_validate(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    errors: List[Dict[str, Any]] = []
    checked = 0
    for path in sorted((cfg.data_dir / "analysis").glob("*.json")):
        data = read_json(path, default=None)
        problems = validate_analysis(data)
        checked += 1
        if problems:
            errors.append({"file": str(path), "errors": problems})
    for path in sorted((cfg.data_dir / "plans").glob("*.json")):
        data = read_json(path, default=None)
        problems = validate_plan(data)
        checked += 1
        if problems:
            errors.append({"file": str(path), "errors": problems})
    print(json.dumps({"ok": not errors, "checked": checked, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def cmd_cover(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    week = args.week or week_key()
    store = Store(cfg.db_path)
    try:
        plan = latest_plan(cfg.data_dir, week)
        if not plan:
            print(json.dumps({"ok": False, "error": f"没有 {week} 的周计划：data/plans/{week}.json"}, ensure_ascii=False))
            return 1
        specs = load_specs(cfg.data_dir, week)
        videos = store.list_videos(limit=200)
        if not specs:
            specs = build_specs(plan, videos)
            write_json(cfg.data_dir / "cover_specs" / f"{week}.json", {"week": week, "covers": specs})
        meta = generate_covers(specs, cfg, week, videos)
        print(json.dumps({"ok": True, "week": week, "count": len(meta.get("items", [])), "out": str(cfg.output_dir / "covers" / "generated" / week)}, ensure_ascii=False, indent=2))
        if args.open:
            open_path(cfg.output_dir / "covers" / "generated" / week)
        return 0
    finally:
        store.close()


def cmd_scriptcheck(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    plan = latest_plan(cfg.data_dir, args.week) if not args.script else None
    targets: List[Tuple[Path, List[str]]] = []
    if args.script:
        path = Path(args.script)
        if not path.is_absolute():
            path = cfg.root / path
        targets.append((path, []))
    elif plan:
        for idea in plan.get("ideas", []):
            raw = idea.get("script_path")
            if not raw:
                continue
            path = Path(raw)
            if not path.is_absolute():
                path = cfg.root / raw
            targets.append((path, list(idea.get("refs", []))))
    else:
        print(json.dumps({"ok": False, "error": "没有可检查的周计划；用 --script 指定单个脚本"}, ensure_ascii=False))
        return 1
    results = []
    failed = 0
    for path, refs in targets:
        result = check_script(path, refs, cfg.data_dir, cfg)
        results.append(result)
        if not result.get("ok"):
            failed += 1
    out = cfg.data_dir / "runs" / f"scriptcheck-{args.week or week_key()}.json"
    write_json(out, {"week": args.week or week_key(), "ok": failed == 0, "results": results})
    print(json.dumps({"ok": failed == 0, "checked": len(results), "failed": failed, "report": str(out), "results": results}, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


def cmd_prune(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    days = int(args.days or cfg.project.get("retention_days", 90))
    before = days_ago_ts(days)
    store = Store(cfg.db_path)
    try:
        deleted = store.prune(before)
        print(json.dumps({"ok": True, "deleted": deleted, "before_ts": before, "days": days}, ensure_ascii=False, indent=2))
        return 0
    finally:
        store.close()


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    store = Store(cfg.db_path)
    try:
        data = {
            "counts": store.counts(),
            "latest_runs": store.latest_runs(5),
            "dashboard": str(cfg.output_dir / "dashboard" / "index.html"),
            "dashboard_exists": (cfg.output_dir / "dashboard" / "index.html").exists(),
            "plans": [p.stem for p in sorted((cfg.data_dir / "plans").glob("*.json"))],
            "analysis_files": [p.stem for p in sorted((cfg.data_dir / "analysis").glob("*.json"))],
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    finally:
        store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bili_viral", description="B站爆款内容雷达")
    parser.add_argument("--config", default=None, help="config.yaml 路径")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="检查环境、登录、API、字体与磁盘")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("collect", help="抓取爆款、字幕、封面并生成报告/仪表盘")
    p.add_argument("--days", type=int, default=None, help="回填天数；默认 2，首次建议 7")
    p.add_argument("--pages", type=int, default=None, help="每个关键词每个排序抓几页")
    p.add_argument("--refresh-cookies", action="store_true", help="强制从 Chrome 重新读取 cookies")
    p.add_argument("--no-transcripts", action="store_true")
    p.add_argument("--no-covers", action="store_true")
    p.add_argument("--no-report", action="store_true")
    p.add_argument("--no-render", action="store_true")
    p.add_argument("--no-pack", action="store_true")
    p.add_argument("--pack-top", type=int, default=20)
    p.add_argument("--open", action="store_true", help="结束后打开仪表盘")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("render", help="只重渲染仪表盘/脚本 HTML")
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("validate", help="校验 data/analysis 与 data/plans JSON")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("cover", help="按周计划生成 2 版封面")
    p.add_argument("--week", default=None)
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_cover)

    p = sub.add_parser("scriptcheck", help="检查脚本原创性、结构与合规")
    p.add_argument("--week", default=None)
    p.add_argument("--script", default=None)
    p.set_defaults(func=cmd_scriptcheck)

    p = sub.add_parser("analyze-pack", help="生成 agent 分析任务包")
    p.add_argument("--top", type=int, default=20)
    p.set_defaults(func=cmd_analyze_pack)

    p = sub.add_parser("prune", help="清理超过保留期的数据")
    p.add_argument("--days", type=int, default=None)
    p.set_defaults(func=cmd_prune)

    p = sub.add_parser("status", help="查看数据库/计划/仪表盘状态")
    p.set_defaults(func=cmd_status)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
