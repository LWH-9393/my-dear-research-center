"""Offline regressions for the cross-project index and citation coverage."""
from pathlib import Path
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect
import fixture
import index as research_index


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.run = fixture.build(self.base / "run")
        with collect.open_corpus(self.run) as corpus:
            corpus.add_candidates("crossref", [{
                "provider_id": "10.1000/a", "doi": "10.1000/a", "title": "Alpha study",
                "references": [{"DOI": "10.1000/b"}, {"unstructured": "Unknown predecessor"}],
                "updates": [{"DOI": "10.1000/c"}], "relations": {},
            }])
            corpus.add_candidates("openalex", [{
                "provider_id": "https://openalex.org/W42", "doi": "10.1000/b",
                "title": "Beta study", "references": ["https://openalex.org/W99"],
            }])
            corpus.ingest(b"A semantic passage about evidence synthesis and review methods.",
                          url="https://example.org/a", title="Alpha document")
        self.path = self.base / "global.sqlite3"
        self.index = research_index.GlobalIndex(self.path); self.addCleanup(self.index.close)

    def test_sync_is_complete_and_idempotent(self):
        result = self.index.sync(self.run)
        audit = result["latest_audit"]
        self.assertEqual(audit["expected_record_edges"], audit["indexed_record_edges"])
        self.assertEqual(audit["expected_citations"], audit["indexed_citations"])
        self.assertEqual(audit["expected_citations"], 4)
        self.assertEqual(audit["unresolved_citations"], 3)
        self.assertEqual(self.index.sync(self.run)["status"], "unchanged")

    def test_multiple_projects_share_one_index_and_work_identity(self):
        first = self.index.sync(self.run)
        second_run = fixture.build(self.base / "second-run")
        with collect.open_corpus(second_run) as corpus:
            corpus.add_candidates("openalex", [{
                "provider_id": "https://openalex.org/W777", "doi": "10.1000/a",
                "title": "Alpha study from another project", "references": [],
            }])
            corpus.ingest(b"A second project passage about research synthesis.",
                          url="https://example.org/second", title="Second document")
        second = self.index.sync(second_run)
        self.assertNotEqual(first["run_key"], second["run_key"])
        self.assertEqual(self.index.status()["runs"], 2)
        self.assertEqual(self.index.db.execute("SELECT count(*) FROM works WHERE work_key='doi:10.1000/a'").fetchone()[0], 1)
        self.assertEqual({x["run_key"] for x in self.index.find("synthesis")}, {first["run_key"], second["run_key"]})

    def test_identity_is_stable_when_a_doi_arrives_later_and_earlier_run_changes(self):
        early = fixture.build(self.base / "early")
        with collect.open_corpus(early) as corpus:
            corpus.add_candidates("openalex", [{"provider_id": "https://openalex.org/W500", "title": "Same work", "references": []}])
        late = fixture.build(self.base / "late")
        with collect.open_corpus(late) as corpus:
            corpus.add_candidates("openalex", [{"provider_id": "https://openalex.org/W500", "doi": "10.1000/merged", "title": "Same work", "references": []}])
        self.index.sync(early); self.index.sync(late)
        (early / "report.md").write_text((early / "report.md").read_text() + "\nchanged\n")
        self.index.sync(early)
        keys = {x[0] for x in self.index.db.execute("SELECT work_key FROM observations WHERE payload LIKE '%W500%'")}
        self.assertEqual(keys, {"doi:10.1000/merged"})
        self.assertEqual(self.index.db.execute("SELECT work_key FROM aliases WHERE alias='openalex:W500'").fetchone()[0], "doi:10.1000/merged")

    def test_unresolved_reference_is_preserved_as_node(self):
        self.index.sync(self.run)
        rows = self.index.db.execute("SELECT target_work,resolution FROM citation_edges WHERE resolution='unresolved_metadata'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["target_work"].startswith("unresolved:"))

    def test_alias_resolves_openalex_work_to_doi(self):
        self.index.sync(self.run)
        alias = self.index.db.execute("SELECT work_key FROM aliases WHERE alias='openalex:W42'").fetchone()[0]
        self.assertEqual(alias, "doi:10.1000/b")
        self.assertEqual(self.index.db.execute("SELECT external FROM works WHERE work_key='doi:10.1000/b'").fetchone()[0], 0)
        self.assertEqual(self.index.db.execute("SELECT external FROM works WHERE work_key='doi:10.1000/c'").fetchone()[0], 1)

    def test_global_text_search_covers_records_and_documents(self):
        self.index.sync(self.run)
        self.assertTrue(any(x["kind"] == "document" for x in self.index.find("evidence synthesis")))
        self.assertTrue(any(x["kind"].startswith("record:") for x in self.index.find("정확도")))

    def test_sync_replaces_changed_run_without_duplicate_text(self):
        first = self.index.sync(self.run)
        before = first["texts"]
        report = self.run / "report.md"; report.write_text(report.read_text() + "\n새 색인 문장\n")
        second = self.index.sync(self.run)
        self.assertEqual(second["status"], "synced")
        self.assertGreaterEqual(second["texts"], before)
        count = self.index.db.execute("SELECT count(*) FROM texts WHERE run_key=?", (second["run_key"],)).fetchone()[0]
        self.assertEqual(count, second["texts"])

    def test_removing_project_collection_removes_or_demotes_orphan_work(self):
        self.index.sync(self.run)
        shutil.rmtree(self.run / "collection")
        self.index.sync(self.run)
        row = self.index.db.execute("SELECT external FROM works WHERE work_key='doi:10.1000/a'").fetchone()
        self.assertTrue(row is None or row[0] == 1)

    def test_query_tamper_is_rejected(self):
        (self.run / "query.md").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "hash"): self.index.sync(self.run)

    def test_collection_page_tamper_is_rejected(self):
        db = sqlite3.connect(self.run / "collection/corpus.sqlite3")
        db.execute("UPDATE pages SET text='tampered' WHERE rowid=(SELECT min(rowid) FROM pages)"); db.commit(); db.close()
        with self.assertRaisesRegex(ValueError, "pages changed"): self.index.sync(self.run)

    def test_collection_source_tamper_is_rejected(self):
        db = sqlite3.connect(self.run / "collection/corpus.sqlite3")
        body = self.run / db.execute("SELECT body_path FROM documents LIMIT 1").fetchone()[0]; db.close()
        body.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "source bytes changed"): self.index.sync(self.run)

    def test_collection_body_path_escape_is_rejected(self):
        outside = self.base / "outside"; outside.write_bytes(b"outside")
        db = sqlite3.connect(self.run / "collection/corpus.sqlite3")
        db.execute("UPDATE documents SET body_path=?,sha256=?", (str(outside), research_index.sha(outside.read_bytes()))); db.commit(); db.close()
        with self.assertRaisesRegex(ValueError, "escapes"): self.index.sync(self.run)

    def test_research_record_graph_is_complete(self):
        result = self.index.sync(self.run)
        audit = result["latest_audit"]
        self.assertGreater(audit["expected_record_edges"], 0)
        self.assertEqual(audit["expected_record_edges"], audit["indexed_record_edges"])
        relations = {x[0] for x in self.index.db.execute("SELECT relation FROM record_edges")}
        self.assertTrue({"investigates", "found_source", "concerns", "investigated_by", "resolved_with", "reviews_claim"} <= relations)

    def test_unsupported_citation_relation_is_preserved_and_counted(self):
        db = sqlite3.connect(self.run / "collection/corpus.sqlite3")
        row = db.execute("SELECT id,payload FROM candidates ORDER BY id LIMIT 1").fetchone()
        payload = json.loads(row[1]); payload["relations"] = ["10.1234/dropped"]
        db.execute("UPDATE candidates SET payload=? WHERE id=?", (json.dumps(payload), row[0])); db.commit(); db.close()
        result = self.index.sync(self.run)
        self.assertEqual(result["latest_audit"]["malformed_citations"], 1)
        self.assertEqual(result["latest_audit"]["expected_citations"], result["latest_audit"]["indexed_citations"])
        self.assertEqual(self.index.db.execute("SELECT count(*) FROM citation_edges WHERE relation='relation:unsupported'").fetchone()[0], 1)

    def test_graph_reports_external_nodes(self):
        self.index.sync(self.run)
        graph = self.index.graph("10.1000/a", depth=1, direction="out")
        self.assertEqual(graph["start"], "doi:10.1000/a")
        self.assertEqual(len(graph["edges"]), 3)
        self.assertTrue(any(x["external"] for x in graph["nodes"] if x["work_key"] != graph["start"]))

    def test_graph_honors_edge_limit(self):
        self.index.sync(self.run)
        graph = self.index.graph("10.1000/a", depth=1, direction="out", limit=2)
        self.assertEqual(len(graph["edges"]), 2)
        self.assertTrue(graph["truncated"])

    def test_semantic_setup_requires_explicit_download(self):
        with self.assertRaisesRegex(ValueError, "allow-download"):
            research_index.setup_semantic(self.base / "env", research_index.MODEL,
                                          research_index.MODEL_REVISION, False)

    def test_semantic_build_and_search_preserve_model_identity(self):
        self.index.sync(self.run)
        def fake_run(cmd, input, **kwargs):
            count = len(json.loads(input)["texts"])
            vectors = [[1.0, 0.0] for _ in range(count)]
            return subprocess.CompletedProcess(cmd, 0, json.dumps({**fixture.window_manifest(json.loads(input)["texts"]), "model": "fixture/model", "revision": "revision", "dimension": 2, "vectors": vectors}), "")
        with patch.object(research_index.subprocess, "run", side_effect=fake_run):
            built = self.index.build_embeddings("python", "fixture/model", "revision")
            found = self.index.semantic("관련 의미", limit=2)
        self.assertEqual(built["dimension"], 2)
        self.assertEqual(found["model"], "fixture/model")
        self.assertEqual(len(found["results"]), 2)

    def test_nonpositive_semantic_batch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            self.index.build_embeddings("python", "fixture/model", "revision", batch=0)

    def test_invalid_result_limits_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "limit"): self.index.find("query", limit=0)
        with self.assertRaisesRegex(ValueError, "limit"): self.index.semantic("query", limit=0)

    def test_embedding_source_tamper_is_rejected(self):
        self.index.sync(self.run)
        def fake_run(cmd, input, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, json.dumps({**fixture.window_manifest(json.loads(input)["texts"]), "model": "fixture/model", "revision": "revision", "dimension": 1, "vectors": [[1.0] for _ in json.loads(input)["texts"]]}), "")
        with patch.object(research_index.subprocess, "run", side_effect=fake_run):
            self.index.build_embeddings("python", "fixture/model", "revision")
        self.index.db.execute("UPDATE texts SET text='tampered' WHERE rowid=(SELECT min(rowid) FROM texts)")
        with patch.object(research_index.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(ValueError, "changed"): self.index.semantic("query")

    def test_semantic_worker_identity_and_normalization_are_verified(self):
        self.index.sync(self.run)
        def wrong_identity(cmd, input, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, json.dumps({**fixture.window_manifest(json.loads(input)["texts"]), "model": "wrong", "revision": "revision", "dimension": 1, "vectors": [[1.0] for _ in json.loads(input)["texts"]]}), "")
        with patch.object(research_index.subprocess, "run", side_effect=wrong_identity):
            with self.assertRaisesRegex(ValueError, "identity"): self.index.build_embeddings("python", "fixture/model", "revision")
        def unnormalized(cmd, input, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, json.dumps({**fixture.window_manifest(json.loads(input)["texts"]), "model": "fixture/model", "revision": "revision", "dimension": 1, "vectors": [[2.0] for _ in json.loads(input)["texts"]]}), "")
        with patch.object(research_index.subprocess, "run", side_effect=unnormalized):
            with self.assertRaisesRegex(ValueError, "normalized"): self.index.build_embeddings("python", "fixture/model", "revision")

    def test_private_index_permissions_are_enforced(self):
        folder = self.base / "private"; old = os.umask(0)
        try:
            idx = research_index.GlobalIndex(folder / "index.sqlite3")
        finally: os.umask(old)
        idx.close()
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        self.assertEqual((folder / "index.sqlite3").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__": unittest.main()
