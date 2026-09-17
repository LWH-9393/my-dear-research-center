"""Synthetic local corpus and structurally valid example; no real-world claims.

The populated review records below are TEST DATA, not evidence of an actual
independent reviewer. Behavioral evaluation uses corpus/ and the query only.
"""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("research", PACKAGE / "scripts/research.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)

QUERY = """가상 제품 A와 B 중 표를 포함한 500페이지 문서 처리 도입안을 정리해 주세요.
목표는 정확도 95% 이상, 최대 메모리 4 GiB 이하입니다.
제공한 로컬 자료만 폭넓고 깊게 조사하고 근거·반증·실행 요건을 연결하세요.
이 자료는 스킬 평가를 위한 가상 데이터이며 실제 제품이나 성능을 나타내지 않습니다.
"""
DOCS = {
    "S01": ("A 발표자료", "A-vendor", "A-study", "primary", "A의 정확도는 98%다. 시험 대상은 표가 없는 20개 짧은 문서다. 메모리는 2 GiB다. 500페이지 문서는 시험하지 않았다."),
    "S02": ("A 소개 블로그", "publisher-one", "A-study", "secondary", "A 발표자료를 인용한다. A 정확도 98%, 메모리 2 GiB. 별도 실험은 수행하지 않았다."),
    "S03": ("A 뉴스레터", "publisher-two", "A-study", "secondary", "A 소개 블로그를 재인용한다. 정확도 98%로 업계 최고라고 소개한다. 평가 데이터는 추가하지 않았다."),
    "S04": ("공통 환경 시험표", "test-lab", "lab-study", "primary", "표 포함 500페이지 문서, 같은 환경. A 정확도 81%, 최대 메모리 5.2 GiB. B 정확도 96%, 최대 메모리 3.6 GiB. 이후 정정문이 있다."),
    "S05": ("시험표 정정", "test-lab", "lab-study", "primary", "B 정확도는 집계에서 실패를 누락한 오류로 96%에서 94%로 정정한다. A의 값과 B 메모리 3.6 GiB는 변함없다. 정정된 값이 원래 정확도 수치를 대체한다."),
    "S06": ("B 신규 옵션 자료", "B-vendor", "B-study", "primary", "B의 신규 layout 옵션을 켠 12개 짧은 표 문서에서 정확도 97%, 메모리 3.8 GiB. 이 옵션으로 500페이지 문서를 시험한 결과는 제공하지 않는다."),
    "S07": ("시험 조건", "test-lab", "lab-study", "primary", "정확도는 보존되어야 할 표 셀 중 올바르게 추출된 셀의 비율이다. 공통 환경 시험은 기본 옵션이다. A 발표자료의 일반 텍스트 정확도 정의와 다르다."),
    "S08": ("도입 제약", "requester", "user-requirements", "primary", "도입 대상은 표 포함 500페이지 문서다. 목표 정확도 95% 이상, 최대 메모리 4 GiB 이하. 현재 승인된 자료 외 실제 실험 결과는 없다. 다음 단계로 내부 파일럿 계획을 작성할 수 있다."),
}


def write_lines(root, table, rows):
    (root / f"{table}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def read_lines(root, table):
    return [json.loads(line) for line in (root / f"{table}.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def seal(root, note="SYNTHETIC TEST RECORD; not an actual independent review"):
    records = research.Records(root)
    rows = read_lines(root, "reviews")
    rows.append({
        "id": f"Rfinal{len(rows)}", "stage": "final", "mode": "self", "reviewer": "fixture-generator",
        "checked_at": datetime.now(timezone.utc).isoformat(), "scope": "Synthetic record of full report and key claims",
        "note": note, "input_digest": records.fingerprint("final"), "verdict": "acceptable",
        "claim_ids": list(records.index["claims"]), "report_checked": True, "findings": [],
    })
    write_lines(root, "reviews", rows)


def build(root: Path):
    root = Path(root)
    stamp = datetime.now(timezone.utc).isoformat()
    query = root.parent / f"{root.name}-query.md"
    query.write_text(QUERY, encoding="utf-8")
    research.initialize(root, query, "implementation")
    (root / "corpus").mkdir()
    sources = []
    for sid, (title, origin, group, kind, body) in DOCS.items():
        content = f"가상 평가 자료 — 실제 제품·연구가 아님\n{title}\n{body}\n"
        original = root / "corpus" / f"{sid}.md"
        original.write_text(content, encoding="utf-8")
        snapshot = root / "evidence" / f"{sid}.md"
        snapshot.write_text(content, encoding="utf-8")
        sources.append({
            "id": sid, "title": title, "local_path": str(original), "kind": kind,
            "origin": origin, "independence_group": group,
            "derived_from": {"S02": ["S01"], "S03": ["S02"]}.get(sid, []),
            "published_at": None, "accessed_at": stamp, "applicability": "가상 문서 시험 조건에만 적용",
            "read_scope": "짧은 가상 원문 전체", "access": "full",
            "evidence_file": f"evidence/{sid}.md", "evidence_sha256": research.digest(snapshot.read_bytes()),
        })
    write_lines(root, "sources", sources)
    searches = []
    for n, (lens, ids, note) in enumerate([
        ("breadth", list(DOCS), "제공된 8개 자료 전체 목록과 내용을 확인하는 가상 조사 기록"),
        ("primary", ["S01", "S04", "S05", "S06", "S07", "S08"], "발표 수치의 원문과 정정·시험 조건을 추적하는 가상 기록"),
        ("counter", ["S05", "S06", "S07"], "정정문·비교 조건 차이·미시험 범위를 확인하는 가상 기록"),
        ("applicability", ["S04", "S05", "S06", "S07", "S08"], "정의·문서 크기·표본·옵션·자원 기준의 적용성을 확인하는 가상 기록"),
    ], 1):
        searches.append({"id": f"A{n:02}", "question_ids": ["Q01", "Q02", "Q03"], "query": f"로컬 corpus: {lens}", "method": "synthetic-local-read", "lens": lens, "executed_at": stamp, "outcome": "found", "source_ids": ids, "note": note})
    write_lines(root, "searches", searches)
    definitions = [
        ("C01", "A의 98%는 표 없는 짧은 문서 시험의 발표값이다.", "supported", ["Q01"], [("S01", "supports"), ("S07", "context")]),
        ("C02", "공통 환경에서 A는 정확도 81%, 최대 메모리 5.2 GiB다.", "supported", ["Q01", "Q02"], [("S04", "supports"), ("S05", "supports")]),
        ("C03", "공통 환경의 B 정확도가 현재도 96%라는 주장은 정정문으로 반박된다.", "refuted", ["Q01"], [("S04", "context"), ("S05", "refutes")]),
        ("C04", "정정 후 B는 정확도 94%, 최대 메모리 3.6 GiB다.", "supported", ["Q01", "Q02"], [("S05", "supports"), ("S04", "supports")]),
        ("C05", "B 신규 옵션은 추가 검증을 전제로 파일럿 후보가 될 수 있다.", "conditional", ["Q03"], [("S06", "supports"), ("S08", "supports")]),
        ("C06", "B 신규 옵션이 대상 500페이지 문서에서 목표를 충족하는지는 미확정이다.", "unresolved", ["Q03"], [("S06", "context"), ("S08", "context")]),
    ]
    claims = []
    for cid, body, state, qids, bindings in definitions:
        claims.append({"id": cid, "text": body, "question_ids": qids, "importance": "key", "kind": "inference" if cid == "C05" else "source_claim", "status": state,
                       "rationale": "가상 원자료의 조건·정정 내용을 근거로 하는 시험 레코드", "applicability": "제공된 시험 조건과 가상 도입 제약",
                       "evidence": [{"source_id": sid, "locator": "본문", "relation": relation, "note": DOCS[sid][4]} for sid, relation in bindings],
                       "content_review": {"reviewer": "synthetic-fixture", "checked_at": stamp, "result": {"supported": "supports", "conditional": "qualified", "refuted": "refutes", "unresolved": "insufficient"}[state], "note": "가상 검토 레코드. 독립 검토 수행 증명이 아님."}})
    write_lines(root, "claims", claims)
    questions = []
    for qid, body, state, ids in [
        ("Q01", "정확도 목표를 충족하는가?", "answered", ["C01", "C02", "C03", "C04"]),
        ("Q02", "메모리 조건을 충족하는가?", "answered", ["C02", "C04"]),
        ("Q03", "어떤 도입·검증 절차가 필요한가?", "bounded", ["C05", "C06"]),
    ]:
        questions.append({"id": qid, "text": body, "importance": "key", "status": state, "claim_ids": ids,
                          "limitation": "신규 옵션의 대상 문서 시험이 없어 도입 확정 불가",
                          "coverage": {a["lens"]: {"status": "done", "search_ids": [a["id"]], "source_ids": a["source_ids"], "note": a["note"]} for a in searches},
                          "depth": {"primary_trace": "S02→S01, S03→S02→S01; S04→S05 정정 추적", "methods": "표 셀 정확도와 일반 텍스트 정확도 구분", "counterevidence": "B 96%는 94%로 정정, A 98%는 다른 조건", "applicability": "500페이지·표·최대 메모리 조건으로 비교", "change_mind": "동일 대상과 환경에서 신규 옵션의 실험 결과가 확보되면 재판단"}})
    write_lines(root, "questions", questions)
    write_lines(root, "leads", [
        {"id": "L01", "text": "B 시험표 정정 확인", "question_ids": ["Q01"], "relevance": "정확도 기준 충족 판정 변경", "priority": "critical", "status": "investigated", "search_ids": ["A03"], "source_ids": ["S05"], "resolution": "정정된 94% 적용"},
        {"id": "L02", "text": "B 신규 옵션의 실제 대상 시험", "question_ids": ["Q03"], "relevance": "도입 결정을 바꿀 수 있음", "priority": "important", "status": "unavailable", "search_ids": ["A04"], "source_ids": ["S06", "S08"], "resolution": "제공 자료에 해당 시험이 없음. 허용된 범위는 로컬 자료 조사와 후속 계획임."},
    ])
    trace = [
        {"id": "T01", "kind": "issue", "text": "기본 방식은 두 조건을 함께 충족하지 못한다.", "parent_ids": ["C02", "C04"], "rationale": "A는 두 기준, B는 정확도 기준 미달"},
        {"id": "T02", "kind": "option", "text": "B 신규 옵션 파일럿", "parent_ids": ["C05", "C06"], "rationale": "작은 표본 결과를 대상으로 확대 검증"},
        {"id": "T03", "kind": "decision", "text": "즉시 도입은 유보하고 제한 파일럿으로 검증한다.", "parent_ids": ["T01", "T02"], "rationale": "현재 증거로 목표 충족을 확정할 수 없음"},
        {"id": "T04", "kind": "requirement", "text": "동일 대상·환경에서 두 조건을 동시에 측정한다.", "parent_ids": ["T03", "C06"], "rationale": "비교 조건 불일치 해결", "acceptance": "정확도 ≥95%, 최대 메모리 ≤4 GiB; 원시 실패 수와 표본 공개"},
        {"id": "T05", "kind": "action", "text": "대표 500페이지 표 문서로 B 신규 옵션 파일럿을 계획한다.", "parent_ids": ["T04"], "rationale": "미확정 성능을 확인할 다음 행동", "acceptance": "사전 고정한 문서·환경·정의로 정확도와 메모리 측정, 실패 로그 보존"},
    ]
    write_lines(root, "trace", trace)
    report = "가상 평가 결과 — 실제 제품에 대한 추천이 아니다.\n\n"
    mappings = []
    for n, claim in enumerate(claims, 1):
        report += claim["text"] + "\n\n"
        mappings.append({"id": f"M{n:02}", "text": claim["text"], "claim_ids": [claim["id"]], "stance": {"supported": "assert", "conditional": "qualified", "unresolved": "uncertain", "refuted": "refuted"}[claim["status"]]})
    report += "즉시 도입을 유보하고, 같은 기준의 제한 파일럿에서 정확도 95% 이상과 최대 메모리 4 GiB 이하를 동시에 확인한다.\n"
    (root / "report.md").write_text(report, encoding="utf-8")
    write_lines(root, "report-map", mappings)
    cfg = json.loads((root / "run.json").read_text())
    cfg.update({"phase": "delivery", "scope": "제공된 가상 로컬 자료 8개 전체. 목적은 도입 판단과 후속 검증 계획. 웹·실험 실행은 범위 밖.", "closeout": {"reason": "bounded_limits", "rationale": "제공된 원자료·정정·조건을 조사했지만 신규 옵션의 실제 대상 증거는 없다.", "limitations": ["B 신규 옵션의 500페이지 문서 시험은 미확정이다."]}})
    (root / "run.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_lines(root, "reviews", [{"id": "Rcorpus", "stage": "corpus", "mode": "self", "reviewer": "fixture-generator", "checked_at": stamp, "scope": "가상 증거집 전체", "note": "S01 재인용 중복과 S05 정정 및 S06 적용 공백을 반영한 가상 검토 기록", "input_digest": research.Records(root).fingerprint("corpus"), "verdict": "inconclusive", "claim_ids": list(research.Records(root).index["claims"]), "findings": []}])
    seal(root)
    return root


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(build(args.path))


def window_manifest(texts):
    """Synthetic one-window protocol for plumbing tests; not tokenizer evidence."""
    from semantic_chunks import WINDOW_VERSION
    return {"window_version": WINDOW_VERSION, "max_seq_length": 128,
            "spans": [{"input": i, "start": 0, "end": len(text), "token_count": 1}
                      for i, text in enumerate(texts)]}
