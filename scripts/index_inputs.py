"""Stable research identities and verified, read-only input snapshots."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid

TABLES = ("questions", "searches", "sources", "claims", "leads", "trace", "reviews", "report-map")
META = ".research-index.json"
INDEX_VERSION = 3
CHUNK_VERSION = 2


class IndexProblem(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(detail)


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def strict_json(value):
    def pairs(items):
        result = {}
        for key, val in items:
            if key in result: raise IndexProblem("invalid_input", "duplicate JSON key")
            result[key] = val
        return result
    def constant(_): raise IndexProblem("invalid_input", "nonfinite JSON value")
    try: return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise IndexProblem("invalid_input", "invalid JSON input") from exc


def metadata(root):
    path = Path(root) / META
    if path.is_symlink(): raise IndexProblem("identity_conflict", "index metadata must not be a symlink")
    if not path.exists(): return None
    value = strict_json(path.read_bytes())
    try:
        valid = isinstance(value, dict) and value.get("schema_version") == 1
        valid = valid and str(uuid.UUID(value["run_id"])) == value["run_id"]
        valid = valid and value.get("scope") in {"global", "local", "off"}
    except (KeyError, ValueError, TypeError, AttributeError): valid = False
    if not valid: raise IndexProblem("identity_conflict", "invalid index metadata")
    return value


def write_metadata(root, value, *, replace=False):
    root = Path(root).resolve()
    if not (root / "run.json").is_file(): raise IndexProblem("missing", "research run is unavailable")
    if (root / META).is_symlink(): raise IndexProblem("identity_conflict", "index metadata must not be a symlink")
    fd, temporary = tempfile.mkstemp(prefix=".research-index-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(canonical_json(value) + "\n"); out.flush(); os.fsync(out.fileno())
        if replace: os.replace(temporary, root / META)
        else:
            try: os.link(temporary, root / META)
            except FileExistsError: pass
        return metadata(root)
    finally: Path(temporary).unlink(missing_ok=True)


def ensure_metadata(root, scope="global"):
    old = metadata(root)
    if old: return old
    return write_metadata(root, {"schema_version": 1, "run_id": str(uuid.uuid4()), "scope": scope})


def contained(root, relative):
    if not isinstance(relative, str) or not relative:
        raise IndexProblem("invalid_input", "invalid document body path")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise IndexProblem("invalid_input", "document body path escapes research run")
    return path


def snapshot(root):
    """Read every indexed input and hash raw evidence before declaring it current.

    Collection queries use one SQLite read transaction. Call again before commit
    to reject an input generation that changed while preparing derived rows.
    """
    root = Path(root).expanduser().resolve()
    if not root.is_dir(): raise IndexProblem("missing", "research run is unavailable")
    if (root / ".collection.lock").exists():
        raise IndexProblem("busy", "research collection is active or has a stale lock")
    meta = metadata(root)
    if meta and meta["scope"] != "global":
        raise IndexProblem("excluded", "research is excluded from the global index")
    files = {}
    for name in ("run.json", "query.md", "report.md") + tuple(n + ".jsonl" for n in TABLES):
        path = contained(root, name)
        try: files[name] = path.read_bytes()
        except FileNotFoundError as exc: raise IndexProblem("missing", "required research file is unavailable") from exc
    config = strict_json(files["run.json"])
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise IndexProblem("invalid_input", "unsupported research schema")
    if sha(files["query.md"]) != config.get("query_sha256"):
        raise IndexProblem("invalid_input", "query.md hash does not match run.json")
    records, ids = {}, set()
    for kind in TABLES:
        rows = []
        for line in files[kind + ".jsonl"].decode("utf-8").splitlines():
            if not line.strip(): raise IndexProblem("invalid_input", "blank JSONL line")
            row = strict_json(line)
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
                raise IndexProblem("invalid_input", "record needs a nonempty id")
            if row["id"] in ids: raise IndexProblem("invalid_input", "duplicate record id")
            ids.add(row["id"]); rows.append(row)
        records[kind] = rows
    evidence, evidence_texts, unindexed_evidence = {}, [], []
    for row in records["sources"]:
        if row.get("evidence_file"):
            path = contained(root, row["evidence_file"])
            blob = path.read_bytes()
            digest = sha(blob)
            if digest != row.get("evidence_sha256"):
                raise IndexProblem("integrity_error", "source evidence bytes changed; review required")
            evidence[row["evidence_file"]] = digest
            note = {"source_id": row["id"], "path": row["evidence_file"], "sha256": digest}
            suffix = path.suffix.lower()
            text_types = {".md", ".txt", ".json", ".jsonl", ".csv", ".tsv", ".log", ".rst",
                          ".yaml", ".yml", ".xml", ".html", ".htm", ".py", ".sql", ".sh", ".out"}
            try:
                if suffix not in text_types:
                    raise ValueError("unsupported_format; ingest with collect.py or attach a UTF-8 evidence note")
                text = blob.decode("utf-8-sig")
                if any(ord(c) < 32 and c not in "\n\r\t\f" for c in text):
                    raise ValueError("binary_content; use the collection extractor")
                evidence_texts.append({**note, "text": text})
            except (UnicodeError, ValueError) as exc:
                reason = "non_utf8; convert explicitly without replacing undecodable bytes" if isinstance(exc, UnicodeError) else str(exc)
                unindexed_evidence.append({**note, "reason": reason})
    candidates, documents = [], []
    collection = contained(root, "collection/corpus.sqlite3")
    if collection.exists():
        src = sqlite3.connect(collection.as_uri() + "?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        try:
            src.execute("BEGIN")
            if src.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise IndexProblem("invalid_input", "unsupported collection database schema")
            if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise IndexProblem("integrity_error", "collection database integrity check failed")
            for row in src.execute("SELECT id,payload FROM candidates ORDER BY id"):
                item = strict_json(row["payload"])
                if not isinstance(item, dict) or item.get("id") != row["id"] or not item.get("provider_id"):
                    raise IndexProblem("invalid_input", "invalid candidate identity")
                candidates.append(item)
            candidate_ids = {r["id"] for r in candidates}
            for raw in src.execute("SELECT * FROM documents ORDER BY id"):
                row = dict(raw); info = strict_json(row["metadata"])
                body = contained(root, row["body_path"])
                if not body.is_file() or sha(body.read_bytes()) != row["sha256"]:
                    raise IndexProblem("integrity_error", "collection source bytes changed; reacquire and review")
                pages = []
                for page in src.execute("SELECT * FROM pages WHERE document_id=? ORDER BY rowid", (row["id"],)):
                    page_info = strict_json(page["metadata"])
                    if not isinstance(page_info, dict) or page_info.get("locator") != page["locator"]:
                        raise IndexProblem("invalid_input", "invalid page locator")
                    pages.append({**page_info, "text": page["text"]})
                digest = sha(json.dumps(pages, ensure_ascii=False, sort_keys=True))
                if not isinstance(info, dict) or digest != info.get("page_digest"):
                    raise IndexProblem("integrity_error", "collection extracted pages changed; re-extract and review")
                if info.get("candidate_id") and info["candidate_id"] not in candidate_ids:
                    raise IndexProblem("invalid_input", "document references an unknown candidate")
                row["pages"] = pages
                documents.append(row)
        finally: src.close()
    if (root / ".collection.lock").exists():
        raise IndexProblem("busy", "research collection changed during snapshot")
    # Hash actual logical data, excluding request cache events and physical DB layout.
    logical = {"version": INDEX_VERSION, "chunk_version": CHUNK_VERSION, "config": config,
               "query": files["query.md"].decode("utf-8"), "report": files["report.md"].decode("utf-8"),
               "records": records, "evidence": evidence, "evidence_texts": evidence_texts,
               "unindexed_evidence": unindexed_evidence, "candidates": candidates, "documents": documents}
    return {**logical, "fingerprint": sha(canonical_json(logical)), "meta": meta,
            "root": root, "graph_fingerprint": sha(canonical_json(candidates))}
