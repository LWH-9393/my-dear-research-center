#!/usr/bin/env python3
"""AI-triggered research refresh, local semantic search and citation graphs."""
from __future__ import annotations

import argparse
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
import subprocess
import uuid

from index_inputs import (CHUNK_VERSION, INDEX_VERSION, META, TABLES, IndexProblem,
                          canonical_json, ensure_metadata, metadata, sha, snapshot,
                          strict_json, write_metadata)
from index_graph import normalize_doi, openalex_alias, project, record_edges
from semantic_chunks import WINDOW_VERSION, validate_spans, pack_tail, unpack_tail

VERSION = "1.5.0"
DATA = Path.home() / ".local/share/my-dear-research-center"
DEFAULT_INDEX = DATA / "research-index.sqlite3"
SEMANTIC_ENV = DATA / "semantic-env"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
ST_REQUIREMENT = "sentence-transformers==5.7.0"


def now(): return datetime.now(timezone.utc).isoformat()


def stable_run_key(root, query_hash):
    """Legacy key, kept for schema-1 compatibility only."""
    return "run:" + sha(str(root.resolve()) + "\0" + query_hash)[:24]


def text_of(value):
    parts = []
    def visit(item):
        if isinstance(item, str): parts.append(item)
        elif isinstance(item, list):
            for x in item: visit(x)
        elif isinstance(item, dict):
            for key, x in item.items():
                if key not in {"evidence_sha256", "input_digest", "query_sha256"}: visit(x)
    visit(value)
    return "\n".join(x.strip() for x in parts if x.strip())


