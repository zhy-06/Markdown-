#!/usr/bin/env python3
# md_index.py

import os
import sqlite3
import frontmatter

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE,
  mtime INTEGER,
  tags TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(path UNINDEXED, content, tags, tokenize = 'unicode61');
"""

class MDIndexer:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _parse(self, filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)
        content = post.content or ""
        tags = post.get("tags") or post.get("tag") or []
        if isinstance(tags, list):
            tags = ",".join(tags)
        elif tags is None:
            tags = ""
        return content, tags

    def index_path(self, path):
        path = os.path.abspath(path)
        for root, _, files in os.walk(path):
            for fn in files:
                if not fn.lower().endswith(".md"):
                    continue
                full = os.path.join(root, fn)
                self.index_file(full)

    def index_file(self, filepath):
        try:
            m = int(os.path.getmtime(filepath))
        except OSError:
            return
        cur = self.conn.cursor()
        cur.execute("SELECT mtime FROM files WHERE path = ?", (filepath,))
        row = cur.fetchone()
        if row and row[0] == m:
            return  # unchanged
        content, tags = ("", "")
        try:
            content, tags = self._parse(filepath)
        except Exception:
            # if parse fails, still index raw content fallback
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                content = ""
        # upsert files table
        cur.execute("""
            INSERT INTO files (path, mtime, tags)
            VALUES (?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, tags=excluded.tags
        """, (filepath, m, tags))
        # replace doc in FTS
        cur.execute("DELETE FROM docs WHERE path = ?", (filepath,))
        cur.execute("INSERT INTO docs (path, content, tags) VALUES (?, ?, ?)", (filepath, content, tags))
        self.conn.commit()

    def search(self, q, limit=50):
        cur = self.conn.cursor()
        # Use parameterized query with MATCH; prepare query as-is
        try:
            cur.execute("SELECT path, snippet(docs, 1, '[', ']', '...', 10) as snippet FROM docs WHERE docs MATCH ? LIMIT ?", (q, limit))
            return cur.fetchall()
        except sqlite3.OperationalError:
            # fallback to simple LIKE search
            q_like = f"%{q}%"
            cur.execute("SELECT path, substr(content, instr(content, ?)-40, 120) FROM docs WHERE content LIKE ? LIMIT ?", (q, q_like, limit))
            return cur.fetchall()