#!/usr/bin/env python3
"""Local research records: initialize, inspect and validate. No network or models.

Validation checks recorded evidence integrity, not factual truth or whether a
human/model actually performed a declared read/review. Python 3.10+, stdlib only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

TABLES = ("questions", "searches", "sources", "claims", "leads", "trace", "reviews", "report-map")
LENSES = ("breadth", "primary", "counter", "applicability")
HASH = re.compile(r"[0-9a-f]{64}\Z")
CLAIM_STATES = {"supported", "conditional", "unresolved", "refuted"}
CORE = ("run.json", "query.md") + tuple(f"{name}.jsonl" for name in TABLES if name not in {"reviews", "report-map"})


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def strict_json(raw):
    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"duplicate JSON key: {key}")
            obj[key] = value
        return obj

    def reject_constant(value):
        raise ValueError(f"non-JSON numeric constant: {value}")

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)


def contained(root: Path, relative) -> Path:
    if not nonempty(relative) or Path(relative).is_absolute():
        raise ValueError("expected a nonempty path relative to the run directory")
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()) or result == root.resolve():
        raise ValueError("path escapes the run directory")
    return result


def initialize(root: Path, query_file: Path, purpose: str) -> dict:
    query = query_file.read_bytes()
    if not query.decode("utf-8").strip():
        raise ValueError("research query is empty")
    root.mkdir(parents=True, exist_ok=False)
    (root / "query.md").write_bytes(query)
    config = {
        "schema_version": 1, "created_at": now(), "purpose": purpose,
        "research_depth": "broad-deep", "query_sha256": digest(query),
        "phase": "scope", "scope": "", "amendments": [],
        "closeout": {"reason": "pending", "rationale": "", "limitations": []},
    }
    (root / "run.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name in TABLES:
        (root / f"{name}.jsonl").write_text("", encoding="utf-8")
    (root / "report.md").write_text("", encoding="utf-8")
    (root / "evidence").mkdir()
    return {"created": str(root.resolve()), "research_depth": "broad-deep", "records_valid": False}


class Records:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.data: dict[str, list[dict]] = {}
        self.index: dict[str, dict[str, dict]] = {}
        self.config = self.load_json("run.json")
        seen = set()
        for table in TABLES:
            records = self.load_lines(f"{table}.jsonl")
            self.data[table] = records
            self.index[table] = {}
            for n, record in enumerate(records, 1):
                key = record.get("id")
                if not nonempty(key):
                    self.error("MISSING_ID", f"{table}:{n}", "record needs a nonempty id")
                elif key in seen:
                    self.error("DUPLICATE_ID", key, "ids must be unique across all record tables")
                else:
                    seen.add(key)
                    self.index[table][key] = record

    def error(self, code, record, detail):
        self.errors.append({"code": code, "record": record, "detail": detail})

    def warn(self, code, record, detail):
        self.warnings.append({"code": code, "record": record, "detail": detail})

    def read(self, name) -> bytes:
        try:
            return contained(self.root, name).read_bytes()
        except (OSError, ValueError) as exc:
            self.error("FILE_ACCESS", str(name), str(exc))
            return b""

    def load_json(self, name):
        try:
            value = strict_json(self.read(name))
            if not isinstance(value, dict):
                raise ValueError("expected an object")
            return value
        except (ValueError, UnicodeError) as exc:
            self.error("INVALID_JSON", name, str(exc))
            return {}

    def load_lines(self, name):
        records = []
        try:
            lines = self.read(name).decode("utf-8").splitlines()
        except UnicodeError as exc:
            self.error("INVALID_UTF8", name, str(exc))
            return records
        for n, line in enumerate(lines, 1):
            if not line.strip():
                self.error("INVALID_JSONL", f"{name}:{n}", "blank lines are not JSON values")
                continue
            try:
                item = strict_json(line)
                if not isinstance(item, dict):
                    raise ValueError("expected a JSON object per line")
                records.append(item)
            except ValueError as exc:
                self.error("INVALID_JSONL", f"{name}:{n}", str(exc))
        return records

    def text_fields(self, obj, fields, label):
        for field in fields:
            if not nonempty(obj.get(field)):
                self.error("REQUIRED_TEXT", label, f"{field} needs nonempty text")

    def choice(self, obj, field, choices, label):
        value = obj.get(field)
        if not isinstance(value, str) or value not in choices:
            self.error("INVALID_VALUE", label, f"{field} must be one of {sorted(choices)}")

    def timestamp(self, value, label):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timestamp needs a timezone")
        except (AttributeError, TypeError, ValueError):
            self.error("INVALID_TIMESTAMP", label, "use an ISO-8601 timestamp with timezone")

    def refs(self, obj, field, targets, label, required=False):
        values = obj.get(field, [])
        if not isinstance(values, list) or any(not nonempty(x) for x in values):
            self.error("INVALID_REFS", label, f"{field} must be an array of ids")
            return []
        if required and not values:
            self.error("EMPTY_REFS", label, f"{field} needs at least one id")
        for value in values:
            if value not in targets:
                self.error("UNKNOWN_REF", label, f"{field}: {value}")
        return values

    def object_list(self, obj, field, label):
        value = obj.get(field, [])
        if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
            self.error("INVALID_LIST", label, f"{field} must contain objects")
            return []
        return value

    def fingerprint(self, stage):
        names = list(CORE)
        if stage == "final":
            names.extend(("report.md", "report-map.jsonl"))
        for source in self.data["sources"]:
            if source.get("evidence_file"):
                names.append(source["evidence_file"])
        hashes = {}
        for name in names:
            if not isinstance(name, str):
                self.error("INVALID_PATH", "fingerprint", "path must be text")
                continue
            hashes[name] = digest(self.read(name))
        return digest(json.dumps(hashes, sort_keys=True, ensure_ascii=False).encode("utf-8"))

    def validate(self, final=False):
        qidx, sidx, cidx = (self.index[x] for x in ("questions", "sources", "claims"))
        aidx, tidx = (self.index[x] for x in ("searches", "trace"))
        if self.config.get("schema_version") != 1:
            self.error("SCHEMA_VERSION", "run", "expected schema_version=1")
        self.choice(self.config, "purpose", {"explanation", "decision", "implementation"}, "run")
        self.choice(self.config, "research_depth", {"broad-deep", "user-limited"}, "run")
        self.choice(self.config, "phase", {"scope", "breadth", "depth", "synthesis", "review", "delivery"}, "run")
        self.timestamp(self.config.get("created_at"), "run.created_at")
        if self.config.get("research_depth") == "user-limited":
            self.text_fields(self.config, ("depth_change_instruction",), "run")
        if digest(self.read("query.md")) != self.config.get("query_sha256"):
            self.error("QUERY_CHANGED", "query.md", "preserve the original query; put later instructions in run.amendments")
        amendments = self.object_list(self.config, "amendments", "run")
        for item in amendments:
            self.text_fields(item, ("instruction", "impact"), "amendment")
            self.timestamp(item.get("at"), "amendment.at")

        for key, source in sidx.items():
            self.text_fields(source, ("title", "origin", "independence_group", "applicability", "read_scope"), key)
            if not nonempty(source.get("url")) and not nonempty(source.get("local_path")):
                self.error("SOURCE_LOCATION", key, "need url or original local_path")
            self.choice(source, "kind", {"primary", "secondary", "context"}, key)
            self.choice(source, "access", {"full", "partial", "metadata", "blocked"}, key)
            self.timestamp(source.get("accessed_at"), key)
            self.refs(source, "derived_from", sidx, key)
            if source.get("access") in {"full", "partial"} or source.get("evidence_file"):
                self.text_fields(source, ("evidence_file", "evidence_sha256"), key)
                blob = self.read(source.get("evidence_file"))
                if not blob.strip():
                    self.error("EMPTY_EVIDENCE", key, "evidence snapshot/note is empty")
                if digest(blob) != source.get("evidence_sha256"):
                    self.error("EVIDENCE_CHANGED", key, "snapshot bytes do not match recorded hash")
            if source.get("published_at") is None:
                self.warn("UNDATED_SOURCE", key, "publication date unknown; check applicability manually")

        for key, search in aidx.items():
            self.text_fields(search, ("query", "method", "note"), key)
            self.choice(search, "lens", set(LENSES) | {"followup"}, key)
            self.choice(search, "outcome", {"found", "empty", "blocked"}, key)
            self.timestamp(search.get("executed_at"), key)
            self.refs(search, "question_ids", qidx, key, required=True)
            self.refs(search, "source_ids", sidx, key)

        for key, claim in cidx.items():
            self.text_fields(claim, ("text", "rationale", "applicability"), key)
            self.choice(claim, "importance", {"key", "supporting"}, key)
            self.choice(claim, "kind", {"observed", "source_claim", "inference"}, key)
            self.choice(claim, "status", CLAIM_STATES, key)
            self.refs(claim, "question_ids", qidx, key, required=True)
            evidence = self.object_list(claim, "evidence", key)
            supports = []
            for binding in evidence:
                self.text_fields(binding, ("source_id", "locator", "note"), key)
                self.choice(binding, "relation", {"supports", "refutes", "context"}, key)
                sid = binding.get("source_id")
                source = sidx.get(sid) if isinstance(sid, str) else None
                if source is None:
                    self.error("UNKNOWN_SOURCE", key, str(sid))
                elif source.get("access") not in {"full", "partial"} and binding.get("relation") in {"supports", "refutes"}:
                    self.error("UNREAD_EVIDENCE", key, f"{sid} has no read body")
                elif binding.get("relation") == "supports":
                    supports.append(source)
            if claim.get("status") in {"supported", "conditional"} and not supports:
                self.error("NO_SUPPORT", key, "supported/conditional claims need readable supporting evidence")
            if final:
                review = claim.get("content_review")
                if not isinstance(review, dict):
                    self.error("CONTENT_REVIEW_MISSING", key, "record actual sentence-to-evidence review")
                else:
                    self.text_fields(review, ("reviewer", "note"), key)
                    self.timestamp(review.get("checked_at"), key)
                    required_result = {"supported": "supports", "conditional": "qualified", "unresolved": "insufficient", "refuted": "refutes"}.get(claim.get("status"))
                    if review.get("result") != required_result:
                        self.error("REVIEW_STATE_CONFLICT", key, "content review result does not match claim status")

        for key, question in qidx.items():
            self.text_fields(question, ("text",), key)
            self.choice(question, "importance", {"key", "supporting"}, key)
            self.choice(question, "status", {"open", "answered", "bounded"}, key)
            claims = self.refs(question, "claim_ids", cidx, key)
            for cid in claims:
                if cid in cidx and key not in cidx[cid].get("question_ids", []):
                    self.error("QUESTION_CLAIM_MISMATCH", key, cid)
            if not final:
                continue
            if question.get("status") == "open":
                self.error("OPEN_QUESTION", key, "answer or explicitly bound the question")
            if question.get("status") == "bounded":
                self.text_fields(question, ("limitation",), key)
            if question.get("status") == "answered" and not claims:
                self.error("ANSWER_WITHOUT_CLAIMS", key, "answer must connect to the claim ledger")
            if question.get("importance") != "key":
                continue
            coverage = question.get("coverage", {})
            if not isinstance(coverage, dict):
                self.error("COVERAGE_MISSING", key, "coverage must be an object")
                continue
            for lens in LENSES:
                cell = coverage.get(lens)
                if not isinstance(cell, dict):
                    self.error("COVERAGE_MISSING", key, lens)
                    continue
                self.choice(cell, "status", {"done", "limited", "not_applicable"}, f"{key}.{lens}")
                self.text_fields(cell, ("note",), f"{key}.{lens}")
                searches = self.refs(cell, "search_ids", aidx, key, required=cell.get("status") == "done")
                sources = self.refs(cell, "source_ids", sidx, key)
                for aid in searches:
                    if aid in aidx and key not in aidx[aid].get("question_ids", []):
                        self.error("COVERAGE_SEARCH_MISMATCH", key, aid)
                    if aid in aidx and aidx[aid].get("lens") not in {lens, "followup"}:
                        self.error("COVERAGE_LENS_MISMATCH", key, f"{aid} was not recorded for {lens}")
                if lens in {"breadth", "primary"} and cell.get("status") == "not_applicable":
                    self.error("CORE_LENS_OMITTED", key, lens)
                if cell.get("status") == "done" and lens != "counter":
                    if not any(sidx.get(sid, {}).get("access") in {"full", "partial"} for sid in sources):
                        self.error("COVERAGE_WITHOUT_READING", key, lens)
            depth = question.get("depth")
            if not isinstance(depth, dict):
                self.error("DEPTH_MISSING", key, "record primary tracing, methods, counterevidence, applicability and change_mind")
            else:
                self.text_fields(depth, ("primary_trace", "methods", "counterevidence", "applicability", "change_mind"), key)

        for key, lead in self.index["leads"].items():
            self.text_fields(lead, ("text", "relevance"), key)
            self.choice(lead, "priority", {"critical", "important", "background"}, key)
            self.choice(lead, "status", {"open", "investigated", "duplicate", "irrelevant", "unavailable", "deferred"}, key)
            self.refs(lead, "question_ids", qidx, key, required=True)
            self.refs(lead, "search_ids", aidx, key, required=lead.get("status") == "investigated")
            self.refs(lead, "source_ids", sidx, key)
            if lead.get("status") != "open":
                self.text_fields(lead, ("resolution",), key)
            if final and lead.get("status") == "open":
                self.error("OPEN_LEAD", key, "resolve, investigate or explicitly defer this lead")

        parents = {**qidx, **cidx, **tidx}
        graph = {}
        for key, item in tidx.items():
            self.choice(item, "kind", {"issue", "option", "decision", "requirement", "action"}, key)
            self.text_fields(item, ("text", "rationale"), key)
            graph[key] = self.refs(item, "parent_ids", parents, key, required=True)
            if item.get("kind") in {"requirement", "action"}:
                self.text_fields(item, ("acceptance",), key)

        # Iterative traversal avoids recursion limits on a long dependency chain.
        for start in graph:
            stack, reached, ancestors = [(start, ())], set(), False
            while stack:
                node, path = stack.pop()
                if node in path:
                    self.error("TRACE_CYCLE", start, " -> ".join(path + (node,)))
                    continue
                if node in reached:
                    continue
                reached.add(node)
                if node in cidx:
                    ancestors = True
                stack.extend((p, path + (node,)) for p in graph.get(node, []))
            if final and not ancestors:
                self.error("TRACE_WITHOUT_CLAIM", start, "trace item must reach a recorded claim")

        if final:
            self.final_checks(qidx, cidx, tidx)
        return self.result(final)

    def final_checks(self, qidx, cidx, tidx):
        if not qidx:
            self.error("NO_QUESTIONS", "questions", "research needs a scope decomposition")
        self.text_fields(self.config, ("scope",), "run")
        closeout = self.config.get("closeout")
        if not isinstance(closeout, dict):
            self.error("CLOSEOUT_MISSING", "run", "closeout must be an object")
            closeout = {}
        self.choice(closeout, "reason", {"evidence_sufficient", "bounded_limits", "user_limit"}, "closeout")
        self.text_fields(closeout, ("rationale",), "closeout")
        limits = closeout.get("limitations")
        if not isinstance(limits, list) or any(not nonempty(x) for x in limits):
            self.error("INVALID_LIMITATIONS", "closeout", "limitations must be an array of nonempty strings")
        elif closeout.get("reason") in {"bounded_limits", "user_limit"} and not limits:
            self.error("LIMITATIONS_MISSING", "closeout", "state the material limits")
        bounded = any(q.get("status") == "bounded" for q in qidx.values())
        bounded |= any(l.get("priority") in {"critical", "important"} and l.get("status") in {"unavailable", "deferred"} for l in self.data["leads"])
        bounded |= any(c.get("importance") == "key" and c.get("status") == "unresolved" for c in cidx.values())
        bounded |= any(isinstance(q.get("coverage"), dict) and any(isinstance(v, dict) and v.get("status") == "limited" for v in q["coverage"].values()) for q in qidx.values())
        if bounded and closeout.get("reason") == "evidence_sufficient":
            self.error("OVERSTATED_COMPLETION", "closeout", "important gaps remain; use bounded_limits or user_limit with their impact")
        if self.config.get("purpose") == "implementation":
            kinds = {x.get("kind") for x in tidx.values() if isinstance(x.get("kind"), str)}
            for kind in ("decision", "requirement", "action"):
                if kind not in kinds:
                    self.error("IMPLEMENTATION_TRACE_MISSING", "trace", kind)
        elif self.config.get("purpose") == "decision" and not any(x.get("kind") == "decision" for x in tidx.values()):
            self.error("DECISION_TRACE_MISSING", "trace", "decision purpose needs a traced decision")

        report = self.read("report.md").decode("utf-8")
        if not report.strip():
            self.error("EMPTY_REPORT", "report.md", "write the actual deliverable text")
        covered = set()
        allowed = {"supported": {"assert", "qualified"}, "conditional": {"qualified"}, "unresolved": {"uncertain"}, "refuted": {"refuted"}}
        for item in self.data["report-map"]:
            key = item.get("id", "report-map")
            self.text_fields(item, ("text",), key)
            self.choice(item, "stance", {"assert", "qualified", "uncertain", "refuted"}, key)
            if not nonempty(item.get("text")) or item["text"] not in report:
                self.error("REPORT_TEXT_MISSING", key, "exact mapped text not found in report.md")
            for cid in self.refs(item, "claim_ids", cidx, key, required=True):
                if cid in cidx:
                    covered.add(cid)
                    if item.get("stance") not in allowed.get(cidx[cid].get("status"), set()):
                        self.error("UNSUPPORTED_ASSERTION", key, f"stance conflicts with {cid} status")
        keyclaims = {key for key, c in cidx.items() if c.get("importance") == "key"}
        for cid in keyclaims - covered:
            self.error("UNMAPPED_KEY_CLAIM", cid, "key claim is missing from the report map")

        current = self.fingerprint("final")
        reviews = self.data["reviews"]
        if not any(r.get("stage") == "corpus" for r in reviews):
            self.error("CORPUS_REVIEW_MISSING", "reviews", "record the actual pre-draft evidence gap review")
        matching = []
        for record in reviews:
            key = record.get("id", "review")
            self.choice(record, "stage", {"corpus", "final"}, key)
            self.choice(record, "mode", {"self", "independent"}, key)
            self.choice(record, "verdict", {"acceptable", "revise", "inconclusive"}, key)
            self.text_fields(record, ("reviewer", "scope", "note"), key)
            self.timestamp(record.get("checked_at"), key)
            if not isinstance(record.get("input_digest"), str) or not HASH.fullmatch(record["input_digest"]):
                self.error("REVIEW_DIGEST_MISSING", key, "record the fingerprint at review time")
            if record.get("mode") == "independent":
                self.text_fields(record, ("context_ref",), key)
            claims = self.refs(record, "claim_ids", cidx, key)
            findings = self.object_list(record, "findings", key)
            for finding in findings:
                self.text_fields(finding, ("id", "judgment", "evidence", "impact"), key)
                self.choice(finding, "severity", {"critical", "major", "minor"}, key)
                self.choice(finding, "status", {"open", "resolved", "dismissed"}, key)
                if finding.get("status") != "open":
                    self.text_fields(finding, ("resolution",), key)
            if record.get("stage") == "final" and record.get("input_digest") == current:
                matching.append((record, claims, findings))
        if not matching:
            self.error("FINAL_REVIEW_STALE", "reviews", "no final review matches the current report and evidence")
        else:
            # JSONL order is append order; a later review may resolve or dismiss
            # an earlier erroneous finding without changing the reviewed inputs.
            record, claims, findings = matching[-1]
            key = record.get("id", "review")
            if record.get("verdict") == "revise":
                self.error("REVISION_REQUIRED", key, "current final review requests revision")
            if any(f.get("status") == "open" and f.get("severity") in {"critical", "major"} for f in findings):
                self.error("OPEN_MAJOR_FINDING", key, "current report has unresolved major findings")
            if record.get("report_checked") is not True or not keyclaims.issubset(set(claims)):
                self.error("FINAL_REVIEW_SCOPE", key, "final review must check the report and every key claim")
            if record.get("verdict") == "inconclusive" and not closeout.get("limitations"):
                self.error("INCONCLUSIVE_WITHOUT_LIMITS", key, "describe what the review could not establish")
            last_findings = {}
            for historical in reviews:
                for finding in historical.get("findings", []) if isinstance(historical.get("findings", []), list) else []:
                    if isinstance(finding, dict) and nonempty(finding.get("id")):
                        last_findings[finding["id"]] = finding
                if historical is record:
                    break
            for fid, finding in last_findings.items():
                if finding.get("status") == "open" and finding.get("severity") in {"critical", "major"}:
                    self.error("FINDING_NOT_CLOSED", fid, "preserve a resolution/dismissal record; a later empty review does not close a finding")

    def source_groups(self):
        sources = self.index["sources"]
        groups = set()
        for start, source in sources.items():
            if source.get("access") not in {"full", "partial"}:
                continue
            stack, seen = [(start, ())], set()
            while stack:
                sid, path = stack.pop()
                if sid in path:
                    self.error("SOURCE_CYCLE", start, " -> ".join(path + (sid,)))
                    continue
                if sid in seen or sid not in sources:
                    continue
                seen.add(sid)
                current = sources[sid]
                parents = current.get("derived_from", [])
                if not isinstance(parents, list):
                    continue  # refs() reports malformed provenance.
                parents = [p for p in parents if nonempty(p)]
                if parents:
                    stack.extend((p, path + (sid,)) for p in parents)
                elif nonempty(current.get("independence_group")):
                    groups.add(current["independence_group"])
        return groups

    def result(self, final):
        source_counts = Counter(s.get("access", "invalid") for s in self.data["sources"] if isinstance(s.get("access", "invalid"), str))
        groups = self.source_groups()
        closeout = self.config.get("closeout", {})
        return {
            "run": str(self.root), "check": "final" if final else "working",
            "records_valid": not self.errors,
            "limits_of_check": "Checks record structure, links and byte fingerprints. Does not prove source truth, actual reading, semantic entailment or reviewer independence.",
            "counts": {**{k: len(v) for k, v in self.data.items()}, "source_access": dict(source_counts), "recorded_independence_groups": len(groups)},
            "limitations": closeout.get("limitations", []) if isinstance(closeout, dict) else [],
            "errors": self.errors, "warnings": self.warnings,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("init", help="create a new run; never overwrite an existing directory")
    new.add_argument("run", type=Path)
    new.add_argument("--query-file", type=Path, required=True)
    new.add_argument("--purpose", choices=("explanation", "decision", "implementation"), default="decision")
    check = sub.add_parser("validate", help="check records without changing them")
    check.add_argument("run", type=Path)
    check.add_argument("--final", action="store_true")
    status = sub.add_parser("status", help="read current counts and unfinished/final validation issues")
    status.add_argument("run", type=Path)
    fingerprint = sub.add_parser("fingerprint", help="identify review inputs; does not perform a review")
    fingerprint.add_argument("run", type=Path)
    fingerprint.add_argument("--stage", choices=("corpus", "final"), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result, code = initialize(args.run, args.query_file, args.purpose), 0
        else:
            records = Records(args.run)
            if args.command == "fingerprint":
                result = {"stage": args.stage, "input_digest": records.fingerprint(args.stage), "errors": records.errors}
                code = 1 if records.errors else 0
            else:
                result = records.validate(final=args.command == "status" or args.final)
                code = 0 if args.command == "status" or result["records_valid"] else 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (OSError, ValueError, UnicodeError, TypeError) as exc:
        print(json.dumps({"records_valid": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
