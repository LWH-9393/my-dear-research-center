"""Behavioral integrity regressions with an explicitly synthetic corpus."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from fixture import build, read_lines, research, seal, write_lines


class RecordsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = build(Path(self.tmp.name) / "run")

    def check(self):
        return research.Records(self.root).validate(final=True)

    def codes(self):
        return {e["code"] for e in self.check()["errors"]}

    def mutate(self, table, func):
        rows = read_lines(self.root, table)
        func(rows)
        write_lines(self.root, table, rows)

    def test_valid_bounded_report(self):
        result = self.check()
        self.assertTrue(result["records_valid"], result["errors"])
        self.assertEqual(result["counts"]["recorded_independence_groups"], 4)
        self.assertTrue(result["limitations"])

    def test_initialization_never_overwrites(self):
        before = (self.root / "report.md").read_bytes()
        with self.assertRaises(FileExistsError):
            research.initialize(self.root, self.root / "query.md", "decision")
        self.assertEqual(before, (self.root / "report.md").read_bytes())

    def test_changed_query_detected(self):
        (self.root / "query.md").write_text("different task")
        self.assertIn("QUERY_CHANGED", self.codes())

    def test_changed_snapshot_invalidates_review(self):
        (self.root / "evidence/S05.md").write_text("B is now 99%")
        self.assertTrue({"EVIDENCE_CHANGED", "FINAL_REVIEW_STALE"}.issubset(self.codes()))

    def test_changed_report_invalidates_review(self):
        with (self.root / "report.md").open("a") as out:
            out.write("Unreviewed new recommendation")
        self.assertIn("FINAL_REVIEW_STALE", self.codes())

    def test_unread_source_cannot_support(self):
        self.mutate("sources", lambda rows: rows[0].update(access="metadata"))
        seal(self.root)
        self.assertIn("UNREAD_EVIDENCE", self.codes())

    def test_missing_counter_lens_detected(self):
        self.mutate("questions", lambda rows: rows[0]["coverage"].pop("counter"))
        seal(self.root)
        self.assertIn("COVERAGE_MISSING", self.codes())

    def test_empty_search_results_can_be_recorded(self):
        self.mutate("searches", lambda rows: rows[2].update(outcome="empty", source_ids=[], note="실제 조회했으나 반박 자료 없음; 참임을 증명하지 않음"))
        self.mutate("questions", lambda rows: [q["coverage"]["counter"].update(source_ids=[]) for q in rows])
        seal(self.root)
        self.assertTrue(self.check()["records_valid"])

    def test_missing_depth_cannot_finish(self):
        self.mutate("questions", lambda rows: rows[0].pop("depth"))
        seal(self.root)
        self.assertIn("DEPTH_MISSING", self.codes())

    def test_important_open_lead_detected(self):
        self.mutate("leads", lambda rows: rows[1].update(status="open"))
        seal(self.root)
        self.assertIn("OPEN_LEAD", self.codes())

    def test_cannot_claim_sufficiency_with_missing_key_evidence(self):
        cfg = json.loads((self.root / "run.json").read_text())
        cfg["closeout"]["reason"] = "evidence_sufficient"
        (self.root / "run.json").write_text(json.dumps(cfg))
        seal(self.root)
        self.assertIn("OVERSTATED_COMPLETION", self.codes())

    def test_unresolved_assertion_detected(self):
        self.mutate("report-map", lambda rows: rows[-1].update(stance="assert"))
        seal(self.root)
        self.assertIn("UNSUPPORTED_ASSERTION", self.codes())

    def test_missing_key_claim_detected(self):
        self.mutate("report-map", lambda rows: rows.pop())
        seal(self.root)
        self.assertIn("UNMAPPED_KEY_CLAIM", self.codes())

    def test_ghost_source_rejected(self):
        self.mutate("claims", lambda rows: rows[0]["evidence"][0].update(source_id="NONEXISTENT"))
        seal(self.root)
        self.assertIn("UNKNOWN_SOURCE", self.codes())

    def test_content_review_required(self):
        self.mutate("claims", lambda rows: rows[0].pop("content_review"))
        seal(self.root)
        self.assertIn("CONTENT_REVIEW_MISSING", self.codes())

    def test_trace_cycle_rejected(self):
        self.mutate("trace", lambda rows: rows[0].update(parent_ids=["T05"]))
        seal(self.root)
        self.assertIn("TRACE_CYCLE", self.codes())

    def test_unanchored_requirement_rejected(self):
        self.mutate("trace", lambda rows: rows[-2].update(parent_ids=["Q01"]))
        seal(self.root)
        self.assertIn("TRACE_WITHOUT_CLAIM", self.codes())

    def test_outside_snapshot_rejected(self):
        outside = Path(self.tmp.name) / "private.txt"
        outside.write_text("not to be read")
        self.mutate("sources", lambda rows: rows[0].update(evidence_file="../private.txt"))
        self.assertIn("FILE_ACCESS", self.codes())

    def test_symlink_outside_rejected(self):
        outside = Path(self.tmp.name) / "external.txt"
        outside.write_text("outside")
        (self.root / "evidence/link.md").symlink_to(outside)
        self.mutate("sources", lambda rows: rows[0].update(evidence_file="evidence/link.md"))
        self.assertIn("FILE_ACCESS", self.codes())

    def test_false_independent_record_lacks_context(self):
        self.mutate("reviews", lambda rows: rows[-1].update(mode="independent"))
        self.assertIn("REQUIRED_TEXT", self.codes())

    def test_open_major_final_finding_rejected(self):
        self.mutate("reviews", lambda rows: rows[-1].update(findings=[{"id": "F1", "severity": "major", "judgment": "보고서의 비교 기준 오류", "evidence": "같은 지표가 아님", "impact": "선택 무효", "status": "open"}]))
        self.assertIn("OPEN_MAJOR_FINDING", self.codes())

    def test_missing_corpus_review_rejected(self):
        self.mutate("reviews", lambda rows: rows.pop(0))
        self.assertIn("CORPUS_REVIEW_MISSING", self.codes())

    def test_duplicate_id_rejected(self):
        self.mutate("sources", lambda rows: rows.append(dict(rows[0])))
        self.assertIn("DUPLICATE_ID", self.codes())

    def test_malformed_json_returns_failure(self):
        (self.root / "claims.jsonl").write_text('{"id":\n')
        self.assertIn("INVALID_JSONL", self.codes())

    def test_cli_has_nonzero_final_failure_without_mutation(self):
        before = (self.root / "run.json").read_bytes()
        self.mutate("questions", lambda rows: rows[0].update(status="open"))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = research.main(["validate", str(self.root), "--final"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out.getvalue())["records_valid"])
        self.assertEqual(before, (self.root / "run.json").read_bytes())

    def test_derivative_labels_cannot_inflate_source_count(self):
        self.mutate("sources", lambda rows: [rows[i].update(independence_group=f"copy-{i}") for i in (1, 2)])
        seal(self.root)
        result = self.check()
        self.assertEqual(result["counts"]["recorded_independence_groups"], 4)

    def test_circular_source_provenance_rejected(self):
        self.mutate("sources", lambda rows: rows[0].update(derived_from=["S03"]))
        seal(self.root)
        self.assertIn("SOURCE_CYCLE", self.codes())

    def test_later_review_can_dismiss_earlier_wrong_finding(self):
        self.mutate("reviews", lambda rows: rows[-1].update(verdict="revise"))
        seal(self.root, "Earlier claim of missing correction dismissed: C04 already uses the correction.")
        self.assertTrue(self.check()["records_valid"])

    def test_breadth_query_cannot_masquerade_as_counter_search(self):
        self.mutate("questions", lambda rows: rows[0]["coverage"]["counter"].update(search_ids=["A01"]))
        seal(self.root)
        self.assertIn("COVERAGE_LENS_MISMATCH", self.codes())

    def test_investigated_lead_requires_actual_search_record(self):
        self.mutate("leads", lambda rows: rows[0].update(search_ids=[]))
        seal(self.root)
        self.assertIn("EMPTY_REFS", self.codes())

    def test_wrong_field_type_fails_cli_without_traceback(self):
        self.mutate("sources", lambda rows: rows[0].update(access=[]))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = research.main(["validate", str(self.root), "--final"])
        self.assertNotEqual(code, 0)
        self.assertFalse(json.loads(out.getvalue())["records_valid"])

    def test_empty_review_cannot_erase_a_prior_major_finding(self):
        self.mutate("reviews", lambda rows: rows[-1].update(findings=[{"id": "F1", "severity": "major", "judgment": "주요 결함", "evidence": "본문 근거", "impact": "결론에 영향", "status": "open"}]))
        seal(self.root)
        self.assertIn("FINDING_NOT_CLOSED", self.codes())
        self.mutate("reviews", lambda rows: rows[-1].update(findings=[{"id": "F1", "severity": "major", "judgment": "주요 결함", "evidence": "본문 근거", "impact": "결론에 영향", "status": "dismissed", "resolution": "원문 대조 결과 해당 조건이 이미 반영되어 있었음을 확인"}]))
        self.assertTrue(self.check()["records_valid"])

    def test_duplicate_json_field_rejected(self):
        (self.root / "claims.jsonl").write_text('{"id":"C01","status":"unresolved","status":"supported"}\n')
        self.assertIn("INVALID_JSONL", self.codes())

    def test_nonfinite_json_number_rejected(self):
        (self.root / "claims.jsonl").write_text('{"id":"C01","value":NaN}\n')
        self.assertIn("INVALID_JSONL", self.codes())

    def test_blank_json_line_rejected(self):
        with (self.root / "claims.jsonl").open("a") as out:
            out.write("\n")
        self.assertIn("INVALID_JSONL", self.codes())


if __name__ == "__main__":
    unittest.main()
