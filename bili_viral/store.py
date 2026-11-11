"""SQLite persistence for videos, UPs and runs."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .util import now_cn, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    bvid TEXT PRIMARY KEY,
    aid INTEGER,
    title TEXT,
    clean_title TEXT,
    pic TEXT,
    play INTEGER DEFAULT 0,
    like INTEGER DEFAULT 0,
    favorite INTEGER DEFAULT 0,
    coin INTEGER DEFAULT 0,
    share INTEGER DEFAULT 0,
    reply INTEGER DEFAULT 0,
    danmaku INTEGER DEFAULT 0,
    pubdate INTEGER,
    duration_s INTEGER DEFAULT 0,
    tags TEXT,
    typename TEXT,
    parent_area TEXT,
    owner_mid INTEGER,
    owner_name TEXT,
    follower INTEGER,
    keyword TEXT,
    keyword_group TEXT,
    relevance REAL DEFAULT 0,
    score REAL DEFAULT 0,
    score_json TEXT,
    is_hot INTEGER DEFAULT 0,
    transcript_status TEXT,
    cover_path TEXT,
    description TEXT,
    cid INTEGER,
    first_seen TEXT,
    last_seen TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS ups (
    mid INTEGER PRIMARY KEY,
    name TEXT,
    follower INTEGER,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    window_days INTEGER,
    keywords_json TEXT,
    counts_json TEXT,
    status TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_videos_pubdate ON videos(pubdate);
CREATE INDEX IF NOT EXISTS idx_videos_score ON videos(score);
CREATE INDEX IF NOT EXISTS idx_videos_keyword ON videos(keyword_group);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);
"""

JSON_FIELDS = {"tags", "score_json", "raw_json"}


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    @staticmethod
    def _dump(value: Any) -> Any:
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return value

    def upsert_video(self, video: Dict[str, Any]) -> None:
        data = dict(video)
        now = now_iso()
        data.setdefault("first_seen", now)
        data["last_seen"] = now
        for field in JSON_FIELDS:
            if field in data:
                data[field] = self._dump(data[field])
        columns = [
            "bvid", "aid", "title", "clean_title", "pic", "play", "like",
            "favorite", "coin", "share", "reply", "danmaku", "pubdate",
            "duration_s", "tags", "typename", "parent_area", "owner_mid",
            "owner_name", "follower", "keyword", "keyword_group", "relevance",
            "score", "score_json", "is_hot", "transcript_status", "cover_path",
            "description", "cid", "first_seen", "last_seen", "raw_json",
        ]
        values = [data.get(c) for c in columns]
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(
            f"{c}=excluded.{c}" for c in columns if c not in ("bvid", "first_seen")
        )
        sql = (
            f"INSERT INTO videos ({','.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(bvid) DO UPDATE SET {updates}"
        )
        self.conn.execute(sql, values)
        self.conn.commit()

    def upsert_many(self, videos: Iterable[Dict[str, Any]]) -> None:
        for video in videos:
            self.upsert_video(video)

    def update_video(self, bvid: str, **fields: Any) -> None:
        if not fields:
            return
        fields["last_seen"] = now_iso()
        for field in JSON_FIELDS:
            if field in fields:
                fields[field] = self._dump(fields[field])
        assignments = ",".join(f"{key}=?" for key in fields)
        self.conn.execute(
            f"UPDATE videos SET {assignments} WHERE bvid=?",
            list(fields.values()) + [bvid],
        )
        self.conn.commit()

    def get_video(self, bvid: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM videos WHERE bvid=?", (bvid,)).fetchone()
        return self._row(row) if row else None

    def list_videos(
        self,
        since_ts: Optional[int] = None,
        limit: Optional[int] = None,
        keyword_group: Optional[str] = None,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM videos WHERE 1=1"
        args: List[Any] = []
        if since_ts is not None:
            sql += " AND pubdate>=?"
            args.append(since_ts)
        if keyword_group:
            sql += " AND keyword_group=?"
            args.append(keyword_group)
        if min_score:
            sql += " AND score>=?"
            args.append(min_score)
        sql += " ORDER BY score DESC, play DESC"
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        rows = self.conn.execute(sql, args).fetchall()
        return [self._row(r) for r in rows]

    def all_bvids(self) -> List[str]:
        return [r[0] for r in self.conn.execute("SELECT bvid FROM videos").fetchall()]

    def upsert_up(self, mid: int, name: str, follower: Optional[int]) -> None:
        self.conn.execute(
            "INSERT INTO ups (mid,name,follower,updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(mid) DO UPDATE SET name=excluded.name, "
            "follower=excluded.follower, updated_at=excluded.updated_at",
            (mid, name, follower, now_iso()),
        )
        self.conn.commit()

    def get_up(self, mid: int) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM ups WHERE mid=?", (mid,)).fetchone()
        return dict(row) if row else None

    def start_run(self, run_id: str, window_days: int, keywords: List[str]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO runs "
            "(run_id,started_at,finished_at,window_days,keywords_json,counts_json,status,error) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                run_id,
                now_iso(),
                None,
                window_days,
                json.dumps(keywords, ensure_ascii=False),
                "{}",
                "running",
                None,
            ),
        )
        self.conn.commit()

    def finish_run(
        self,
        run_id: str,
        counts: Dict[str, Any],
        status: str = "ok",
        error: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, counts_json=?, status=?, error=? WHERE run_id=?",
            (
                now_iso(),
                json.dumps(counts, ensure_ascii=False),
                status,
                error,
                run_id,
            ),
        )
        self.conn.commit()

    def latest_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["keywords"] = json.loads(item.get("keywords_json") or "[]")
            item["counts"] = json.loads(item.get("counts_json") or "{}")
            out.append(item)
        return out

    def counts(self) -> Dict[str, Any]:
        total = self.conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        hot = self.conn.execute("SELECT COUNT(*) FROM videos WHERE is_hot=1").fetchone()[0]
        with_transcript = self.conn.execute(
            "SELECT COUNT(*) FROM videos WHERE transcript_status='ok'"
        ).fetchone()[0]
        return {
            "videos": total,
            "hot": hot,
            "with_transcript": with_transcript,
        }

    def prune(self, before_ts: int) -> int:
        cur = self.conn.execute("DELETE FROM videos WHERE pubdate < ?", (before_ts,))
        self.conn.commit()
        return cur.rowcount

    @staticmethod
    def _row(row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        for field in JSON_FIELDS:
            if field in item and isinstance(item[field], str):
                try:
                    item[field] = json.loads(item[field])
                except ValueError:
                    pass
        item["is_hot"] = bool(item.get("is_hot"))
        return item

    def health(self) -> Dict[str, Any]:
        try:
            self.conn.execute("SELECT 1").fetchone()
            db_ok = True
        except sqlite3.Error:
            db_ok = False
        return {
            "db_ok": db_ok,
            "path": str(self.path),
            "size_mb": round(self.path.stat().st_size / (1024 * 1024), 2)
            if self.path.exists()
            else 0,
            "counts": self.counts(),
        }
