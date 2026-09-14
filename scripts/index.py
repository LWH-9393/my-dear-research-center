#!/usr/bin/env python3
"""Cross-project research index, local semantic search and citation graph."""
from __future__ import annotations

import argparse
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile

VERSION = "1.3.0"
DATA = Path.home() / ".local/share/my-dear-research-center"
DEFAULT_INDEX = DATA / "research-index.sqlite3"
SEMANTIC_ENV = DATA / "semantic-env"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
ST_REQUIREMENT = "sentence-transformers==5.7.0"
TABLES = ("questions", "searches", "sources", "claims", "leads", "trace", "reviews", "report-map")


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    if isinstance(value, str): value = value.encode()
    return hashlib.sha256(value).hexdigest()


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def collection_json(value):
    """Match collect.py's persisted digest representation exactly."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def read_json(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ValueError(f"expected JSON object: {path}")
    return value


def read_jsonl(path):
    rows = []
    if not path.exists(): return rows
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip(): raise ValueError(f"blank JSONL line: {path}:{n}")
        value = json.loads(line)
        if not isinstance(value, dict): raise ValueError(f"expected JSON object: {path}:{n}")
        rows.append(value)
    return rows


def normalize_doi(value):
    if not isinstance(value, str): return None
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", value.strip(), flags=re.I)
    return value.lower() if re.fullmatch(r"10\.\d{4,9}/\S+", value) else None


def openalex_alias(value):
    if not isinstance(value, str): return None
    tail = value.rstrip("/").rsplit("/", 1)[-1]
    return "openalex:" + tail.upper() if re.fullmatch(r"W\d+", tail, re.I) else None


def stable_run_key(root, query_hash):
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
    if not text: return []
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


class GlobalIndex:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        self.db = sqlite3.connect(self.path)
        os.chmod(self.path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, 1}:
            self.db.close(); raise ValueError("unsupported global index schema")
        self.db.executescript("""
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
        PRAGMA user_version=1;
        """)

    def close(self): self.db.close()

    def _text(self, run_key, kind, object_id, locator, text):
        for ordinal, value in enumerate(chunks(text)):
            tid = "txt:" + sha("\0".join([run_key, kind, object_id, locator, str(ordinal), sha(value)]))[:28]
            self.db.execute("INSERT INTO texts VALUES(?,?,?,?,?,?,?,?)", (tid, run_key, kind, object_id, locator, ordinal, value, sha(value)))
            self.db.execute("INSERT INTO text_search VALUES(?,?,?,?,?,?)", (tid, run_key, kind, object_id, locator, value))

    def _work(self, key, title=None, doi=None, metadata=None, external=False):
        old = self.db.execute("SELECT * FROM works WHERE work_key=?", (key,)).fetchone()
        if old:
            title = title or old["title"]; doi = doi or old["doi"]
            merged = json.loads(old["metadata"] or "{}")
            if metadata: merged.update(metadata)
            external = bool(old["external"] and external)
        else: merged = metadata or {}
        self.db.execute("INSERT OR REPLACE INTO works VALUES(?,?,?,?,?)", (key, title, doi, canonical_json(merged), int(external)))
        if doi: self.db.execute("INSERT OR REPLACE INTO aliases VALUES(?,?)", ("doi:" + doi, key))
        return key

    def _target(self, raw, evidence):
        doi = normalize_doi(raw)
        alias = "doi:" + doi if doi else openalex_alias(raw)
        if alias:
            row = self.db.execute("SELECT work_key FROM aliases WHERE alias=?", (alias,)).fetchone()
            key = row[0] if row else alias
            known = self.db.execute("SELECT external FROM works WHERE work_key=?", (key,)).fetchone()
            locally_observed = bool(known and not known[0])
            self._work(key, doi=doi, metadata={"first_seen_as": raw}, external=True)
            self.db.execute("INSERT OR IGNORE INTO aliases VALUES(?,?)", (alias, key))
            return key, "resolved_local" if locally_observed else "external_identifier"
        key = "unresolved:" + sha(canonical_json(evidence))[:24]
        self._work(key, metadata={"unresolved_reference": evidence}, external=True)
        return key, "unresolved_metadata"

    def _citation(self, run_key, source, target, relation, provider, evidence, resolution):
        eid = "cite:" + sha(canonical_json([run_key, source, target, relation, provider, evidence]))[:28]
        self.db.execute("INSERT OR REPLACE INTO citation_edges VALUES(?,?,?,?,?,?,?,?)", (eid, run_key, source, target, relation, provider, canonical_json(evidence), resolution))

    @staticmethod
    def _observation_aliases(item):
        provider = str(item.get("provider") or "unknown")
        pid = str(item.get("provider_id"))
        aliases = {provider + ":" + pid, pid}
        oa = openalex_alias(pid)
        doi = normalize_doi(item.get("doi"))
        if oa: aliases.add(oa)
        if doi: aliases.add("doi:" + doi)
        return aliases

    @staticmethod
    def _canonical_alias(aliases):
        def rank(alias):
            if alias.startswith("doi:"): return (0, alias)
            if alias.startswith("openalex:"): return (1, alias)
            return (2, alias)
        return min(aliases, key=rank)

    def _rebuild_identities(self):
        """Rebuild work identity from every live observation, independent of sync order."""
        observations = self.db.execute("SELECT run_key,candidate_id,work_key,payload FROM observations").fetchall()
        parent = {}
        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]; x = parent[x]
            return x
        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb: parent[max(ra, rb)] = min(ra, rb)
        parsed = []
        for row in observations:
            item = json.loads(row["payload"]); aliases = self._observation_aliases(item)
            first = min(aliases)
            for alias in aliases: union(first, alias)
            parsed.append((row, item, aliases))
        groups = {}
        for alias in parent: groups.setdefault(find(alias), set()).add(alias)
        mapping = {}
        for aliases in groups.values():
            canonical = self._canonical_alias(aliases)
            mapping.update({alias: canonical for alias in aliases})
        remap = dict(mapping)

        old_works = {row["work_key"]: dict(row) for row in self.db.execute("SELECT * FROM works")}
        for row, item, aliases in parsed:
            canonical = mapping[next(iter(aliases))]
            if row["work_key"] not in mapping:
                current = remap.get(row["work_key"])
                remap[row["work_key"]] = self._canonical_alias({current, canonical} - {None})
            self.db.execute("UPDATE observations SET work_key=? WHERE run_key=? AND candidate_id=?",
                            (canonical, row["run_key"], row["candidate_id"]))
            doi = normalize_doi(item.get("doi"))
            provider = str(item.get("provider") or "unknown")
            self._work(canonical, item.get("title"), doi,
                       {provider: {"provider_id": str(item.get("provider_id")), "observed_at": item.get("observed_at")}})
        for old, canonical in remap.items():
            if old == canonical: continue
            meta = old_works.get(old)
            if meta:
                self._work(canonical, meta["title"], meta["doi"], json.loads(meta["metadata"] or "{}"), bool(meta["external"]))
            self.db.execute("UPDATE documents SET work_key=? WHERE work_key=?", (canonical, old))
            self.db.execute("UPDATE citation_edges SET source_work=? WHERE source_work=?", (canonical, old))
            self.db.execute("UPDATE citation_edges SET target_work=? WHERE target_work=?", (canonical, old))

        self.db.execute("DELETE FROM aliases")
        for alias, canonical in sorted(mapping.items()):
            self.db.execute("INSERT INTO aliases VALUES(?,?)", (alias, canonical))
        # Preserve self aliases for citation-only identifiers.
        endpoints = self.db.execute("SELECT source_work FROM citation_edges UNION SELECT target_work FROM citation_edges").fetchall()
        for (key,) in endpoints:
            if key.startswith(("doi:", "openalex:")):
                self.db.execute("INSERT OR IGNORE INTO aliases VALUES(?,?)", (key, mapping.get(key, key)))

        self.db.execute("UPDATE works SET external=1")
        self.db.execute("UPDATE works SET external=0 WHERE work_key IN (SELECT DISTINCT work_key FROM observations)")
        # Re-key after endpoint normalization and collapse duplicates deterministically.
        edges = [dict(x) for x in self.db.execute("SELECT * FROM citation_edges")]
        self.db.execute("DELETE FROM citation_edges")
        for edge in edges:
            source = remap.get(edge["source_work"], edge["source_work"])
            target = remap.get(edge["target_work"], edge["target_work"])
            local = self.db.execute("SELECT 1 FROM observations WHERE work_key=? LIMIT 1", (target,)).fetchone()
            resolution = "resolved_local" if local else edge["resolution"]
            self._citation(edge["run_key"], source, target, edge["relation"], edge["provider"],
                           json.loads(edge["evidence"]), resolution)
        used = {x[0] for x in self.db.execute("SELECT work_key FROM observations UNION SELECT work_key FROM documents UNION SELECT source_work FROM citation_edges UNION SELECT target_work FROM citation_edges")}
        for (key,) in self.db.execute("SELECT work_key FROM works").fetchall():
            if key not in used: self.db.execute("DELETE FROM works WHERE work_key=?", (key,))

    @staticmethod
    def _validate_collection(root, collection, src):
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("collection database integrity check failed")
        if src.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("unsupported collection database schema")
        root = root.resolve()
        for row in src.execute("SELECT * FROM documents"):
            body = (root / row["body_path"]).resolve()
            try: body.relative_to(root)
            except ValueError: raise ValueError("document body path escapes research run") from None
            if not body.is_file() or sha(body.read_bytes()) != row["sha256"]:
                raise ValueError("collection source bytes changed; reacquire and review")
            pages = []
            for page in src.execute("SELECT text,metadata FROM pages WHERE document_id=? ORDER BY rowid", (row["id"],)):
                pages.append({**json.loads(page["metadata"]), "text": page["text"]})
            metadata = json.loads(row["metadata"])
            if sha(collection_json(pages)) != metadata.get("page_digest"):
                raise ValueError("collection extracted pages changed; re-extract and review")

    def sync(self, root):
        root = Path(root).expanduser().resolve()
        config = read_json(root / "run.json")
        query = (root / "query.md").read_bytes()
        if sha(query) != config.get("query_sha256"): raise ValueError("query.md hash does not match run.json")
        if (root / ".collection.lock").exists(): raise ValueError("research collection is active or has a stale lock")
        records = {name: read_jsonl(root / (name + ".jsonl")) for name in TABLES}
        collection = root / "collection/corpus.sqlite3"
        inputs = [Path(__file__).read_bytes(), query, (root / "run.json").read_bytes(), (root / "report.md").read_bytes()]
        inputs += [(root / (name + ".jsonl")).read_bytes() for name in TABLES if (root / (name + ".jsonl")).exists()]
        if collection.exists(): inputs.append(collection.read_bytes())
        fingerprint = sha(b"\0".join(inputs))
        run_key = stable_run_key(root, config["query_sha256"])
        old = self.db.execute("SELECT fingerprint FROM runs WHERE run_key=?", (run_key,)).fetchone()
        if old and old[0] == fingerprint:
            return {"run_key": run_key, "status": "unchanged", **self.status(run_key)}
        expected_records = expected_record_edges = expected_citations = malformed = 0
        with self.db:
            text_ids = [r[0] for r in self.db.execute("SELECT text_id FROM texts WHERE run_key=?", (run_key,))]
            for table in ("records", "record_edges", "observations", "documents", "texts", "citation_edges", "sync_audits"):
                self.db.execute(f"DELETE FROM {table} WHERE run_key=?", (run_key,))
            for tid in text_ids:
                self.db.execute("DELETE FROM text_search WHERE text_id=?", (tid,))
                self.db.execute("DELETE FROM embeddings WHERE text_id=?", (tid,))
            self.db.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?)", (run_key, str(root), config["query_sha256"], fingerprint, now()))
            self._text(run_key, "query", "query.md", "document", query.decode("utf-8"))
            self._text(run_key, "report", "report.md", "document", (root / "report.md").read_text(encoding="utf-8"))
            known = {name: {str(x.get("id")): x for x in rows if x.get("id") is not None} for name, rows in records.items()}
            for kind, rows in records.items():
                for row in rows:
                    lid = str(row.get("id")); expected_records += 1
                    self.db.execute("INSERT INTO records VALUES(?,?,?,?)", (run_key, kind, lid, canonical_json(row)))
                    self._text(run_key, "record:" + kind, lid, "record", text_of(row))
            edge_specs = []
            for row in records["sources"]:
                edge_specs += [("sources", row["id"], "sources", x, "derived_from", {}) for x in row.get("derived_from", [])]
            for row in records["searches"]:
                edge_specs += [("searches", row["id"], "questions", x, "investigates", {}) for x in row.get("question_ids", [])]
                edge_specs += [("searches", row["id"], "sources", x, "found_source", {}) for x in row.get("source_ids", [])]
            for row in records["claims"]:
                edge_specs += [("claims", row["id"], "questions", x, "addresses", {}) for x in row.get("question_ids", [])]
                edge_specs += [("claims", row["id"], "sources", x.get("source_id"), x.get("relation", "evidence"), x) for x in row.get("evidence", [])]
            for row in records["questions"]:
                edge_specs += [("questions", row["id"], "claims", x, "answered_by", {}) for x in row.get("claim_ids", [])]
                for lens, cell in (row.get("coverage") or {}).items():
                    edge_specs += [("questions", row["id"], "searches", x, "covered_by:" + lens, {}) for x in cell.get("search_ids", [])]
                    edge_specs += [("questions", row["id"], "sources", x, "coverage_source:" + lens, {}) for x in cell.get("source_ids", [])]
            for row in records["leads"]:
                edge_specs += [("leads", row["id"], "questions", x, "concerns", {}) for x in row.get("question_ids", [])]
                edge_specs += [("leads", row["id"], "searches", x, "investigated_by", {}) for x in row.get("search_ids", [])]
                edge_specs += [("leads", row["id"], "sources", x, "resolved_with", {}) for x in row.get("source_ids", [])]
            for row in records["trace"]:
                for x in row.get("parent_ids", []):
                    target = next((k for k in ("questions", "claims", "trace") if x in known[k]), "unknown")
                    edge_specs.append(("trace", row["id"], target, x, "parent", {}))
            for row in records["report-map"]:
                edge_specs += [("report-map", row["id"], "claims", x, "maps_claim", {}) for x in row.get("claim_ids", [])]
            for row in records["reviews"]:
                edge_specs += [("reviews", row["id"], "claims", x, "reviews_claim", {}) for x in row.get("claim_ids", [])]
            expected_record_edges = len(edge_specs)
            for sk, sid, tk, tid, rel, evidence in edge_specs:
                if tk == "unknown" or tid not in known.get(tk, {}): raise ValueError(f"unresolved record edge {sk}:{sid} -> {tk}:{tid}")
                self.db.execute("INSERT INTO record_edges VALUES(?,?,?,?,?,?,?)", (run_key, sk, sid, tk, tid, rel, canonical_json(evidence)))
            if collection.exists():
                src = sqlite3.connect("file:" + str(collection) + "?mode=ro", uri=True); src.row_factory = sqlite3.Row
                try:
                    self._validate_collection(root, collection, src)
                    candidates = [json.loads(x["payload"]) for x in src.execute("SELECT payload FROM candidates")]
                    for item in candidates:
                        provider = item.get("provider", "unknown"); pid = str(item.get("provider_id")); doi = normalize_doi(item.get("doi")); key = "doi:" + doi if doi else (openalex_alias(pid) or provider + ":" + pid)
                        self._work(key, item.get("title"), doi, {provider: {"provider_id": pid, "observed_at": item.get("observed_at")}})
                        self.db.execute("INSERT INTO observations VALUES(?,?,?,?,?)", (run_key, item["id"], key, provider, canonical_json(item)))
                    self._rebuild_identities()
                    for item in candidates:
                        provider = item.get("provider", "unknown"); pid = str(item.get("provider_id")); doi = normalize_doi(item.get("doi")); source = "doi:" + doi if doi else (openalex_alias(pid) or provider + ":" + pid)
                        source = (self.db.execute("SELECT work_key FROM aliases WHERE alias=?", (source,)).fetchone() or [source])[0]
                        refs = item.get("references") or []
                        for ref in refs:
                            expected_citations += 1
                            raw = ref if isinstance(ref, str) else (ref.get("DOI") or ref.get("doi") or ref.get("id") if isinstance(ref, dict) else None)
                            if not isinstance(ref, (str, dict)): malformed += 1
                            target, resolution = self._target(raw, ref)
                            self._citation(run_key, source, target, "references", provider, ref, resolution)
                        for ref in item.get("updates") or []:
                            expected_citations += 1
                            raw = ref.get("DOI") or ref.get("doi") or ref.get("id") if isinstance(ref, dict) else ref
                            if not isinstance(ref, (str, dict)): malformed += 1
                            target, resolution = self._target(raw, ref)
                            self._citation(run_key, source, target, "updates", provider, ref, resolution)
                        relations = item.get("relations") or {}
                        if isinstance(relations, dict):
                            for relation, values in relations.items():
                                for ref in values if isinstance(values, list) else [values]:
                                    expected_citations += 1
                                    raw = (ref.get("id") or ref.get("DOI") or ref.get("doi")) if isinstance(ref, dict) else ref
                                    if not isinstance(ref, (str, dict)): malformed += 1
                                    target, resolution = self._target(raw, ref)
                                    self._citation(run_key, source, target, "relation:" + relation, provider, ref, resolution)
                        elif relations:
                            expected_citations += 1; malformed += 1
                            target, resolution = self._target(None, relations)
                            self._citation(run_key, source, target, "relation:unsupported", provider, relations, resolution)
                    for row in src.execute("SELECT * FROM documents"):
                        meta = json.loads(row["metadata"]); candidate = meta.get("candidate_id")
                        work = None
                        if candidate:
                            found = self.db.execute("SELECT work_key FROM observations WHERE run_key=? AND candidate_id=?", (run_key, candidate)).fetchone()
                            work = found[0] if found else None
                        gid = "doc:" + sha(run_key + "\0" + row["id"])[:28]
                        self.db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)", (gid, run_key, row["id"], work, row["title"], row["url"], row["sha256"], row["metadata"]))
                        for page in src.execute("SELECT locator,text FROM pages WHERE document_id=? ORDER BY rowid", (row["id"],)):
                            self._text(run_key, "document", gid, page["locator"], page["text"])
                finally: src.close()
            # Also recompute after a project removes its collection database.
            self._rebuild_identities()
            indexed_record_edges = self.db.execute("SELECT count(*) FROM record_edges WHERE run_key=?", (run_key,)).fetchone()[0]
            indexed_citations = self.db.execute("SELECT count(*) FROM citation_edges WHERE run_key=?", (run_key,)).fetchone()[0]
            unresolved = self.db.execute("SELECT count(*) FROM citation_edges WHERE run_key=? AND resolution!='resolved_local'", (run_key,)).fetchone()[0]
            stamp = now()
            self.db.execute("INSERT INTO sync_audits VALUES(?,?,?,?,?,?,?,?)", (run_key, stamp, expected_record_edges, indexed_record_edges, expected_citations, indexed_citations, unresolved, malformed))
            if expected_record_edges != indexed_record_edges or expected_citations != indexed_citations:
                raise ValueError("index coverage invariant failed")
        return {"run_key": run_key, "status": "synced", **self.status(run_key)}

    def status(self, run_key=None):
        where = " WHERE run_key=?" if run_key else ""; args = (run_key,) if run_key else ()
        counts = {table: self.db.execute(f"SELECT count(*) FROM {table}{where}", args).fetchone()[0]
                  for table in ("runs", "records", "record_edges", "observations", "documents", "texts", "citation_edges") if not run_key or table != "runs"}
        audit = self.db.execute("SELECT * FROM sync_audits" + where + " ORDER BY synced_at DESC LIMIT 1", args).fetchone()
        counts["latest_audit"] = dict(audit) if audit else None
        counts["semantic_vectors"] = self.db.execute("SELECT count(*) FROM embeddings").fetchone()[0]
        return counts

    def find(self, query, limit=20, run_key=None):
        if not 1 <= limit <= 1000: raise ValueError("limit must be 1..1000")
        terms = re.findall(r"\w+", query, flags=re.UNICODE)
        if not terms: raise ValueError("query needs words")
        match = " AND ".join('"' + x.replace('"', '""') + '"' for x in terms)
        sql = "SELECT text_id,run_key,kind,object_id,locator,snippet(text_search,5,'[',']','...',40) snippet,bm25(text_search) score FROM text_search WHERE text_search MATCH ?"
        args = [match]
        if run_key: sql += " AND run_key=?"; args.append(run_key)
        sql += " ORDER BY score LIMIT ?"; args.append(limit)
        return [dict(x) for x in self.db.execute(sql, args)]

    def build_embeddings(self, python, model, revision, batch=32):
        if batch < 1: raise ValueError("batch must be positive")
        rows = self.db.execute("SELECT t.* FROM texts t LEFT JOIN embeddings e ON e.text_id=t.text_id AND e.backend='sentence-transformers' AND e.model=? AND e.revision=? WHERE e.text_id IS NULL ORDER BY t.text_id", (model, revision)).fetchall()
        built = 0; dimension = None
        worker = Path(__file__).with_name("semantic_worker.py")
        if rows:
            request = canonical_json({"texts": [x["text"] for x in rows], "batch_size": batch})
            cmd = [python, "-B", str(worker), "--model", model, "--revision", revision, "--offline"]
            proc = subprocess.run(cmd, input=request, capture_output=True, text=True, timeout=600)
            if proc.returncode: raise ValueError("semantic worker failed: " + proc.stderr[-500:])
            result = json.loads(proc.stdout); vectors = result["vectors"]; dimension = result["dimension"]
            if result.get("model") != model or result.get("revision") != revision:
                raise ValueError("semantic worker model identity mismatch")
            if not isinstance(dimension, int) or dimension < 1: raise ValueError("invalid embedding dimension")
            if len(vectors) != len(rows): raise ValueError("semantic worker result count mismatch")
            with self.db:
                for row, vector in zip(rows, vectors):
                    if len(vector) != dimension or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector): raise ValueError("invalid embedding vector")
                    if not math.isclose(math.sqrt(sum(x*x for x in vector)), 1.0, rel_tol=1e-4, abs_tol=1e-4):
                        raise ValueError("embedding vector is not normalized")
                    blob = struct.pack("<" + "f" * dimension, *vector)
                    self.db.execute("INSERT INTO embeddings VALUES(?,?,?,?,?,?,?)", (row["text_id"], "sentence-transformers", model, revision, dimension, blob, row["text_sha256"]))
                    built += 1
        else:
            existing = self.db.execute("SELECT dimension FROM embeddings WHERE model=? AND revision=? LIMIT 1", (model, revision)).fetchone()
            dimension = existing[0] if existing else None
            proc = subprocess.run([python, "-B", str(worker), "--model", model, "--revision", revision, "--offline"], input=canonical_json({"texts": ["local semantic index readiness"]}), capture_output=True, text=True, timeout=600)
            if proc.returncode: raise ValueError("semantic worker failed: " + proc.stderr[-500:])
            probe = json.loads(proc.stdout)
            if probe.get("model") != model or probe.get("revision") != revision:
                raise ValueError("semantic worker model identity mismatch")
            if dimension is not None and probe["dimension"] != dimension: raise ValueError("semantic model dimension changed")
            dimension = probe["dimension"]
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES('semantic',?)", (canonical_json({"python": python, "backend": "sentence-transformers", "model": model, "revision": revision, "dimension": dimension}),))
        return {"built": built, "total": self.db.execute("SELECT count(*) FROM embeddings WHERE model=? AND revision=?", (model, revision)).fetchone()[0], "dimension": dimension, "model": model, "revision": revision}

    def semantic(self, query, limit=20, run_key=None):
        if not query.strip(): raise ValueError("semantic query is empty")
        if not 1 <= limit <= 1000: raise ValueError("limit must be 1..1000")
        row = self.db.execute("SELECT value FROM settings WHERE key='semantic'").fetchone()
        if not row: raise ValueError("semantic index not built")
        config = json.loads(row[0]); worker = Path(__file__).with_name("semantic_worker.py")
        proc = subprocess.run([config["python"], "-B", str(worker), "--model", config["model"], "--revision", config["revision"], "--offline"], input=canonical_json({"texts": [query]}), capture_output=True, text=True, timeout=600)
        if proc.returncode: raise ValueError("semantic worker failed: " + proc.stderr[-500:])
        result = json.loads(proc.stdout)
        if result.get("model") != config["model"] or result.get("revision") != config["revision"]:
            raise ValueError("semantic worker model identity mismatch")
        vectors = result.get("vectors")
        if not isinstance(vectors, list) or len(vectors) != 1: raise ValueError("invalid semantic query result")
        q = vectors[0]; scores = []
        if result["dimension"] != config["dimension"]: raise ValueError("semantic query dimension differs from index")
        if len(q) != config["dimension"] or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in q):
            raise ValueError("invalid semantic query vector")
        if not math.isclose(math.sqrt(sum(x*x for x in q)), 1.0, rel_tol=1e-4, abs_tol=1e-4):
            raise ValueError("semantic query vector is not normalized")
        sql = "SELECT e.*,t.run_key,t.kind,t.object_id,t.locator,t.text FROM embeddings e JOIN texts t USING(text_id) WHERE e.model=? AND e.revision=?"
        args = [config["model"], config["revision"]]
        if run_key: sql += " AND t.run_key=?"; args.append(run_key)
        for item in self.db.execute(sql, args):
            if item["text_sha256"] != sha(item["text"]): raise ValueError("embedding source text changed")
            if item["dimension"] != config["dimension"] or len(item["vector"]) != 4 * item["dimension"]:
                raise ValueError("stored embedding dimension is invalid")
            vector = struct.unpack("<" + "f" * item["dimension"], item["vector"])
            if not all(math.isfinite(x) for x in vector) or not math.isclose(math.sqrt(sum(x*x for x in vector)), 1.0, rel_tol=1e-4, abs_tol=1e-4):
                raise ValueError("stored embedding vector is invalid")
            score = sum(a*b for a,b in zip(q, vector))
            scores.append({"text_id": item["text_id"], "run_key": item["run_key"], "kind": item["kind"], "object_id": item["object_id"], "locator": item["locator"], "score": max(-1.0, min(1.0, score)), "snippet": item["text"][:500]})
        scores.sort(key=lambda x: x["score"], reverse=True)
        return {"query": query, "model": config["model"], "revision": config["revision"], "results": scores[:limit]}

    def graph(self, work, depth=1, direction="both", limit=200):
        if not 1 <= limit <= 1000: raise ValueError("limit must be 1..1000")
        alias = normalize_doi(work); alias = "doi:" + alias if alias else (openalex_alias(work) or work)
        row = self.db.execute("SELECT work_key FROM aliases WHERE alias=?", (alias,)).fetchone(); start = row[0] if row else alias
        if not self.db.execute("SELECT 1 FROM works WHERE work_key=?", (start,)).fetchone(): raise ValueError("work not found")
        queue, seen, edges = deque([(start,0)]), {start}, []
        while queue and len(edges) < limit:
            node, level = queue.popleft()
            if level >= depth: continue
            clauses=[];args=[]
            if direction in {"out","both"}: clauses.append("source_work=?");args.append(node)
            if direction in {"in","both"}: clauses.append("target_work=?");args.append(node)
            for edge in self.db.execute("SELECT * FROM citation_edges WHERE " + " OR ".join(clauses), args):
                if len(edges) >= limit: break
                item=dict(edge);item["evidence"]=json.loads(item["evidence"]);edges.append(item)
                other=edge["target_work"] if edge["source_work"]==node else edge["source_work"]
                if other not in seen: seen.add(other);queue.append((other,level+1))
        nodes=[]
        for key in seen:
            row=self.db.execute("SELECT * FROM works WHERE work_key=?",(key,)).fetchone()
            nodes.append(dict(row) if row else {"work_key":key,"external":1})
        remaining = bool(queue) or self.db.execute(
            "SELECT 1 FROM citation_edges WHERE source_work=? OR target_work=? LIMIT 1 OFFSET ?",
            (start, start, len(edges)),
        ).fetchone() is not None
        return {"start":start,"depth":depth,"direction":direction,"nodes":nodes,"edges":edges,"truncated":len(edges)>=limit and remaining}


@contextmanager
def opened(path):
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(resolved.parent, 0o700)
    lock = Path(str(resolved) + ".lock")
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    index = None
    try: index=GlobalIndex(path);yield index
    finally:
        if index:index.close()
        lock.unlink(missing_ok=True)


def setup_semantic(env, model, revision, allow_download):
    if not allow_download: raise ValueError("semantic setup installs packages and a model; pass --allow-download explicitly")
    env=Path(env).expanduser().resolve(); python=env/'bin/python'
    if not python.exists():
        uv=shutil.which("uv")
        if not uv: raise ValueError("uv is required to create the isolated semantic environment")
        subprocess.run([uv,"venv",str(env),"--python","3.12"],check=True,timeout=300)
    uv=shutil.which("uv")
    if not uv: raise ValueError("uv is required to manage the isolated semantic environment")
    subprocess.run([uv,"pip","install","--python",str(python),ST_REQUIREMENT],check=True,timeout=1200)
    worker=Path(__file__).with_name("semantic_worker.py")
    proc=subprocess.run([str(python),"-B",str(worker),"--model",model,"--revision",revision],input=canonical_json({"texts":["연구 색인 준비"]}),capture_output=True,text=True,timeout=1200)
    if proc.returncode: raise ValueError("model setup failed: "+proc.stderr[-500:])
    result=json.loads(proc.stdout)
    if result.get("model") != model or result.get("revision") != revision:
        raise ValueError("semantic worker model identity mismatch")
    return {"python":str(python),"model":model,"revision":revision,"dimension":result["dimension"],"local_inference":True}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--index",default=str(DEFAULT_INDEX));sub=p.add_subparsers(dest="cmd",required=True)
    s=sub.add_parser("sync");s.add_argument("run")
    sub.add_parser("status")
    s=sub.add_parser("find");s.add_argument("query");s.add_argument("--limit",type=int,default=20);s.add_argument("--run-key")
    s=sub.add_parser("semantic-setup");s.add_argument("--env",default=str(SEMANTIC_ENV));s.add_argument("--model",default=MODEL);s.add_argument("--revision",default=MODEL_REVISION);s.add_argument("--allow-download",action="store_true")
    s=sub.add_parser("semantic-build");s.add_argument("--python",default=str(SEMANTIC_ENV/'bin/python'));s.add_argument("--model",default=MODEL);s.add_argument("--revision",default=MODEL_REVISION);s.add_argument("--batch",type=int,default=32)
    s=sub.add_parser("semantic-search");s.add_argument("query");s.add_argument("--limit",type=int,default=20);s.add_argument("--run-key")
    s=sub.add_parser("graph");s.add_argument("work");s.add_argument("--depth",type=int,default=1);s.add_argument("--direction",choices=["in","out","both"],default="both");s.add_argument("--limit",type=int,default=200)
    args=p.parse_args(argv)
    try:
        if args.cmd=="semantic-setup": result=setup_semantic(args.env,args.model,args.revision,args.allow_download)
        else:
            with opened(args.index) as index:
                if args.cmd=="sync":result=index.sync(args.run)
                elif args.cmd=="status":result=index.status()
                elif args.cmd=="find":result={"results":index.find(args.query,args.limit,args.run_key)}
                elif args.cmd=="semantic-build":result=index.build_embeddings(args.python,args.model,args.revision,args.batch)
                elif args.cmd=="semantic-search":result=index.semantic(args.query,args.limit,args.run_key)
                else:
                    if not 1<=args.depth<=5:raise ValueError("depth must be 1..5")
                    result=index.graph(args.work,args.depth,args.direction,args.limit)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True));return 0
    except (ValueError,OSError,sqlite3.Error,subprocess.SubprocessError,json.JSONDecodeError) as exc:
        print(json.dumps({"status":"error","detail":str(exc)},ensure_ascii=False));return 2


if __name__=="__main__":raise SystemExit(main())
