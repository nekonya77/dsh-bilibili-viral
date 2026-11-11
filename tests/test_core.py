"""Offline unit tests for the B站爆款雷达. No network calls."""
from __future__ import annotations

import datetime
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

from bili_viral.analysis import validate_analysis, validate_plan
from bili_viral.config import load_config
from bili_viral.covergen import render_cover
from bili_viral.rank import dedupe, passes_filters, score_videos
from bili_viral.report import render_daily
from bili_viral.render import render_dashboard
from bili_viral.scriptcheck import check_script, containment
from bili_viral.store import Store
from bili_viral.util import chinese_char_count, human_num, parse_duration, week_key


def make_video(**kwargs):
    now = int(time.time())
    data = {
        "bvid": "BV1ab411c7de",
        "aid": 1,
        "title": "我用 AI 把 3 小时的活压到 12 分钟",
        "clean_title": "我用 AI 把 3 小时的活压到 12 分钟",
        "pic": "",
        "play": 50000,
        "like": 2500,
        "favorite": 1800,
        "coin": 600,
        "share": 300,
        "reply": 200,
        "danmaku": 100,
        "pubdate": now - 3600 * 24,
        "duration_s": 300,
        "tags": ["AI", "效率"],
        "typename": "科技",
        "parent_area": "科技",
        "owner_mid": 1,
        "owner_name": "测试UP",
        "follower": 10000,
        "keyword": "AI工具",
        "keyword_group": "AI效率",
        "relevance": 0.9,
    }
    data.update(kwargs)
    return data


class TestUtil(unittest.TestCase):
    def test_parse_and_format(self):
        self.assertEqual(parse_duration("12:34"), 754)
        self.assertEqual(parse_duration(90), 90)
        self.assertEqual(parse_duration("1:02:03"), 3723)
        self.assertEqual(human_num(12345), "1.2万")
        self.assertRegex(week_key(), r"^\d{4}-W\d{2}$")


class TestConfigAndStore(unittest.TestCase):
    def test_config_creates_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(root=Path(tmp))
            self.assertTrue(cfg.data_dir.exists())
            self.assertTrue(cfg.output_dir.exists())
            self.assertTrue(cfg.db_path.parent.exists())
            self.assertGreaterEqual(len(cfg.keywords), 5)

    def test_store_upsert_and_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.db")
            video = make_video()
            store.upsert_video(video)
            self.assertEqual(store.get_video(video["bvid"])["play"], 50000)
            store.update_video(video["bvid"], play=90000, cover_path="/tmp/a.jpg")
            row = store.get_video(video["bvid"])
            self.assertEqual(row["play"], 90000)
            self.assertEqual(row["cover_path"], "/tmp/a.jpg")
            self.assertEqual(store.counts()["videos"], 1)
            store.close()


class TestRank(unittest.TestCase):
    def test_filter_and_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(root=Path(tmp))
            now = int(time.time())
            video = make_video()
            self.assertTrue(passes_filters(video, cfg, now - 86400 * 7, now + 60))
            bad = make_video(bvid="BV1bad", typename="游戏", parent_area="游戏")
            self.assertFalse(passes_filters(bad, cfg, now - 86400 * 7, now + 60))
            short = make_video(bvid="BV1short", duration_s=10)
            self.assertFalse(passes_filters(short, cfg, now - 86400 * 7, now + 60))
            self.assertEqual(len(dedupe([video, video])), 1)

    def test_scores_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(root=Path(tmp))
            videos = [
                make_video(bvid=f"BV1ab411c7d{i}", play=10000 * (i + 1), score=0)
                for i in range(5)
            ]
            scored = score_videos(videos, cfg)
            self.assertEqual(len(scored), 5)
            for v in scored:
                self.assertGreaterEqual(v["score"], 0)
                self.assertLessEqual(v["score"], 100)
                self.assertIn("score_json", v)


