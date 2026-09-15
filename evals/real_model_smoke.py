#!/usr/bin/env python3
"""Opt-in real-model retrieval smoke test; synthetic facts, never a benchmark.

Requires the pinned Sentence Transformers environment. --allow-download permits
only this test's pinned model download; normal regressions never download models.
"""
from __future__ import annotations

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
import tempfile
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/"scripts"), str(Path(__file__).resolve().parent)]
import fixture
import index as idx
from semantic_windows import token_windows

# Freeze queries/expected sources before looking at results. All facts are fiction.
DOCUMENTS = {
    "S01": ("Routine maintenance includes inspecting instruments and recording measurements. " * 10
            + "Project Aurora uses a sapphire optical link for emergency underwater communication."),
    "S02": ("정기 점검은 장비 상태와 보관 기록을 확인하는 작업입니다. " * 18
            + "제퍼 보관소에서 암호화 키를 복구하려면 서로 다른 관리자 세 명의 승인이 필요합니다."),
}
CASES = [
    ("How does Project Aurora communicate during an underwater emergency?", "S01"),
    ("Project Aurora의 수중 비상 통신에는 어떤 연결을 사용하나요?", "S01"),
    ("제퍼 보관소의 암호화 키를 복구하려면 몇 명의 관리자 승인이 필요한가요?", "S02"),
    ("How many separate custodians must approve recovery of the encryption key?", "S02"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.allow_download:
        parser.error("explicit --allow-download is required for the real-model smoke test")
    from sentence_transformers import SentenceTransformer
    started = time.monotonic()
    result = {"test_type": "synthetic_real_model_smoke_not_benchmark", "model": idx.MODEL,
              "revision": idx.MODEL_REVISION, "python": platform.python_version(),
              "sentence_transformers": version("sentence-transformers"), "cases": [],
              "acceptance": "each expected evidence source appears in the first five unfiltered hits"}
    try:
        model = SentenceTransformer(idx.MODEL, revision=idx.MODEL_REVISION, trust_remote_code=False)
        result["max_seq_length"] = model.max_seq_length
        result["input_coverage"] = []
        for source, text in DOCUMENTS.items():
            count = len(model.tokenizer.encode(text, add_special_tokens=True, truncation=False, verbose=False))
            windows = token_windows(text, model.tokenizer, model.max_seq_length)
            result["input_coverage"].append({"source_id": source, "original_tokens": count,
                "windows": len(windows), "largest_window_tokens": max(w["token_count"] for w in windows),
                "tail_covered": windows[-1]["end"] == len(text)})
            if count <= model.max_seq_length:
                raise AssertionError("smoke input does not exercise the original truncation bug")
        # Release the first model before subprocess-based index integration.
        del model
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); run = fixture.build(base/"run")
            sources = fixture.read_lines(run, "sources")
            for source in sources:
                if source["id"] in DOCUMENTS:
                    blob = DOCUMENTS[source["id"]].encode()
                    (run/source["evidence_file"]).write_bytes(blob)
                    source["evidence_sha256"] = idx.sha(blob)
            fixture.write_lines(run, "sources", sources)
            with idx.opened(base/"index.sqlite3") as index:
                index.sync(run)
                result["build"] = index.build_embeddings(sys.executable, idx.MODEL, idx.MODEL_REVISION)
                for query, expected in CASES:
                    found = index.semantic(query, limit=5)
                    rank = next((i for i, row in enumerate(found["results"], 1)
                                 if row["kind"] == "evidence" and row["object_id"] == expected), None)
                    result["cases"].append({"query": query, "expected_source": expected,
                        "rank_in_top5": rank, "passed": rank is not None,
                        "hits": [{k: hit[k] for k in ("kind", "object_id", "locator", "score", "snippet", "window")}
                                 for hit in found["results"]]})
                result["no_change_refresh"] = index.refresh(run, "smoke_noop", "auto")["embedding_build"]
        result["passed"] = all(x["passed"] for x in result["cases"])
    except Exception as exc:
        result.update(passed=False, error_type=type(exc).__name__, error=str(exc))
    finally:
        result["elapsed_seconds"] = round(time.monotonic()-started, 3)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
