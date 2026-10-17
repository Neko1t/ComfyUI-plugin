"""Transactional local state. Public projections never include credentials or signed URLs."""

from __future__ import annotations

import ipaddress
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


def identifier(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("节点/记录标识无效，请重新创建节点") from exc


def api_base(value: str) -> str:
    parts = urlsplit(value.strip().rstrip("/"))
    local = parts.hostname == "localhost"
    try:
        local = local or ipaddress.ip_address(parts.hostname or "").is_loopback
    except ValueError:
        pass
    if (
        parts.scheme not in {"http", "https"}
        or (parts.scheme == "http" and not local)
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
    ):
        raise ValueError("API 地址须为 HTTPS 根地址（本机测试可用 HTTP），例如 https://vividai.run")
    return value.strip().rstrip("/")


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.cache = self.root / "cache"
        self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = self.root / "state.sqlite3"
        self._lock = threading.RLock()
        self._leases: dict[str, int] = {}
        with self._db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS profiles
                    (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                     base TEXT NOT NULL, secret TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks
                    (node TEXT, intent TEXT, body TEXT NOT NULL, PRIMARY KEY(node,intent));
                CREATE TABLE IF NOT EXISTS garbage (name TEXT PRIMARY KEY);
                PRAGMA user_version=1;
            """)
        os.chmod(self.db_path, 0o600)
        # A process may have died after downloading but before committing a material.
        # Only this single-instance store owns the cache; unknown names/symlinks are untouched.
        with self._db() as db:
            live = {
                item["file"]
                for row in db.execute("SELECT body FROM nodes")
                for item in json.loads(row[0])["history"]
            }
            for path in self.cache.iterdir():
                if path.name in live:
                    continue
                try:
                    self.cache_path(path.name)
                except ValueError:
                    continue
                db.execute("INSERT OR IGNORE INTO garbage VALUES (?)", (path.name,))
        self.collect()

    @contextmanager
    def _db(self):
        with self._lock, sqlite3.connect(self.db_path, timeout=15) as db:
            db.row_factory = sqlite3.Row
            yield db

    def profiles(self) -> list[dict]:
        with self._db() as db:
            return [
                dict(row) for row in db.execute("SELECT id,name,base FROM profiles ORDER BY name")
            ]

    def save_profile(self, name: str, base: str, secret: str, ref: str | None = None) -> str:
        ref = identifier(ref) if ref else str(uuid.uuid4())
        if not name.strip() or not secret.strip() or len(secret) > 4096:
            raise ValueError("请填写配置名称和 API Key")
        if "\n" in secret or "\r" in secret:
            raise ValueError("API Key 不能包含换行")
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO profiles VALUES (?,?,?,?)",
                (ref, name.strip()[:100], api_base(base), secret.strip()),
            )
        return ref

    def profile(self, ref: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT * FROM profiles WHERE id=?", (ref,)).fetchone()
        if row is None:
            raise ValueError("本机未找到此连接配置，请在 VividAI 配置节点中保存 API Key")
        return dict(row)

    def delete_profile(self, ref: str):
        with self._db() as db:
            db.execute("DELETE FROM profiles WHERE id=?", (ref,))

    @staticmethod
    def _node(db, key):
        row = db.execute("SELECT body FROM nodes WHERE id=?", (key,)).fetchone()
        return (
            json.loads(row[0])
            if row
            else {
                "id": key,
                "history": [],
                "selected": None,
                "active": None,
                "capacity": 3,
            }
        )

    @staticmethod
    def _put(db, node):
        db.execute("INSERT OR REPLACE INTO nodes VALUES (?,?)", (node["id"], json.dumps(node)))

    def node(self, key: str) -> dict:
        key = identifier(key)
        with self._db() as db:
            return self._node(db, key)

    def task(self, key: str, intent: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT body FROM tasks WHERE node=? AND intent=?", (key, intent))
            row = row.fetchone()
        return json.loads(row[0]) if row else None

    def begin(self, key: str, intent: str, snapshot: dict, ref: str, kind: str) -> dict:
        key = identifier(key)
        task = {
            "intent": intent,
            "state": "prepared",
            "snapshot": snapshot,
            "profile": ref,
            "kind": kind,
            "job_id": None,
            "created": time.time(),
        }
        with self._db() as db:
            db.execute("INSERT INTO tasks VALUES (?,?,?)", (key, intent, json.dumps(task)))
            node = self._node(db, key)
            node["active"] = intent
            self._put(db, node)
        return task

    def update_task(self, key: str, intent: str, **updates) -> dict:
        with self._db() as db:
            row = db.execute("SELECT body FROM tasks WHERE node=? AND intent=?", (key, intent))
            task = json.loads(row.fetchone()[0])
            task.update(updates)
            db.execute(
                "UPDATE tasks SET body=? WHERE node=? AND intent=?", (json.dumps(task), key, intent)
            )
        return task

    def cache_path(self, name: str) -> Path:
        # No caller can turn cache cleanup or preview into arbitrary filesystem access.
        path = self.cache / name
        if (
            Path(name).name != name
            or path.is_symlink()
            or path.resolve().parent != self.cache.resolve()
            or path.suffix not in {".png", ".mp4", ".part"}
        ):
            raise ValueError("缓存文件路径无效")
        identifier(path.stem)
        return path

    def new_path(self, suffix: str) -> Path:
        return self.cache_path(f"{uuid.uuid4()}{suffix}")

    def _trim(self, db, node):
        removed = node["history"][node["capacity"] :]
        node["history"] = node["history"][: node["capacity"]]
        for item in removed:
            db.execute("INSERT OR IGNORE INTO garbage VALUES (?)", (item["file"],))

    def capacity(self, key: str, capacity: int):
        if isinstance(capacity, bool) or not 1 <= capacity <= 100:
            raise ValueError("历史容量须为 1–100")
        key = identifier(key)
        with self._db() as db:
            node = self._node(db, key)
            node["capacity"] = capacity
            self._trim(db, node)
            self._put(db, node)
        self.collect()

    def complete(self, key: str, intent: str, path: Path, snapshot: dict, kind: str) -> dict:
        if self.cache_path(path.name) != path.resolve() or not path.is_file():
            raise ValueError("生成结果尚未保存在插件缓存中")
        material = {
            "id": str(uuid.uuid4()),
            "file": path.name,
            "snapshot": snapshot,
            "kind": kind,
            "created": time.time(),
        }
        with self._db() as db:
            node = self._node(db, key)
            node["history"].insert(0, material)
            node["selected"] = material["id"]
            node["active"] = None
            self._trim(db, node)
            self._put(db, node)
            row = db.execute("SELECT body FROM tasks WHERE node=? AND intent=?", (key, intent))
            task = json.loads(row.fetchone()[0])
            task.update(state="succeeded", material=material["id"])
            db.execute(
                "UPDATE tasks SET body=? WHERE node=? AND intent=?", (json.dumps(task), key, intent)
            )
        self.collect()
        return material

    def activate(self, key: str, material_id: str):
        with self._db() as db:
            node = self._node(db, identifier(key))
            if node["active"]:
                row = db.execute(
                    "SELECT body FROM tasks WHERE node=? AND intent=?", (key, node["active"])
                ).fetchone()
                if json.loads(row[0])["state"] in {"prepared", "submitting", "running"}:
                    raise ValueError("任务仍待恢复，请先完成原任务")
            item = next((x for x in node["history"] if x["id"] == material_id), None)
            if item is None or not self.cache_path(item["file"]).is_file():
                raise ValueError("此素材已被淘汰或文件缺失")
            node["history"].remove(item)
            node["history"].insert(0, item)
            node["selected"] = material_id
            node["active"] = None
            self._put(db, node)

    def selected(self, key: str) -> dict | None:
        node = self.node(key)
        return next((x for x in node["history"] if x["id"] == node["selected"]), None)

    def acquire(self, name: str):
        path = self.cache_path(name)
        with self._lock:
            self._leases[name] = self._leases.get(name, 0) + 1
        released = False

        def release():
            nonlocal released
            with self._lock:
                if not released:
                    released = True
                    self._leases[name] -= 1
                    self.collect()

        return path, release

    @contextmanager
    def lease(self, name: str):
        path, release = self.acquire(name)
        try:
            yield path
        finally:
            release()

    def collect(self):
        with self._db() as db:
            for row in db.execute("SELECT name FROM garbage").fetchall():
                name = row[0]
                if self._leases.get(name, 0):
                    continue
                try:
                    self.cache_path(name).unlink(missing_ok=True)
                except OSError:
                    continue  # A Windows decoder may still hold the file; retry later.
                db.execute("DELETE FROM garbage WHERE name=?", (name,))

    def public_node(self, key: str) -> dict:
        node = self.node(key)
        task = self.task(key, node["active"]) if node["active"] else None
        return node | {
            "task": {
                k: task.get(k)
                for k in (
                    "state",
                    "job_id",
                    "error",
                    "created",
                )
            }
            if task
            else None
        }