class TestScriptCheck(unittest.TestCase):
    def _script(self, body: str, bvids=("BV1ab411c7de", "BV1cd411c7ef")):
        return f"""# 标题

## 钩子
{body}

## 结构
- 0:00 钩子
- 0:20 背景
- 1:00 演示

## 分镜
| 时间 | 画面 | 口播 |
|---|---|---|
| 0:00 | 录屏 | {body[:40]} |

## 竞品参考
- {bvids[0]}：借结构
- {bvids[1]}：借封面

## 事实核查
- [x] 工具版本
"""

    def test_containment_detects_copy(self):
        ref = "这个竞品用采访和街拍讲述普通人转行的经历" * 40
        copy = "这个竞品用采访和街拍讲述普通人转行的经历" * 20
        self.assertGreater(containment(copy, ref), 0.5)

    def test_clean_script_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = load_config(root=root)
            script = root / "script.md"
            body = "我把表格拖进工作流以后每天少做两小时重复操作，省下的时间用来写脚本和复盘数据。" * 30
            script.write_text(self._script(body), encoding="utf-8")
            self.assertGreaterEqual(chinese_char_count(script.read_text(encoding="utf-8")), 900)
            result = check_script(script, ["BV1ab411c7de", "BV1cd411c7ef"], cfg.data_dir, cfg)
            self.assertTrue(result["ok"], result["errors"])

    def test_overlap_script_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = load_config(root=root)
            (cfg.data_dir / "transcripts").mkdir(parents=True, exist_ok=True)
            ref_text = "这个竞品用采访和街拍讲述普通人转行的经历" * 40
            (cfg.data_dir / "transcripts" / "BV1ab411c7de.md").write_text(ref_text, encoding="utf-8")
            script = root / "script.md"
            script.write_text(self._script(ref_text * 2), encoding="utf-8")
            result = check_script(script, ["BV1ab411c7de"], cfg.data_dir, cfg)
            self.assertFalse(result["ok"])
            self.assertTrue(any("重合度" in e for e in result["errors"]))


class TestAnalysis(unittest.TestCase):
    def test_validate_good_plan(self):
        idea = {
            "id": "w01",
            "day": "周一",
            "topic": "用 AI 自动整理会议纪要",
            "title_options": ["3 分钟整理完 2 小时会议"],
            "refs": ["BV1ab411c7de", "BV1cd411c7ef"],
            "script_path": "output/scripts/w01.md",
            "outline": ["0:00 钩子"],
        }
        plan = {"week": "2026-W47", "ideas": [dict(idea, id=f"w0{i}") for i in range(1, 6)]}
        self.assertEqual(validate_plan(plan), [])
        self.assertEqual(validate_plan({"week": "2026-W47", "ideas": []}), ["plan.ideas should contain 5 ideas, got 0"])

    def test_validate_analysis(self):
        good = {
            "videos": [
                {
                    "bvid": "BV1ab411c7de",
                    "topic": "AI 整理会议纪要",
                    "why_viral": ["省时间"],
                    "cover": {"style": "black_yellow"},
                    "scores": {"topic": 8},
                }
            ]
        }
        self.assertEqual(validate_analysis(good), [])
        self.assertTrue(validate_analysis({"videos": [{"bvid": "x"}]}))


class TestCoverAndRender(unittest.TestCase):
    def test_five_styles_render_1280x720(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = load_config(root=root)
            base = root / "base.jpg"
            Image.new("RGB", (800, 450), (30, 30, 40)).save(base)
            for idx, style in enumerate(
                ["black_yellow", "split_compare", "screenshot_callout", "gradient_tech", "face_bigtext"]
            ):
                spec = {
                    "id": f"w0{idx}",
                    "style": style,
                    "title": "3 小时活压到 12 分钟",
                    "subtitle": "不用学编程",
                    "badge": "AI 工具",
                    "accent": "#FFD400",
                }
                out = root / f"{style}.jpg"
                render_cover(spec, out, cfg, variant=1, cover_path=str(base))
                self.assertTrue(out.exists())
                with Image.open(out) as img:
                    self.assertEqual(img.size, (1280, 720))

    def test_dashboard_and_daily_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = load_config(root=root)
            store = Store(cfg.db_path)
            store.upsert_video(make_video())
            dashboard = render_dashboard(cfg, store, None)
            self.assertTrue(dashboard.exists())
            self.assertIn("B站", dashboard.read_text(encoding="utf-8"))
            daily = render_daily("2026-11-11", [], {}, cfg)
            self.assertTrue(daily.exists())
            store.close()


if __name__ == "__main__":
    unittest.main()
