"""Offline regressions for acquisition boundaries and persistence."""
from pathlib import Path
import json
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect
import research


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        query = self.base / "query.md"; query.write_text("Synthetic collector test")
        self.root = self.base / "run"; research.initialize(self.root, query, "explanation")
        (self.root / "questions.jsonl").write_text('{"id":"Q01"}\n')
        self.c = collect.Corpus(self.root); self.addCleanup(self.c.db.close)

    def ingest(self, **extra):
        return self.c.ingest(b"Page evidence alpha beta", url="https://example.org/source", title="Fixture", **extra)

    def test_acquisition_does_not_register_or_review(self):
        result = self.ingest()
        self.assertFalse(result["read_verified"])
        self.assertEqual((self.root / "sources.jsonl").read_text(), "")
        self.assertEqual((self.root / "claims.jsonl").read_text(), "")

    def test_reimport_is_idempotent_and_find_preserves_locator(self):
        first = self.ingest(); second = self.ingest()
        self.assertEqual(first["document_id"], second["document_id"])
        found = self.c.find("alpha beta")["results"]
        self.assertEqual(len(found), 1); self.assertEqual(found[0]["locator"], "document")

    def test_raw_tampering_blocks_read_and_find(self):
        did = self.ingest()["document_id"]
        doc = self.c.document(did)
        (self.root / doc["body_path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "changed"): self.c.read(did)
        with self.assertRaisesRegex(ValueError, "changed"): self.c.find("alpha")

    def test_different_provider_observations_share_work_key_only(self):
        a = self.c.add_candidates("crossref", [{"provider_id":"10.1234/x", "doi":"10.1234/x"}])[0]
        b = self.c.add_candidates("openalex", [{"provider_id":"W123", "doi":"10.1234/x"}])[0]
        self.assertNotEqual(a["id"], b["id"]); self.assertEqual(a["work_key"], b["work_key"])

    def test_extracted_page_tampering_blocks_read(self):
        did = self.ingest()["document_id"]
        self.c.db.execute("UPDATE pages SET text='changed' WHERE document_id=?", (did,))
        with self.assertRaisesRegex(ValueError, "pages changed"): self.c.read(did)

    def test_http_cache_uses_preserved_bytes(self):
        with patch.object(collect, "http_get", return_value=(b"original", "text/plain", "https://example.org/a")) as get:
            self.assertFalse(self.c.get("https://example.org/a")[3])
            self.assertTrue(self.c.get("https://example.org/a")[3])
            self.assertEqual(get.call_count, 1)

    def test_refresh_performs_new_request(self):
        with patch.object(collect, "http_get", return_value=(b"original", "text/plain", "https://example.org/a")) as get:
            self.c.get("https://example.org/a"); self.c.get("https://example.org/a", refresh=True)
            self.assertEqual(get.call_count, 2)

    def test_failure_is_not_cached_as_absence(self):
        with patch.object(collect, "http_get", side_effect=collect.AccessError("rate_limited", "HTTP 429")):
            with self.assertRaises(collect.AccessError): self.c.get("https://example.org/a")
        self.assertEqual(self.c.db.execute("SELECT count(*) FROM requests").fetchone()[0], 0)

    def test_failed_resolver_stays_incomplete(self):
        with patch.object(collect, "settings", return_value={"unpaywall_email":"test@example.org"}), \
             patch.object(self.c, "json_get", side_effect=collect.AccessError("rate_limited", "429")):
            result = collect.resolve(self.c, "https://doi.org/10.1234/X")
        self.assertEqual(result["status"], "lookup_incomplete")
        self.assertEqual(result["attempts"][0]["status"], "rate_limited")

    def test_metadata_cannot_be_registered_as_fulltext(self):
        did = self.ingest(content_level="metadata")["document_id"]
        note = self.base / "note.md"; note.write_text("Read fixture")
        with self.assertRaisesRegex(ValueError, "cannot"):
            collect.register(self.c, did, "S01", note, "document", "fixture", "fixture", ["Q01"])

    def test_nonexistent_locator_cannot_be_registered(self):
        did = self.ingest()["document_id"]
        note = self.base / "note.md"; note.write_text("A note")
        with self.assertRaisesRegex(ValueError, "existing"):
            collect.register(self.c, did, "S01", note, "page:999", "fixture", "fixture", ["Q01"])

    def test_resolution_url_must_match_recorded_candidate(self):
        eid = self.c.event("resolve", {"candidates":[{"url":"https://example.org/a"}]})
        with self.assertRaisesRegex(ValueError, "not a candidate"):
            collect.fetch_document(self.c,"https://example.org/b","fixture",resolution_id=eid)

    def test_register_requires_known_question_and_preserves_claims(self):
        did = self.ingest()["document_id"]
        note = self.base / "note.md"; note.write_text("Observed alpha beta in document. Synthetic fixture only.")
        with self.assertRaisesRegex(ValueError, "question"):
            collect.register(self.c, did, "S01", note, "document", "fixture", "fixture", ["MISSING"])
        result = collect.register(self.c, did, "S01", note, "document", "fixture", "fixture", ["Q01"])
        self.assertFalse(result["claims_modified"])
        self.assertEqual((self.root / "claims.jsonl").read_text(), "")
        source = json.loads((self.root / "sources.jsonl").read_text())
        self.assertEqual(source["access"], "partial")
        self.assertEqual(collect.sha((self.root / source["evidence_file"]).read_bytes()), source["evidence_sha256"])
        with self.assertRaisesRegex(ValueError, "already"):
            collect.register(self.c, did, "S01", note, "document", "fixture", "fixture", ["Q01"])

    def test_public_url_rejects_loopback_and_file(self):
        with self.assertRaises(ValueError): collect.public_url("file:///tmp/x")
        with patch.object(socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1",443))]):
            with self.assertRaises(ValueError): collect.public_url("https://example.org/")

    def test_redaction_does_not_disclose_email_or_key(self):
        result = collect.redact("https://example.org/a?email=private%40example.org&api_key=secret&q=paper")
        self.assertNotIn("private", result); self.assertNotIn("secret", result); self.assertIn("paper", result)

    def test_missing_pdf_dependency_is_explicit(self):
        with patch.object(collect, "runtime", return_value={"pdf_python":None}):
            with self.assertRaises(collect.AccessError) as caught:
                collect.extract(b"%PDF-fake", "application/pdf", self.base / "raw")
        self.assertEqual(caught.exception.status, "dependency_missing")

    def test_html_mislabeled_pdf_is_not_ingested_as_pdf(self):
        with self.assertRaises(collect.AccessError):
            collect.extract(b"<html>Access denied</html>", "application/pdf", self.base / "raw")

    def test_crossref_cursor_is_exposed(self):
        payload = {"message":{"items":[{"DOI":"10.1234/X", "title":["Fixture"]}], "next-cursor":"next", "total-results":9}}
        with patch.object(self.c, "json_get", return_value=(payload,False)):
            result = collect.search(self.c, "crossref", "fixture", size=1)
        self.assertEqual(result["next_cursor"], "next")
        self.assertEqual(result["items"][0]["doi"], "10.1234/x")

    def test_semantic_is_not_silently_replaced_with_keyword_search(self):
        with self.assertRaisesRegex(ValueError,"semantic"):
            collect.search(self.c,"crossref","fixture",semantic=True)


if __name__ == "__main__": unittest.main()
