"""Pure projections of recorded research relationships; no inferred citations."""
from __future__ import annotations
import re
from index_inputs import IndexProblem, canonical_json, sha


def normalize_doi(value):
    if not isinstance(value, str): return None
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", value.strip(), flags=re.I)
    return value.lower() if re.fullmatch(r"10\.\d{4,9}/\S+", value) else None


def openalex_alias(value):
    if not isinstance(value, str): return None
    tail = value.rstrip("/").rsplit("/", 1)[-1]
    return "openalex:" + tail.upper() if re.fullmatch(r"W\d+", tail, re.I) else None


def observation_aliases(item):
    provider, pid = str(item["provider"]), str(item["provider_id"])
    aliases = {provider + ":" + pid}
    doi = normalize_doi(item.get("doi")); oa = openalex_alias(pid)
    if doi: aliases.add("doi:" + doi)
    if oa: aliases.add(oa)
    return aliases


def canonical_alias(aliases):
    return min(aliases, key=lambda a: (0 if a.startswith("doi:") else 1 if a.startswith("openalex:") else 2, a))


def record_edges(records):
    known = {k: {r["id"] for r in v} for k, v in records.items()}
    edges = []
    def add(kind, row, target, field, relation, obj=None):
        values = (row if obj is None else obj).get(field, [])
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            raise IndexProblem("invalid_input", "record relationship must be an ID list")
        for value in values:
            if value not in known[target]: raise IndexProblem("invalid_input", "unresolved record edge")
            edges.append((kind, row["id"], target, value, relation, {}))
    for kind, rows in records.items():
        for row in rows:
            if kind == "sources": add(kind, row, "sources", "derived_from", "derived_from")
            elif kind == "searches":
                add(kind, row, "questions", "question_ids", "investigates")
                add(kind, row, "sources", "source_ids", "found_source")
            elif kind == "claims":
                add(kind, row, "questions", "question_ids", "addresses")
                evidence = row.get("evidence", [])
                if not isinstance(evidence, list): raise IndexProblem("invalid_input", "claim evidence must be a list")
                for ev in evidence:
                    if not isinstance(ev, dict) or ev.get("source_id") not in known["sources"]:
                        raise IndexProblem("invalid_input", "unresolved claim evidence")
                    relation = ev.get("relation", "evidence")
                    if not isinstance(relation, str): raise IndexProblem("invalid_input", "invalid evidence relation")
                    edges.append((kind, row["id"], "sources", ev["source_id"], relation, ev))
            elif kind == "questions":
                add(kind, row, "claims", "claim_ids", "answered_by")
                coverage = row.get("coverage", {})
                if not isinstance(coverage, dict): raise IndexProblem("invalid_input", "invalid question coverage")
                for lens, cell in coverage.items():
                    if not isinstance(cell, dict): raise IndexProblem("invalid_input", "invalid coverage cell")
                    add(kind, row, "searches", "search_ids", "covered_by:" + lens, cell)
                    add(kind, row, "sources", "source_ids", "coverage_source:" + lens, cell)
            elif kind == "leads":
                add(kind, row, "questions", "question_ids", "concerns")
                add(kind, row, "searches", "search_ids", "investigated_by")
                add(kind, row, "sources", "source_ids", "resolved_with")
            elif kind == "trace":
                values = row.get("parent_ids", [])
                if not isinstance(values, list): raise IndexProblem("invalid_input", "invalid trace parents")
                for value in values:
                    target = next((k for k in ("questions", "claims", "trace") if isinstance(value, str) and value in known[k]), None)
                    if not target: raise IndexProblem("invalid_input", "unresolved trace parent")
                    edges.append((kind, row["id"], target, value, "parent", {}))
            elif kind in {"reviews", "report-map"}:
                add(kind, row, "claims", "claim_ids", "reviews_claim" if kind == "reviews" else "maps_claim")
    return edges


def citation_items(item):
    for field in ("references", "updates"):
        values = item.get(field, [])
        if values is None: continue
        if not isinstance(values, list):
            yield field + ":unsupported", values, True
        else:
            for value in values: yield field, value, not isinstance(value, (str, dict))
    relations = item.get("relations", {})
    if relations is None: return
    if not isinstance(relations, dict):
        yield "relation:unsupported", relations, True
    else:
        for relation, values in relations.items():
            for value in values if isinstance(values, list) else [values]:
                yield "relation:" + relation, value, not isinstance(value, (str, dict))


def project(observations):
    """Rebuild only from live raw observations, so removed aliases cannot revive."""
    parent, parsed = {}, []
    def find(a):
        parent.setdefault(a, a)
        if parent[a] != a: parent[a] = find(parent[a])
        return parent[a]
    for run_key, candidate_id, item in sorted(observations, key=lambda x: (x[0], x[1])):
        aliases = observation_aliases(item)
        first = min(aliases)
        for alias in sorted(aliases):
            a, b = find(first), find(alias)
            if a != b: parent[max(a, b)] = min(a, b)
        parsed.append((run_key, candidate_id, item, aliases))
    groups = {}
    for alias in parent: groups.setdefault(find(alias), set()).add(alias)
    mapping = {a: canonical_alias(group) for group in groups.values() for a in group}
    works, identities, edges, audits = {}, {}, {}, {}
    for run_key, cid, item, aliases in parsed:
        key = mapping[min(aliases)]; identities[(run_key, cid)] = key
        work = works.setdefault(key, {"title": item.get("title"), "doi": normalize_doi(item.get("doi")), "metadata": {}, "external": 0})
        work["metadata"].setdefault(item["provider"], []).append({"provider_id": item["provider_id"], "doi": item.get("doi")})
    for run_key, cid, item, _ in parsed:
        audit = audits.setdefault(run_key, {"expected": 0, "malformed": 0, "indexed": 0, "unresolved": 0})
        for relation, evidence, malformed in citation_items(item):
            audit["expected"] += 1; audit["malformed"] += int(malformed)
            raw = (evidence.get("DOI") or evidence.get("doi") or evidence.get("id")) if isinstance(evidence, dict) else evidence
            doi = normalize_doi(raw); alias = "doi:" + doi if doi else openalex_alias(raw)
            key = mapping.get(alias, alias) if alias else "unresolved:" + sha(canonical_json(evidence))[:24]
            if key not in works:
                works[key] = {"title": None, "doi": doi, "metadata": {"reference": evidence}, "external": 1}
            if alias: mapping[alias] = key
            resolution = "resolved_local" if not works[key]["external"] else "external_identifier" if alias else "unresolved_metadata"
            source = identities[(run_key, cid)]
            eid = "cite:" + sha(canonical_json([run_key, source, key, relation, item["provider"], evidence]))[:28]
            edges[eid] = (eid, run_key, source, key, relation, item["provider"], canonical_json(evidence), resolution)
    for edge in edges.values():
        audits[edge[1]]["indexed"] += 1
        audits[edge[1]]["unresolved"] += int(edge[-1] != "resolved_local")
    return works, mapping, identities, edges, audits