def chunks(text, maximum=1400, overlap=160):
    text = re.sub(r"[ \t]+", " ", text).strip()
    result, start = [], 0
    while start < len(text):
        end = min(len(text), start + maximum)
        if end < len(text):
            split = max(text.rfind("\n", start + maximum // 2, end), text.rfind(". ", start + maximum // 2, end))
            if split > start: end = split + 1
        value = text[start:end].strip()
        if value: result.append(value)
        if end == len(text): break
        start = max(start + 1, end - overlap)
    return result


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(run_key TEXT PRIMARY KEY,root TEXT UNIQUE,query_sha256 TEXT,fingerprint TEXT,synced_at TEXT);
CREATE TABLE IF NOT EXISTS records(run_key TEXT,kind TEXT,local_id TEXT,payload TEXT,PRIMARY KEY(run_key,kind,local_id));
CREATE TABLE IF NOT EXISTS record_edges(run_key TEXT,source_kind TEXT,source_id TEXT,target_kind TEXT,target_id TEXT,relation TEXT,evidence TEXT,PRIMARY KEY(run_key,source_kind,source_id,target_kind,target_id,relation));
CREATE TABLE IF NOT EXISTS works(work_key TEXT PRIMARY KEY,title TEXT,doi TEXT,metadata TEXT,external INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS aliases(alias TEXT PRIMARY KEY,work_key TEXT);
CREATE TABLE IF NOT EXISTS observations(run_key TEXT,candidate_id TEXT,work_key TEXT,provider TEXT,payload TEXT,PRIMARY KEY(run_key,candidate_id));
CREATE TABLE IF NOT EXISTS documents(global_id TEXT PRIMARY KEY,run_key TEXT,local_id TEXT,work_key TEXT,title TEXT,url TEXT,sha256 TEXT,metadata TEXT,UNIQUE(run_key,local_id));
CREATE TABLE IF NOT EXISTS texts(text_id TEXT PRIMARY KEY,run_key TEXT,kind TEXT,object_id TEXT,locator TEXT,ordinal INTEGER,text TEXT,text_sha256 TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS text_search USING fts5(text_id UNINDEXED,run_key UNINDEXED,kind UNINDEXED,object_id UNINDEXED,locator UNINDEXED,text,tokenize='unicode61');
CREATE TABLE IF NOT EXISTS embeddings(text_id TEXT,backend TEXT,model TEXT,revision TEXT,dimension INTEGER,vector BLOB,text_sha256 TEXT,PRIMARY KEY(text_id,backend,model,revision));
CREATE TABLE IF NOT EXISTS citation_edges(edge_id TEXT PRIMARY KEY,run_key TEXT,source_work TEXT,target_work TEXT,relation TEXT,provider TEXT,evidence TEXT,resolution TEXT);
CREATE TABLE IF NOT EXISTS sync_audits(run_key TEXT,synced_at TEXT,expected_record_edges INTEGER,indexed_record_edges INTEGER,expected_citations INTEGER,indexed_citations INTEGER,unresolved_citations INTEGER,malformed_citations INTEGER,PRIMARY KEY(run_key,synced_at));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
"""


class GlobalIndex:
    def __init__(self, path, readonly=False):
        self.path = Path(path).expanduser().resolve()
        self.readonly, self.missing = readonly, not self.path.exists()
        self.last_coverage = []
        if readonly:
            self.db = sqlite3.connect(":memory:") if self.missing else sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        else:
            if Path(str(self.path) + ".lock").exists():
                raise IndexProblem("busy", "legacy index lock exists; inspect its owner before recovery")
            new_parent = not self.path.parent.exists()
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if new_parent or self.path.parent == DATA: self.path.parent.chmod(0o700)
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600); os.close(fd)
            self.path.chmod(0o600)
            self.db = sqlite3.connect(self.path, timeout=1)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=1000")
        self.version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if self.version not in {0, 1, 2, 3}:
            self.db.close(); raise IndexProblem("schema_error", "unsupported global index schema")
        if not readonly or self.missing:
            self.db.execute("PRAGMA secure_delete=ON")
            self.db.executescript(SCHEMA)
            self._migrate()
        elif self.version == 0:
            self.db.close(); raise IndexProblem("schema_error", "uninitialized index database")

    def close(self): self.db.close()

    def _migrate(self):
        # No source-run writes here. IDs are adopted on the first explicit refresh.
        self.db.execute("BEGIN IMMEDIATE")
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS run_state(run_key TEXT PRIMARY KEY,run_id TEXT UNIQUE,checked_at TEXT,index_status TEXT,last_error TEXT,semantic_error TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,run_key TEXT,at TEXT,reason TEXT,status TEXT,error_code TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS scope_blocks(run_id TEXT PRIMARY KEY,scope TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS graph_coverage(run_key TEXT PRIMARY KEY,expected INTEGER,indexed INTEGER,duplicates INTEGER,unresolved INTEGER,malformed INTEGER)")
            columns = {r[1] for r in self.db.execute("PRAGMA table_info(embeddings)")}
            if "vector_sha256" not in columns:
                self.db.execute("ALTER TABLE embeddings ADD COLUMN vector_sha256 TEXT")
            if "chunk_version" not in columns:
                self.db.execute("ALTER TABLE embeddings ADD COLUMN chunk_version INTEGER DEFAULT 1")
            for row in self.db.execute("SELECT rowid,vector FROM embeddings WHERE vector_sha256 IS NULL").fetchall():
                self.db.execute("UPDATE embeddings SET vector_sha256=? WHERE rowid=?", (sha(row["vector"]), row["rowid"]))
            for column, declaration in (("window_manifest", "TEXT"), ("window_tail", "BLOB"), ("window_sha256", "TEXT")):
                if column not in columns:
                    self.db.execute("ALTER TABLE embeddings ADD COLUMN " + column + " " + declaration)
            self.db.execute("PRAGMA user_version=3")
        self.version = 3

    @contextmanager
    def transaction(self):
        if self.readonly: raise IndexProblem("readonly", "mutation requires a writable index")
        if self.db.in_transaction: raise IndexProblem("busy", "another transaction is active")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            yield
            self.db.commit()
        except Exception:
            self.db.rollback(); raise

    def _resolve(self, root, meta=None):
        root = str(Path(root).expanduser().resolve())
        row = self.db.execute("SELECT * FROM runs WHERE root=?", (root,)).fetchone()
        if self.version < 2: return row
        by_id = None
        if meta:
            by_id = self.db.execute("SELECT r.* FROM runs r JOIN run_state s USING(run_key) WHERE s.run_id=?", (meta["run_id"],)).fetchone()
        if by_id and by_id["root"] != root:
            raise IndexProblem("identity_conflict", "run ID is registered at another path; use relocate or fork")
        if row:
            state = self.db.execute("SELECT run_id FROM run_state WHERE run_key=?", (row["run_key"],)).fetchone()
            if state and state[0] and (not meta or state[0] != meta["run_id"]):
                raise IndexProblem("identity_conflict", "path belongs to another run ID")
        return row

    def _blocked(self, meta):
        if not meta: return False
        if meta["scope"] != "global": return True
        return self.version >= 2 and bool(self.db.execute("SELECT 1 FROM scope_blocks WHERE run_id=?", (meta["run_id"],)).fetchone())

    def _model(self):
        row = self.db.execute("SELECT value FROM settings WHERE key='semantic'").fetchone()
        return strict_json(row[0]) if row else None

    def semantic_status(self, run_key=None):
        config = self._model()
        where, args = (" WHERE run_key=?", [run_key]) if run_key else ("", [])
        total = self.db.execute("SELECT count(*) FROM texts" + where, args).fetchone()[0]
        ready = 0
        if config:
            sql = "SELECT count(*) FROM embeddings e JOIN texts t USING(text_id) WHERE e.backend='sentence-transformers' AND e.model=? AND e.revision=? AND e.text_sha256=t.text_sha256"
            values = [config["model"], config["revision"]]
            if self.version >= 2: sql += " AND e.chunk_version=?"; values.append(CHUNK_VERSION)
            if self.version >= 3: sql += " AND e.window_manifest IS NOT NULL"
            else: sql += " AND 0"
            if run_key: sql += " AND t.run_key=?"; values.append(run_key)
            ready = self.db.execute(sql, values).fetchone()[0]
        return {"status": "not_configured" if not config else "pending" if ready < total else "ready",
                "total": total, "ready": ready, "pending": total - ready}

    def check(self, root):
        root = Path(root).expanduser().resolve(); checked = now()
        try:
            if not root.is_dir(): raise IndexProblem("missing", "research run is unavailable")
            meta = metadata(root)
            if self._blocked(meta): return {"status": "excluded", "source_status": "excluded", "checked_at": checked}
            row = self._resolve(root, meta)
            snap = snapshot(root)
            record_edges(snap["records"])
            if row is None: status = "not_initialized" if self.missing else "new"
            else: status = "current" if row["fingerprint"] == snap["fingerprint"] else "stale"
            result = {"status": status, "source_status": "present", "checked_at": checked,
                      "run_key": row["run_key"] if row else None, "run_id": meta["run_id"] if meta else None,
                      "last_success": row["synced_at"] if row else None,
                      "unindexed_evidence": snap["unindexed_evidence"],
                      "semantic": self.semantic_status(row["run_key"]) if row else {"status": "not_configured", "pending": None}}
            if row:
                desired = self._desired_texts(row["run_key"], snap)
                old = {r[0] for r in self.db.execute("SELECT text_id FROM texts WHERE run_key=?", (row["run_key"],))}
                new = {r[0] for r in desired}
                result["text_changes"] = {"added": len(new-old), "removed": len(old-new), "unchanged": len(new & old)}
                result["research_phase"] = snap["config"].get("phase")
                result["review_validation"] = "not_performed; use research.py validate"
                result["unavailable_source_links"] = [r["id"] for r in snap["records"]["sources"] if r.get("local_path") and not Path(r["local_path"]).is_file()]
                if self.version >= 2:
                    state = self.db.execute("SELECT index_status,last_error,semantic_error FROM run_state WHERE run_key=?", (row["run_key"],)).fetchone()
                    result["last_attempt"] = dict(state) if state else None
            return result
        except (OSError, ValueError, sqlite3.Error, TypeError, KeyError) as exc:
            code = problem_code(exc)
            return {"status": code, "source_status": "missing" if code == "missing" else "unverified", "checked_at": checked, "error_code": code}

    def runs(self):
        return [{"run_key": r["run_key"], "root": r["root"], **self.check(r["root"])}
                for r in self.db.execute("SELECT run_key,root FROM runs ORDER BY root").fetchall()]

    def status(self, run_key=None):
        where, args = (" WHERE run_key=?", (run_key,)) if run_key else ("", ())
        counts = {table: self.db.execute(f"SELECT count(*) FROM {table}{where}", args).fetchone()[0]
                  for table in ("runs", "records", "record_edges", "observations", "documents", "texts", "citation_edges") if not run_key or table != "runs"}
        audit = self.db.execute("SELECT * FROM sync_audits" + where + " ORDER BY synced_at DESC LIMIT 1", args).fetchone()
        counts["latest_audit"] = dict(audit) if audit else None
        counts["semantic"] = self.semantic_status(run_key)
        counts["semantic_vectors"] = counts["semantic"]["ready"]
        counts["schema_version"] = self.version
        if self.version >= 2:
            counts["graph_coverage"] = [dict(r) for r in self.db.execute("SELECT * FROM graph_coverage" + where, args)]
        return counts

    def _state(self, key, run_id, status, error=None, semantic_error=None):
        self.db.execute("INSERT INTO run_state VALUES(?,?,?,?,?,?) ON CONFLICT(run_key) DO UPDATE SET run_id=COALESCE(excluded.run_id,run_state.run_id),checked_at=excluded.checked_at,index_status=excluded.index_status,last_error=excluded.last_error,semantic_error=excluded.semantic_error", (key, run_id, now(), status, error, semantic_error))

    def _attempt(self, key, reason, status, error=None):
        self.db.execute("INSERT INTO attempts(run_key,at,reason,status,error_code) VALUES(?,?,?,?,?)", (key, now(), reason, status, error))

    @staticmethod
    def _desired_texts(key, snap):
        result = []
        def add(kind, obj, locator, value):
            for ordinal, text in enumerate(chunks(value)):
                tid = "txt:" + sha("\0".join([key, kind, obj, locator, str(ordinal), sha(text)]))[:28]
                result.append((tid, key, kind, obj, locator, ordinal, text, sha(text)))
        add("query", "query.md", "document", snap["query"])
        add("report", "report.md", "document", snap["report"])
        for kind, rows in snap["records"].items():
            for row in rows: add("record:" + kind, row["id"], "record", text_of(row))
        for note in snap["evidence_texts"]:
            add("evidence", note["source_id"], note["path"], note["text"])
        for row in snap["documents"]:
            gid = "doc:" + sha(key + "\0" + row["id"])[:28]
            for page in row["pages"]: add("document", gid, page["locator"], page["text"])
        return result

    def _reconcile(self, table, keys, rows, run_key=None):
        """Compare complete row values; only write changed or removed rows."""
        cols = [r[1] for r in self.db.execute("PRAGMA table_info(" + table + ")")]
        indices = [cols.index(k) for k in keys]
        def key(row): return tuple(row[i] for i in indices)
        clause = " WHERE run_key=?" if run_key else ""
        old = {key(tuple(r)): tuple(r) for r in self.db.execute("SELECT * FROM " + table + clause, (run_key,) if run_key else ())}
        new = {key(tuple(r)): tuple(r) for r in rows}
        condition = " AND ".join(k + "=?" for k in keys)
        for k in old.keys() - new.keys(): self.db.execute("DELETE FROM " + table + " WHERE " + condition, k)
        for k, row in new.items():
            if old.get(k) != row:
                self.db.execute("INSERT OR REPLACE INTO " + table + " VALUES(" + ",".join("?" for _ in row) + ")", row)
        return {"added": len(new.keys()-old.keys()), "removed": len(old.keys()-new.keys()),
                "changed": sum(old[k] != new[k] for k in old.keys() & new.keys())}

    def _apply_texts(self, key, desired):
        old = {r["text_id"]: dict(r) for r in self.db.execute("SELECT * FROM texts WHERE run_key=?", (key,))}
        new = {r[0]: r for r in desired}
        cache = {}
        for row in self.db.execute("SELECT e.* FROM embeddings e JOIN texts t USING(text_id) WHERE t.run_key=?", (key,)):
            validate_blob(row)
            if row["chunk_version"] == CHUNK_VERSION:
                stored_windows(row, old[row["text_id"]]["text"])
            signature = (row["backend"], row["model"], row["revision"], row["chunk_version"])
            cache.setdefault(row["text_sha256"], {})[signature] = dict(row)
        reused = 0
        for tid in old.keys()-new.keys():
            self.db.execute("DELETE FROM embeddings WHERE text_id=?", (tid,))
            self.db.execute("DELETE FROM text_search WHERE text_id=?", (tid,))
            self.db.execute("DELETE FROM texts WHERE text_id=?", (tid,))
        for tid, row in new.items():
            if tid in old:
                if old[tid]["text_sha256"] != sha(old[tid]["text"]):
                    raise IndexProblem("integrity_error", "indexed source text changed")
                continue
            self.db.execute("INSERT INTO texts VALUES(?,?,?,?,?,?,?,?)", row)
            self.db.execute("INSERT INTO text_search VALUES(?,?,?,?,?,?)", (tid, key, row[2], row[3], row[4], row[6]))
            for vector in cache.get(row[7], {}).values():
                if vector["chunk_version"] != CHUNK_VERSION: continue
                self.db.execute("INSERT OR IGNORE INTO embeddings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (tid, vector["backend"], vector["model"], vector["revision"], vector["dimension"], vector["vector"], row[7], vector["vector_sha256"], CHUNK_VERSION, vector["window_manifest"], vector["window_tail"], vector["window_sha256"]))
                reused += 1
        return {"added": len(new.keys()-old.keys()), "removed": len(old.keys()-new.keys()),
                "unchanged": len(old.keys() & new.keys()), "relocated_vectors_reused": reused}

    def _rebuild_graph(self):
        raw = [(r["run_key"], r["candidate_id"], strict_json(r["payload"])) for r in self.db.execute("SELECT * FROM observations")]
        works, aliases, identities, edges, audits = project(raw)
        self._reconcile("works", ["work_key"], [(k, w["title"], w["doi"], canonical_json(w["metadata"]), w["external"]) for k, w in works.items()])
        self._reconcile("aliases", ["alias"], list(aliases.items()))
        self._reconcile("citation_edges", ["edge_id"], list(edges.values()))
        self._reconcile("graph_coverage", ["run_key"], [(k, a["expected"], a["indexed"], a["expected"]-a["indexed"], a["unresolved"], a["malformed"]) for k, a in audits.items()])
        for (key, cid), work in identities.items():
            self.db.execute("UPDATE observations SET work_key=? WHERE run_key=? AND candidate_id=? AND work_key IS NOT ?", (work, key, cid, work))
        for row in self.db.execute("SELECT * FROM documents").fetchall():
            cid = strict_json(row["metadata"]).get("candidate_id")
            work = identities.get((row["run_key"], cid))
            if row["work_key"] != work: self.db.execute("UPDATE documents SET work_key=? WHERE global_id=?", (work, row["global_id"]))

    def sync(self, root, reason="manual"):
        root = Path(root).expanduser().resolve()
        meta = ensure_metadata(root)
        self._resolve(root, meta)  # Reject ambiguous copies before any global mutation.
        if self._blocked(meta):
            self.forget(root, scope=meta["scope"] if meta["scope"] != "global" else "off")
            return {"status": "excluded"}
        snap = snapshot(root); specifications = record_edges(snap["records"])
        with self.transaction():
            old = self._resolve(root, meta)
            key = old["run_key"] if old else "run:" + meta["run_id"]
            self._state(key, meta["run_id"], "checking")
            if old and old["fingerprint"] == snap["fingerprint"]:
                # Raw sources were verified by snapshot, even on this fast path.
                self._state(key, meta["run_id"], "current")
                self._attempt(key, reason, "unchanged")
                result = {"run_key": key, "status": "unchanged", "text_changes": {"added": 0, "removed": 0}, **self.status(key)}
            else:
                self.db.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?)", (key, str(root), snap["config"]["query_sha256"], snap["fingerprint"], now()))
                rows = [(key, kind, row["id"], canonical_json(row)) for kind, records in snap["records"].items() for row in records]
                self._reconcile("records", ["run_key", "kind", "local_id"], rows, key)
                grouped = {}
                for *binding, evidence in specifications: grouped.setdefault(tuple(binding), []).append(evidence)
                self._reconcile("record_edges", ["run_key", "source_kind", "source_id", "target_kind", "target_id", "relation"],
                                [(key, *binding, canonical_json(evs)) for binding, evs in grouped.items()], key)
                prior = {r["candidate_id"]: r["work_key"] for r in self.db.execute("SELECT * FROM observations WHERE run_key=?", (key,))}
                observation_changes = self._reconcile("observations", ["run_key", "candidate_id"],
                    [(key, row["id"], prior.get(row["id"]), row["provider"], canonical_json(row)) for row in snap["candidates"]], key)
                docs = []
                for row in snap["documents"]:
                    gid = "doc:" + sha(key + "\0" + row["id"])[:28]
                    work = prior.get(strict_json(row["metadata"]).get("candidate_id"))
                    docs.append((gid, key, row["id"], work, row["title"], row["url"], row["sha256"], row["metadata"]))
                self._reconcile("documents", ["global_id"], docs, key)
                changes = self._apply_texts(key, self._desired_texts(key, snap))
                if any(observation_changes.values()) or not old or not self.db.execute("SELECT 1 FROM graph_coverage LIMIT 1").fetchone():
                    self._rebuild_graph()
                coverage = self.db.execute("SELECT * FROM graph_coverage WHERE run_key=?", (key,)).fetchone()
                expected, indexed, unresolved, malformed = (coverage["expected"], coverage["indexed"], coverage["unresolved"], coverage["malformed"]) if coverage else (0, 0, 0, 0)
                self.db.execute("INSERT INTO sync_audits VALUES(?,?,?,?,?,?,?,?)", (key, now(), len(specifications), len(grouped), expected, indexed, unresolved, malformed))
                self._state(key, meta["run_id"], "current")
                self._attempt(key, reason, "synced")
                result = {"run_key": key, "status": "synced", "text_changes": changes, **self.status(key)}
            again = snapshot(root)
            if again["fingerprint"] != snap["fingerprint"] or again["meta"] != snap["meta"]:
                raise IndexProblem("busy", "research inputs changed while indexing; retry after saving")
        return result

    def refresh(self, root, reason="manual", semantic="auto"):
        if semantic not in {"auto", "off", "required"}: raise ValueError("invalid semantic mode")
        try:
            result = self.sync(root, reason)
        except (OSError, ValueError, sqlite3.Error, TypeError, KeyError) as exc:
            code = problem_code(exc)
            row = self.db.execute("SELECT run_key FROM runs WHERE root=?", (str(Path(root).expanduser().resolve()),)).fetchone()
            if row:
                with self.transaction(): self._state(row[0], None, code, code); self._attempt(row[0], reason, code, code)
            else:
                try: meta = metadata(root)
                except (OSError, ValueError): meta = None
                if meta and not self._blocked(meta):
                    with self.transaction(): self._attempt("run:" + meta["run_id"], reason, code, code)
            return {"status": code, "error_code": code, "previous_generation_preserved": True}
        if result["status"] == "excluded": return result
        key = result["run_key"]; config = self._model()
        if semantic != "off" and config:
            try:
                result["embedding_build"] = self.build_embeddings(config["python"], config["model"], config["revision"], run_key=key)
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                code = problem_code(exc)
                with self.transaction(): self._state(key, None, "current", semantic_error=code); self._attempt(key, reason, "semantic_error", code)
                result["status"] = "partial"; result["semantic_error"] = code
        elif semantic == "required" and not config:
            result["status"] = "partial"; result["semantic_error"] = "not_configured"
        result["semantic"] = self.semantic_status(key)
        result["freshness"] = self.check(root)
        return result

    def forget(self, root, scope="off"):
        if scope not in {"local", "off"}: raise ValueError("forget scope must be local or off")
        root = Path(root).expanduser().resolve()
        meta = metadata(root) if root.is_dir() else None
        row = self._resolve(root, meta) if root.is_dir() else self.db.execute("SELECT * FROM runs WHERE root=?", (str(root),)).fetchone()
        if meta:
            write_metadata(root, {**meta, "scope": scope}, replace=True)
        with self.transaction():
            run_id = meta["run_id"] if meta else None
            if row:
                key = row["run_key"]
                state = self.db.execute("SELECT run_id FROM run_state WHERE run_key=?", (key,)).fetchone()
                run_id = run_id or (state[0] if state else None)
                tids = [r[0] for r in self.db.execute("SELECT text_id FROM texts WHERE run_key=?", (key,))]
                for tid in tids:
                    self.db.execute("DELETE FROM embeddings WHERE text_id=?", (tid,))
                    self.db.execute("DELETE FROM text_search WHERE text_id=?", (tid,))
                for table in ("texts", "records", "record_edges", "observations", "documents", "citation_edges", "sync_audits", "graph_coverage", "attempts", "run_state", "runs"):
                    self.db.execute("DELETE FROM " + table + " WHERE run_key=?", (key,))
                self._rebuild_graph()
                # FTS5 segment merges remove deleted text from its shadow storage.
                self.db.execute("INSERT INTO text_search(text_search) VALUES('optimize')")
            if run_id: self.db.execute("INSERT OR REPLACE INTO scope_blocks VALUES(?,?)", (run_id, scope))
        return {"status": "excluded", "scope": scope, "removed": bool(row), "source_policy_updated": bool(meta), "external_backups": "not_managed; apply the same retention decision to your backups"}

    def set_scope(self, root, scope):
        if scope not in {"global", "local", "off"}: raise ValueError("invalid scope")
        meta = ensure_metadata(root); self._resolve(root, meta)
        if scope != "global": return self.forget(root, scope)
        write_metadata(root, {**meta, "scope": scope}, replace=True)
        with self.transaction(): self.db.execute("DELETE FROM scope_blocks WHERE run_id=?", (meta["run_id"],))
        return self.refresh(root, "scope_change", "off")

    def relocate(self, old_root, new_root):
        old_root, new_root = Path(old_root).expanduser().resolve(), Path(new_root).expanduser().resolve()
        row = self.db.execute("SELECT * FROM runs WHERE root=?", (str(old_root),)).fetchone()
        if not row: raise IndexProblem("missing", "old research path is not registered")
        if old_root.exists(): raise IndexProblem("identity_conflict", "both paths exist; use fork for a copied run")
        state = self.db.execute("SELECT run_id FROM run_state WHERE run_key=?", (row["run_key"],)).fetchone()
        meta = metadata(new_root)
        if not meta or not state or not state[0] or meta["run_id"] != state[0]:
            raise IndexProblem("identity_conflict", "move requires the same registered run ID")
        if self._blocked(meta): raise IndexProblem("excluded", "excluded run cannot be relocated into global search")
        snap = snapshot(new_root); record_edges(snap["records"])
        if self.db.execute("SELECT 1 FROM runs WHERE root=?", (str(new_root),)).fetchone():
            raise IndexProblem("identity_conflict", "destination already registered")
        with self.transaction():
            self.db.execute("UPDATE runs SET root=? WHERE run_key=?", (str(new_root), row["run_key"]))
            self._attempt(row["run_key"], "relocate", "relocated")
        return self.refresh(new_root, "relocate", "off")

    def fork(self, root):
        root = Path(root).expanduser().resolve()
        if self.db.execute("SELECT 1 FROM runs WHERE root=?", (str(root),)).fetchone():
            raise IndexProblem("identity_conflict", "fork requires an unregistered copy")
        meta = ensure_metadata(root)
        new = write_metadata(root, {**meta, "run_id": str(uuid.uuid4())}, replace=True)
        return {"status": "forked", "run_id": new["run_id"], "scope": new["scope"]}

    def _eligible(self, run_key=None, allow_stale=False):
        rows = self.db.execute("SELECT run_key,root FROM runs" + (" WHERE run_key=?" if run_key else ""), (run_key,) if run_key else ()).fetchall()
        coverage, allowed = [], set()
        for row in rows:
            check = self.check(row["root"])
            item = {"run_key": row["run_key"], **check}
            item["run_key"] = row["run_key"]
            coverage.append(item)
            if check["status"] == "current" or (allow_stale and check["status"] not in {"excluded", "identity_conflict"}): allowed.add(row["run_key"])
        self.last_coverage = coverage
        return allowed

    def find(self, query, limit=20, run_key=None, allow_stale=False):
        if not 1 <= limit <= 1000: raise ValueError("limit must be 1..1000")
        terms = re.findall(r"\w+", query, flags=re.UNICODE)
        if not terms: raise ValueError("query needs words")
        allowed = self._eligible(run_key, allow_stale)
        if not allowed: return []
        match = " AND ".join('"' + x.replace('"', '""') + '"' for x in terms)
        sql = "SELECT text_id,run_key,kind,object_id,locator,snippet(text_search,5,'[',']','...',40) snippet,bm25(text_search) score FROM text_search WHERE text_search MATCH ? AND run_key IN (" + ",".join("?" for _ in allowed) + ") ORDER BY score LIMIT ?"
        return [dict(x) for x in self.db.execute(sql, [match, *sorted(allowed), limit])]

    def build_embeddings(self, python, model, revision, batch=32, run_key=None):
        if batch < 1: raise ValueError("batch must be positive")
        allowed = self._eligible(run_key)
        if not allowed:
            return {"built": 0, "total": 0, "dimension": None, "status": "no_current_runs", "worker_calls": 0}
        rows = self.db.execute("SELECT t.* FROM texts t LEFT JOIN embeddings e ON e.text_id=t.text_id AND e.backend='sentence-transformers' AND e.model=? AND e.revision=? AND e.chunk_version=? WHERE (e.text_id IS NULL OR e.text_sha256!=t.text_sha256 OR e.window_manifest IS NULL) AND t.run_key IN (" + ",".join("?" for _ in allowed) + ") ORDER BY t.text_id", [model, revision, CHUNK_VERSION, *sorted(allowed)]).fetchall()
        built = calls = 0
        for row in self.db.execute("SELECT e.*,t.text FROM embeddings e JOIN texts t USING(text_id) WHERE e.model=? AND e.revision=? AND t.run_key IN (" + ",".join("?" for _ in allowed) + ")", [model, revision, *sorted(allowed)]):
            validate_blob(row)
            if row["chunk_version"] == CHUNK_VERSION:
                stored_windows(row, row["text"])
        existing = self.db.execute("SELECT dimension FROM embeddings WHERE model=? AND revision=? LIMIT 1", (model, revision)).fetchone()
        dimension = existing[0] if existing else None
        config = {"python": str(python), "backend": "sentence-transformers", "model": model, "revision": revision, "dimension": dimension}
        # Configuration is a request to use a pinned local model, not proof it is loaded.
        with self.transaction(): self.db.execute("INSERT OR REPLACE INTO settings VALUES('semantic',?)", (canonical_json(config),))
        try:
            for start in range(0, len(rows), batch):
                selected = rows[start:start+batch]
                result = run_worker(str(python), model, revision, [r["text"] for r in selected], batch)
                groups, dimension = worker_windows(result, model, revision, [r["text"] for r in selected], dimension)
                calls += 1
                # There is no SQLite write transaction during model inference.
                current = self._eligible(run_key)
                if any(r["run_key"] not in current for r in selected):
                    raise IndexProblem("busy", "research changed during embedding; refresh before resuming")
                with self.transaction():
                    for row, windows in zip(selected, groups):
                        live = self.db.execute("SELECT text,text_sha256 FROM texts WHERE text_id=?", (row["text_id"],)).fetchone()
                        if not live or live[1] != row["text_sha256"] or sha(live[0]) != live[1]:
                            raise IndexProblem("busy", "embedding source changed before commit")
                        blob = struct.pack("<" + "f" * dimension, *windows[0][1])
                        manifest = canonical_json({"version": WINDOW_VERSION, "maximum": result["max_seq_length"],
                                                   "spans": [span for span, _ in windows]})
                        tail = pack_tail([vector for _, vector in windows], dimension)
                        self.db.execute("INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (row["text_id"], "sentence-transformers", model, revision, dimension, blob, row["text_sha256"], sha(blob), CHUNK_VERSION, manifest, tail, sha(manifest.encode() + b"\0" + tail)))
                        built += 1
                    config["dimension"] = dimension
                    self.db.execute("INSERT OR REPLACE INTO settings VALUES('semantic',?)", (canonical_json(config),))
                    for key in {r["run_key"] for r in selected}: self._state(key, None, "current")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            with self.transaction():
                for key in allowed:
                    if self.db.execute("SELECT 1 FROM runs WHERE run_key=?", (key,)).fetchone():
                        self._state(key, None, "current", semantic_error=problem_code(exc))
                        self._attempt(key, "embedding", "semantic_error", problem_code(exc))
            raise
        total = self.db.execute("SELECT count(*) FROM embeddings e JOIN texts t USING(text_id) WHERE e.model=? AND e.revision=? AND t.run_key IN (" + ",".join("?" for _ in allowed) + ")", [model, revision, *sorted(allowed)]).fetchone()[0]
        return {"built": built, "total": total, "dimension": dimension, "model": model, "revision": revision, "worker_calls": calls}

    def semantic(self, query, limit=20, run_key=None, allow_stale=False):
        if not query.strip(): raise ValueError("semantic query is empty")
        if not 1 <= limit <= 1000: raise ValueError("limit must be 1..1000")
        config = self._model()
        if not config: raise IndexProblem("not_configured", "semantic index not built")
        allowed = self._eligible(run_key, allow_stale)
        if not allowed: return {"query": query, "results": [], "coverage": self.last_coverage}
        result = run_worker(config["python"], config["model"], config["revision"], [query], 1)
        groups, dimension = worker_windows(result, config["model"], config["revision"], [query], config["dimension"])
        allowed = self._eligible(run_key, allow_stale)
        if not allowed: return {"query": query, "model": config["model"], "revision": config["revision"], "results": [], "coverage": self.last_coverage}
        queries, scores = [v for _, v in groups[0]], []
        sql = "SELECT e.*,t.run_key,t.kind,t.object_id,t.locator,t.text FROM embeddings e JOIN texts t USING(text_id) WHERE e.backend='sentence-transformers' AND e.model=? AND e.revision=? AND t.run_key IN (" + ",".join("?" for _ in allowed) + ")"
        for item in self.db.execute(sql, [config["model"], config["revision"], *sorted(allowed)]):
            if item["text_sha256"] != sha(item["text"]): raise IndexProblem("integrity_error", "embedding source text changed")
            if self.version < 3 or item["chunk_version"] != CHUNK_VERSION: continue
            windows = stored_windows(item, item["text"], dimension)
            score, best = max((max(sum(a*b for a,b in zip(q, vector)) for q in queries), i)
                              for i, (_, vector) in enumerate(windows))
            span = windows[best][0]
            scores.append({"text_id": item["text_id"], "run_key": item["run_key"], "kind": item["kind"], "object_id": item["object_id"], "locator": item["locator"], "score": max(-1., min(1., score)), "snippet": item["text"][span["start"]:span["end"]][:500],
                           "window_start": span["start"], "window_end": span["end"], "window_count": len(windows)})
        scores.sort(key=lambda x: (-x["score"], x["text_id"]))
        return {"query": query, "model": config["model"], "revision": config["revision"], "results": scores[:limit], "coverage": self.last_coverage}

    def graph(self, work, depth=1, direction="both", limit=200, allow_stale=False):
        if not 1 <= limit <= 1000: raise ValueError("limit must be 1..1000")
        if not 1 <= depth <= 5 or direction not in {"in", "out", "both"}: raise ValueError("invalid graph traversal")
        allowed = self._eligible(allow_stale=allow_stale)
        observations = [(r["run_key"], r["candidate_id"], strict_json(r["payload"])) for r in self.db.execute("SELECT * FROM observations") if r["run_key"] in allowed]
        works, aliases, _, graph_edges, _ = project(observations)
        doi = normalize_doi(work); alias = "doi:" + doi if doi else openalex_alias(work) or work
        start = aliases.get(alias, alias)
        if start not in works:
            return {"status": "not_found", "nodes": [], "edges": [], "coverage": self.last_coverage}
        queue, seen, edges, edge_ids, truncated = deque([(start, 0)]), {start}, [], set(), False
        while queue:
            node, level = queue.popleft()
            if level >= depth: continue
            for edge in graph_edges.values():
                if edge[0] in edge_ids: continue
                if not ((direction in {"out", "both"} and edge[2] == node) or (direction in {"in", "both"} and edge[3] == node)): continue
                if len(edges) == limit: truncated = True; continue
                edge_ids.add(edge[0])
                item = dict(zip(("edge_id", "run_key", "source_work", "target_work", "relation", "provider", "evidence", "resolution"), edge))
                item["evidence"] = strict_json(item["evidence"]); edges.append(item)
                other = edge[3] if edge[2] == node else edge[2]
                if other not in seen: seen.add(other); queue.append((other, level+1))
        return {"start": start, "depth": depth, "direction": direction, "nodes": [{"work_key": k, **works[k]} for k in sorted(seen)], "edges": edges, "truncated": truncated, "coverage": self.last_coverage}


def problem_code(exc):
    if isinstance(exc, IndexProblem): return exc.code
    if isinstance(exc, FileNotFoundError): return "missing"
    if isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc): return "busy"
    if isinstance(exc, subprocess.SubprocessError): return "semantic_error"
    return "invalid_input"


def validate_vectors(result, model, revision, count, dimension=None):
    if not isinstance(result, dict) or result.get("model") != model or result.get("revision") != revision:
        raise IndexProblem("semantic_error", "semantic worker model identity mismatch")
    size = result.get("dimension")
    if type(size) is not int or size < 1 or (dimension is not None and size != dimension):
        raise IndexProblem("semantic_error", "invalid embedding dimension")
    if model == MODEL and size != 384: raise IndexProblem("semantic_error", "pinned model dimension mismatch")
    vectors = result.get("vectors")
    if not isinstance(vectors, list) or len(vectors) != count: raise IndexProblem("semantic_error", "semantic result count mismatch")
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != size or any(type(x) not in {int, float} or not math.isfinite(x) for x in vector):
            raise IndexProblem("semantic_error", "invalid embedding vector")
        if not math.isclose(math.sqrt(sum(x*x for x in vector)), 1., abs_tol=1e-4):
            raise IndexProblem("semantic_error", "embedding vector is not normalized")
    return vectors, size


def validate_blob(row, dimension=None):
    size, blob = row["dimension"], row["vector"]
    if type(size) is not int or size < 1 or len(blob) != 4*size or (dimension is not None and size != dimension):
        raise IndexProblem("integrity_error", "stored embedding dimension is invalid")
    if "vector_sha256" in row.keys() and sha(blob) != row["vector_sha256"]:
        raise IndexProblem("integrity_error", "stored embedding bytes changed")
    vector = struct.unpack("<" + "f" * size, blob)
    if not all(math.isfinite(x) for x in vector) or not math.isclose(math.sqrt(sum(x*x for x in vector)), 1., abs_tol=1e-4):
        raise IndexProblem("integrity_error", "stored embedding vector is invalid")
    return vector


def worker_windows(result, model, revision, texts, dimension=None):
    if not isinstance(result, dict) or result.get("window_version") != WINDOW_VERSION:
        raise IndexProblem("semantic_error", "semantic worker window protocol mismatch; rebuild with the current worker")
    try:
        spans = result.get("spans")
        groups = validate_spans(spans, texts, result.get("max_seq_length"))
        vectors, dimension = validate_vectors(result, model, revision, len(spans), dimension)
        output, offset = [], 0
        for rows in groups:
            output.append([({**span, "input": 0}, vector) for span, vector in zip(rows, vectors[offset:offset+len(rows)])])
            offset += len(rows)
        return output, dimension
    except ValueError as exc:
        raise IndexProblem("semantic_error", str(exc)) from exc


def stored_windows(row, text, dimension=None):
    first = validate_blob(row, dimension)
    try:
        manifest, tail = row["window_manifest"], row["window_tail"]
        if not isinstance(manifest, str) or not isinstance(tail, bytes):
            raise ValueError("semantic window data missing; rebuild required")
        if sha(manifest.encode() + b"\0" + tail) != row["window_sha256"]:
            raise ValueError("stored semantic window bytes changed")
        meta = strict_json(manifest)
        if not isinstance(meta, dict) or meta.get("version") != WINDOW_VERSION:
            raise ValueError("semantic window version mismatch")
        spans = validate_spans(meta.get("spans"), [text], meta.get("maximum"))[0]
        vectors = [first] + unpack_tail(tail, len(spans)-1, row["dimension"])
        return list(zip(spans, vectors))
    except (ValueError, TypeError, KeyError) as exc:
        raise IndexProblem("integrity_error", str(exc)) from exc


def run_worker(python, model, revision, texts, batch=32):
    worker = Path(__file__).with_name("semantic_worker.py")
    proc = subprocess.run([python, "-B", str(worker), "--model", model, "--revision", revision, "--offline"], input=canonical_json({"texts": texts, "batch_size": batch}), capture_output=True, text=True, timeout=600)
    if proc.returncode: raise IndexProblem("semantic_error", "local semantic worker failed; inspect the configured environment")
    return strict_json(proc.stdout)


@contextmanager
def opened(path, readonly=False):
    instance = GlobalIndex(path, readonly)
    try: yield instance
    finally: instance.close()


def setup_semantic(env, model, revision, allow_download):
    if not allow_download: raise ValueError("semantic setup installs packages and a model; pass --allow-download explicitly")
    env = Path(env).expanduser().resolve(); python = env / "bin/python"
    uv = shutil.which("uv")
    if not uv: raise ValueError("uv is required to manage the isolated semantic environment")
    if not python.exists(): subprocess.run([uv, "venv", str(env), "--python", "3.12"], check=True, timeout=300)
    subprocess.run([uv, "pip", "install", "--python", str(python), ST_REQUIREMENT], check=True, timeout=1200)
    worker = Path(__file__).with_name("semantic_worker.py")
    proc = subprocess.run([str(python), "-B", str(worker), "--model", model, "--revision", revision], input=canonical_json({"texts": ["연구 색인 준비"]}), capture_output=True, text=True, timeout=1200)
    if proc.returncode: raise IndexProblem("semantic_error", "local model setup failed")
    _, dimension = worker_windows(strict_json(proc.stdout), model, revision, ["연구 색인 준비"])
    return {"python": str(python), "model": model, "revision": revision, "dimension": dimension, "local_inference": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default=str(DEFAULT_INDEX)); sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync"); s.add_argument("run")
    s = sub.add_parser("refresh"); s.add_argument("--run", required=True); s.add_argument("--reason", default="manual"); s.add_argument("--semantic", choices=["auto", "off", "required"], default="auto")
    s = sub.add_parser("check"); s.add_argument("--run", required=True)
    sub.add_parser("runs"); sub.add_parser("status")
    for command in ("find", "semantic-search"):
        s = sub.add_parser(command); s.add_argument("query"); s.add_argument("--limit", type=int, default=20); s.add_argument("--run-key"); s.add_argument("--allow-stale", action="store_true")
    s = sub.add_parser("semantic-setup"); s.add_argument("--env", default=str(SEMANTIC_ENV)); s.add_argument("--model", default=MODEL); s.add_argument("--revision", default=MODEL_REVISION); s.add_argument("--allow-download", action="store_true")
    s = sub.add_parser("semantic-build"); s.add_argument("--python", default=str(SEMANTIC_ENV/'bin/python')); s.add_argument("--model", default=MODEL); s.add_argument("--revision", default=MODEL_REVISION); s.add_argument("--batch", type=int, default=32); s.add_argument("--run-key")
    s = sub.add_parser("graph"); s.add_argument("work"); s.add_argument("--depth", type=int, default=1); s.add_argument("--direction", choices=["in", "out", "both"], default="both"); s.add_argument("--limit", type=int, default=200); s.add_argument("--allow-stale", action="store_true")
    s = sub.add_parser("relocate"); s.add_argument("--from", dest="old", required=True); s.add_argument("--to", dest="new", required=True)
    s = sub.add_parser("fork"); s.add_argument("--run", required=True)
    s = sub.add_parser("scope"); s.add_argument("--run", required=True); s.add_argument("--set", dest="scope", choices=["global", "local", "off"], required=True)
    s = sub.add_parser("forget"); s.add_argument("--run", required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "semantic-setup": result = setup_semantic(args.env, args.model, args.revision, args.allow_download)
        else:
            readonly = args.cmd in {"check", "runs", "status", "find", "semantic-search", "graph"}
            with opened(args.index, readonly) as index:
                if args.cmd == "sync": result = index.sync(args.run)
                elif args.cmd == "refresh": result = index.refresh(args.run, args.reason, args.semantic)
                elif args.cmd == "check": result = index.check(args.run)
                elif args.cmd == "runs": result = {"runs": index.runs()}
                elif args.cmd == "status": result = {"status": "not_initialized" if index.missing else "ok", **index.status(), "run_states": index.runs()}
                elif args.cmd == "find": result = {"results": index.find(args.query, args.limit, args.run_key, args.allow_stale), "coverage": index.last_coverage}
                elif args.cmd == "semantic-search": result = index.semantic(args.query, args.limit, args.run_key, args.allow_stale)
                elif args.cmd == "semantic-build": result = index.build_embeddings(args.python, args.model, args.revision, args.batch, args.run_key)
                elif args.cmd == "graph": result = index.graph(args.work, args.depth, args.direction, args.limit, args.allow_stale)
                elif args.cmd == "relocate": result = index.relocate(args.old, args.new)
                elif args.cmd == "fork": result = index.fork(args.run)
                elif args.cmd == "scope": result = index.set_scope(args.run, args.scope)
                else: result = index.forget(args.run)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2 if result.get("status") in {"busy", "partial", "identity_conflict", "invalid_input", "integrity_error", "missing", "semantic_error"} else 0
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "error", "error_code": problem_code(exc), "detail": str(exc) if isinstance(exc, IndexProblem) else "request failed; inspect inputs or local environment"}, ensure_ascii=False)); return 2


if __name__ == "__main__": raise SystemExit(main())
