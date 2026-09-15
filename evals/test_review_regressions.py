"""Regression cases for review findings; entirely synthetic, offline inputs."""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "scripts"), str(Path(__file__).resolve().parent)]
import fixture
import index as idx
from index_inputs import snapshot
from semantic_fixture import with_windows
from semantic_windows import encode_windowed, token_windows, validate_windows


class CharacterTokenizer:
    """A deterministic test tokenizer: one token per character plus BOS/EOS."""
    def encode(self, text, add_special_tokens=True, **kwargs):
        assert kwargs.get("truncation") is False
        return ([0] if add_special_tokens else []) + [ord(x) for x in text] + ([1] if add_special_tokens else [])


class Array:
    def __init__(self, rows): self.rows = rows
    def astype(self, dtype): return self
    def tolist(self): return self.rows


class WindowModel:
    """A marker-sensitive fake model; no semantic-quality claim is implied."""
    tokenizer = CharacterTokenizer()
    max_seq_length = 40
    do_lower_case = False
    def __init__(self): self.seen = []
    def __getitem__(self, index): return self
    def get_sentence_embedding_dimension(self): return 2
    def encode(self, texts, **kwargs):
        self.seen.extend(texts)
        for text in texts:
            if len(self.tokenizer.encode(text.strip(), truncation=False)) > self.max_seq_length:
                raise AssertionError("encoder received an over-limit input")
        return Array([[0., 1.] if "tailmarker" in text else [1., 0.] for text in texts])


def fake_worker(cmd, input, **kwargs):
    texts = json.loads(input)["texts"]
    model = WindowModel()
    vectors, windows, dimension = encode_windowed(model, texts)
    return subprocess.CompletedProcess(cmd, 0, json.dumps({"model": "fixture/model", "revision": "rev",
        "dimension": dimension, "vectors": vectors, "windows": windows}), "")


class WindowTests(unittest.TestCase):
    def test_long_unicode_input_has_exact_coverage_and_bounded_tokens(self):
        text = ("한국어 English 😀 e\u0301 안전한 검증. " * 30) + "tailmarker"
        tokenizer = CharacterTokenizer()
        windows = token_windows(text, tokenizer, 40)
        self.assertGreater(len(windows), 1)
        covered = 0
        for window in windows:
            self.assertLessEqual(window["start"], covered)
            part = text[window["start"]:window["end"]]
            actual = len(tokenizer.encode(part.strip(), truncation=False))
            self.assertEqual(window["token_count"], actual)
            self.assertLessEqual(actual, 40)
            covered = window["end"]
        self.assertEqual(covered, len(text))
        self.assertTrue(text[windows[-1]["start"]:].endswith("tailmarker"))

    def test_encoder_receives_tail_and_every_window(self):
        model = WindowModel(); text = "ordinary words "*60 + "tailmarker"
        _, manifests, dimension = encode_windowed(model, [text])
        self.assertEqual(len(model.seen), len(manifests[0]["windows"]))
        self.assertTrue(any("tailmarker" in x for x in model.seen))
        self.assertTrue(any(w["vector"] == [0., 1.] for w in manifests[0]["windows"]))
        validate_windows(manifests[0], text, dimension)

    def test_empty_and_whitespace_inputs_are_preserved(self):
        for text in ["", "  \n\t "]:
            _, manifests, dimension = encode_windowed(WindowModel(), [text])
            validate_windows(manifests[0], text, dimension)
            self.assertEqual(manifests[0]["windows"][-1]["end"], len(text))

    def test_no_overlap_still_covers_every_character(self):
        text = "a"*180
        windows = token_windows(text, CharacterTokenizer(), 12, overlap_tokens=0)
        self.assertEqual("".join(text[w["start"]:w["end"]] for w in windows), text)

    def test_special_token_budget_is_enforced(self):
        for limit in [0, 1, 2, True, None]:
            with self.assertRaises(ValueError): token_windows("x", CharacterTokenizer(), limit)

    def test_negative_overlap_is_rejected(self):
        with self.assertRaises(ValueError): token_windows("x", CharacterTokenizer(), 10, -1)

    def test_missing_window_protocol_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "manifests"):
            idx.worker_windows({"vectors": [[1., 0.]]}, ["x"], 2)

    def test_manifest_rejects_tail_gap_wrong_hash_and_large_token_count(self):
        text = "words "*60
        _, manifests, _ = encode_windowed(WindowModel(), [text])
        for mutate in [lambda p: p["windows"].pop(),
                       lambda p: p.update(text_sha256="bad"),
                       lambda p: p["windows"][0].update(start=1),
                       lambda p: p["windows"][0].update(token_count=999),
                       lambda p: p["windows"][0].update(vector=[float("nan"), 0.])]:
            payload = copy.deepcopy(manifests[0]); mutate(payload)
            with self.assertRaises(ValueError): validate_windows(payload, text, 2)


class EvidenceAndValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.run = fixture.build(self.base/"run")
        self.index = idx.GlobalIndex(self.base/"index.sqlite3"); self.addCleanup(self.index.close)

    def note(self, content, suffix=".md"):
        rows = fixture.read_lines(self.run, "sources")
        path = self.run/"evidence"/("S01"+suffix)
        path.write_bytes(content)
        rows[0].update(evidence_file=str(path.relative_to(self.run)), evidence_sha256=idx.sha(content))
        fixture.write_lines(self.run, "sources", rows)

    def errors(self):
        fixture.seal(self.run)
        return {x["code"] for x in fixture.research.Records(self.run).validate(final=True)["errors"]}

    def build(self):
        with patch.object(idx.subprocess, "run", side_effect=fake_worker):
            return self.index.build_embeddings("fixture-python", "fixture/model", "rev")

    def test_note_only_term_is_globally_searchable(self):
        self.note("노트전용식별자 evidenceonlymarker".encode())
        self.index.sync(self.run)
        for query in ["노트전용식별자", "evidenceonlymarker"]:
            matches = self.index.find(query)
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["kind"], "evidence")
            self.assertEqual(matches[0]["object_id"], "S01")
            self.assertEqual(matches[0]["locator"], "evidence/S01.md")

    def test_note_tail_window_is_ranked_and_snippet_points_to_hit(self):
        self.note(("ordinary words "*65 + "tailmarker").encode())
        self.index.sync(self.run); self.build()
        with patch.object(idx.subprocess, "run", side_effect=fake_worker):
            result = self.index.semantic("tailmarker", limit=1)
        hit = result["results"][0]
        self.assertEqual((hit["kind"], hit["object_id"]), ("evidence", "S01"))
        self.assertIn("tailmarker", hit["snippet"])
        self.assertGreater(hit["window"]["start"], 128)
        self.assertEqual(hit["offset_basis"], "indexed_text_chunk")
        self.assertEqual(result["aggregation"], "max_window_cosine")

    def test_note_hash_tamper_remains_excluded_from_normal_search(self):
        self.note(b"evidenceonlymarker"); self.index.sync(self.run)
        (self.run/"evidence/S01.md").write_bytes(b"changed without ledger")
        self.assertEqual(self.index.find("evidenceonlymarker"), [])
        self.assertEqual(self.index.last_coverage[0]["status"], "integrity_error")

    def test_nontext_or_nonutf8_evidence_is_reported_not_silently_dropped(self):
        for content, suffix in [(b"%PDF-test fixture only", ".pdf"), (b"\x80\xff", ".txt"), (b"a\x00b", ".txt")]:
            self.note(content, suffix); self.index.sync(self.run)
            coverage = self.index.check(self.run)["unindexed_evidence"]
            self.assertEqual(len(coverage), 1)
            self.assertEqual(coverage[0]["source_id"], "S01")
            self.assertTrue(coverage[0]["reason"])

    def test_utf8_bom_note_is_searchable(self):
        self.note(b"\xef\xbb\xbf" + "한글전용표식".encode())
        self.index.sync(self.run)
        self.assertTrue(self.index.find("한글전용표식"))

    def test_changed_note_replaces_only_affected_search_texts(self):
        self.note(b"firstonlymarker"); self.index.sync(self.run); self.build()
        other = {r[0]: r[1] for r in self.index.db.execute("SELECT text_id,vector FROM embeddings JOIN texts USING(text_id) WHERE kind='document' OR (kind='evidence' AND object_id='S02')")}
        self.note(b"secondonlymarker"); self.index.sync(self.run)
        self.assertEqual(self.index.find("firstonlymarker"), [])
        self.assertTrue(self.index.find("secondonlymarker"))
        current = dict(self.index.db.execute("SELECT text_id,vector FROM embeddings"))
        self.assertTrue(all(current[k] == v for k,v in other.items()))

    def test_scope_exclusion_removes_window_payloads(self):
        self.index.sync(self.run); self.build()
        self.assertGreater(self.index.db.execute("SELECT count(*) FROM embedding_windows").fetchone()[0], 0)
        self.index.set_scope(self.run, "off")
        self.assertEqual(self.index.db.execute("SELECT count(*) FROM embedding_windows").fetchone()[0], 0)

    def test_window_payload_tamper_is_detected(self):
        self.index.sync(self.run); self.build()
        with self.index.db: self.index.db.execute("UPDATE embedding_windows SET payload='{}'")
        with patch.object(idx.subprocess, "run", side_effect=fake_worker):
            with self.assertRaisesRegex(ValueError, "window bytes changed"):
                self.index.semantic("query")

    def test_missing_windows_are_pending_and_rebuilt(self):
        self.index.sync(self.run); self.build()
        with self.index.db: self.index.db.execute("DELETE FROM embedding_windows")
        self.assertEqual(self.index.semantic_status()["ready"], 0)
        count = self.index.semantic_status()["pending"]
        self.assertEqual(self.build()["built"], count)
        self.assertEqual(self.index.semantic_status()["status"], "ready")

    def test_old_vectors_are_not_used_as_current_windows(self):
        self.index.sync(self.run); self.build()
        with self.index.db:
            self.index.db.execute("UPDATE embeddings SET chunk_version=1")
            self.index.db.execute("DELETE FROM embedding_windows")
        self.assertEqual(self.index.semantic_status()["ready"], 0)
        with patch.object(idx.subprocess, "run", side_effect=fake_worker):
            self.assertEqual(self.index.semantic("query")["results"], [])
        self.assertGreater(self.build()["built"], 0)

    def test_schema_two_readonly_does_not_migrate_or_claim_ready(self):
        self.index.sync(self.run); self.build()
        legacy = self.base/"schema2.sqlite3"
        connection = sqlite3.connect(legacy)
        self.index.db.backup(connection)
        connection.execute("DROP TABLE embedding_windows")
        connection.execute("UPDATE embeddings SET chunk_version=1")
        connection.execute("PRAGMA user_version=2"); connection.commit(); connection.close()
        before = legacy.read_bytes()
        with idx.opened(legacy, readonly=True) as old:
            self.assertEqual(old.semantic_status()["ready"], 0)
            self.assertTrue(old.semantic_status()["migration_required"])
            self.assertEqual(old.semantic("query", allow_stale=True)["status"], "migration_required")
        self.assertEqual(legacy.read_bytes(), before)
        with idx.opened(legacy) as upgraded:
            self.assertEqual(upgraded.version, 3)
            upgraded.sync(self.run)
            with patch.object(idx.subprocess, "run", side_effect=fake_worker):
                self.assertGreater(upgraded.build_embeddings("fixture-python", "fixture/model", "rev")["built"], 0)
            self.assertEqual(upgraded.semantic_status()["pending"], 0)

    def test_refuted_without_refutation_is_rejected(self):
        claims = fixture.read_lines(self.run, "claims")
        claims[0].update(status="refuted", evidence=[])
        claims[0]["content_review"]["result"] = "refutes"
        fixture.write_lines(self.run, "claims", claims)
        self.assertIn("NO_REFUTATION", self.errors())

    def test_context_only_and_unread_sources_cannot_refute(self):
        for relation, access in [("context", "full"), ("supports", "full"), ("refutes", "metadata")]:
            claims = fixture.read_lines(self.run, "claims")
            claims[0].update(status="refuted", evidence=[{"source_id": "S01", "locator": "synthetic", "relation": relation, "note": "synthetic test"}])
            claims[0]["content_review"]["result"] = "refutes"
            fixture.write_lines(self.run, "claims", claims)
            sources = fixture.read_lines(self.run, "sources"); sources[0]["access"] = access
            fixture.write_lines(self.run, "sources", sources)
            self.assertIn("NO_REFUTATION", self.errors())

    def test_readable_refutation_satisfies_structural_requirement(self):
        claims = fixture.read_lines(self.run, "claims")
        claims[0].update(status="refuted", evidence=[{"source_id": "S01", "locator": "synthetic", "relation": "refutes", "note": "synthetic test"}])
        claims[0]["content_review"]["result"] = "refutes"
        fixture.write_lines(self.run, "claims", claims)
        self.assertNotIn("NO_REFUTATION", self.errors())

    def test_primary_done_with_only_secondary_sources_is_rejected(self):
        questions = fixture.read_lines(self.run, "questions")
        questions[0]["coverage"]["primary"]["source_ids"] = ["S02"]
        fixture.write_lines(self.run, "questions", questions)
        self.assertIn("PRIMARY_WITHOUT_PRIMARY_SOURCE", self.errors())

    def test_primary_limited_is_permitted_without_a_primary_source(self):
        questions = fixture.read_lines(self.run, "questions")
        questions[0]["coverage"]["primary"].update(status="limited", source_ids=["S02"], note="Primary body unavailable; secondary evidence only")
        fixture.write_lines(self.run, "questions", questions)
        self.assertNotIn("PRIMARY_WITHOUT_PRIMARY_SOURCE", self.errors())

    def test_readable_user_primary_source_is_permitted(self):
        self.assertNotIn("PRIMARY_WITHOUT_PRIMARY_SOURCE", self.errors())


if __name__ == "__main__": unittest.main()
