"""Observable lifecycle and incremental-index acceptance cases; local fixtures only."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).resolve().parent)]
import collect
import fixture
from semantic_fixture import with_windows
import index as idx
from index_inputs import META, metadata, snapshot, write_metadata


def worker(cmd, input, **kwargs):
    request = json.loads(input)
    return subprocess.CompletedProcess(cmd, 0, json.dumps(with_windows({'model': 'fixture/model', 'revision': 'rev', 'dimension': 2,
        'vectors': [[1., 0.] for _ in request['texts']]}, json.loads(input)["texts"])), '')


class RefreshTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.base = Path(tmp.name)
        self.run = fixture.build(self.base / 'run')
        with collect.open_corpus(self.run) as corpus:
            candidates = corpus.add_candidates('openalex', [{'provider_id': 'https://openalex.org/W600', 'doi': '10.1000/alpha', 'title': 'Alpha',
                'references': ['10.1000/beta', '10.1000/beta'], 'relations': {'is-update-of': [{'id': '10.1000/gamma'}]}}])
            corpus.ingest(b'Original document about semantic research.', url='https://example.org/doc', title='Study', candidate_id=candidates[0]['id'])
        self.path = self.base / 'store' / 'index.sqlite3'
        self.index = idx.GlobalIndex(self.path); self.addCleanup(self.index.close)

    def build(self, batch=32):
        with patch.object(idx.subprocess, 'run', side_effect=worker):
            return self.index.build_embeddings('fixture-python', 'fixture/model', 'rev', batch=batch)

    def vector_rows(self):
        return {r['text_id']: (bytes(r['vector']), r['vector_sha256']) for r in self.index.db.execute('SELECT * FROM embeddings')}

    def test_report_edit_preserves_unrelated_vectors_and_resumes(self):
        self.index.sync(self.run); self.build()
        document_ids = {r[0] for r in self.index.db.execute("SELECT text_id FROM texts WHERE kind='document'")}
        before = self.vector_rows()
        report = self.run / 'report.md'; report.write_text(report.read_text() + '\nNew conclusion and limitations.\n')
        result = self.index.refresh(self.run, 'closeout', 'off')
        after = self.vector_rows()
        self.assertEqual(result['status'], 'synced')
        self.assertTrue(all(before[k] == after[k] for k in document_ids))
        self.assertGreater(len(after), 0)
        self.assertGreater(result['semantic']['pending'], 0)
        built = self.build()
        self.assertLess(built['built'], len(before))

    def test_no_change_does_not_start_model(self):
        self.index.sync(self.run); self.build()
        before = self.vector_rows()
        with patch.object(idx.subprocess, 'run', side_effect=AssertionError('unnecessary model invocation')):
            result = self.index.refresh(self.run, 'resume')
        self.assertEqual(result['embedding_build']['worker_calls'], 0)
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual(before, self.vector_rows())

    def test_cache_events_do_not_invalidate_content(self):
        self.index.sync(self.run); self.build()
        with collect.open_corpus(self.run) as corpus: corpus.event('cache_probe', {'at': 'different'})
        with patch.object(idx.subprocess, 'run', side_effect=AssertionError('model should not run')):
            self.assertEqual(self.index.refresh(self.run)['status'], 'unchanged')

    def test_changed_locator_reuses_identical_content_vector(self):
        self.index.sync(self.run); self.build()
        with collect.open_corpus(self.run) as corpus:
            page = corpus.db.execute('SELECT * FROM pages LIMIT 1').fetchone()
            info = json.loads(page['metadata']); info['locator'] = 'section:1'
            doc = corpus.db.execute('SELECT metadata FROM documents WHERE id=?', (page['document_id'],)).fetchone()
            meta = json.loads(doc[0])
            meta['page_digest'] = collect.sha(collect.dump([{**info, 'text': page['text']}]).encode())
            corpus.db.execute('UPDATE pages SET locator=?,metadata=? WHERE document_id=?', ('section:1', collect.dump(info), page['document_id']))
            corpus.db.execute('UPDATE documents SET metadata=? WHERE id=?', (collect.dump(meta), page['document_id']))
            corpus.db.commit()
        with patch.object(idx.subprocess, 'run', side_effect=AssertionError('identical content must be reused')):
            result = self.index.refresh(self.run)
        self.assertEqual(result['text_changes']['relocated_vectors_reused'], 1)
        self.assertEqual(result['embedding_build']['built'], 0)

    def test_shared_work_survives_one_project_exclusion(self):
        self.index.sync(self.run)
        second = fixture.build(self.base / 'second')
        with collect.open_corpus(second) as corpus:
            corpus.add_candidates('crossref', [{'provider_id':'10.1000/alpha', 'doi':'10.1000/alpha', 'title':'Shared alpha', 'references':['10.1000/delta']}])
        self.index.sync(second)
        self.index.forget(self.run)
        graph = self.index.graph('10.1000/alpha', direction='out')
        self.assertEqual(len(graph['edges']), 1)
        self.assertEqual(graph['edges'][0]['target_work'], 'doi:10.1000/delta')
        self.assertTrue(self.index.db.execute("SELECT 1 FROM works WHERE work_key='doi:10.1000/alpha'").fetchone())

    def test_raw_tamper_after_index_never_returns_current(self):
        self.index.sync(self.run)
        with collect.open_corpus(self.run) as corpus:
            row = corpus.db.execute('SELECT body_path FROM documents LIMIT 1').fetchone()
        (self.run / row[0]).write_bytes(b'changed without a database write')
        self.assertEqual(self.index.check(self.run)['status'], 'integrity_error')
        result = self.index.refresh(self.run, 'before_search', 'off')
        self.assertEqual(result['status'], 'integrity_error')
        self.assertTrue(result['previous_generation_preserved'])
        self.assertEqual(self.index.find('semantic'), [])
        self.assertTrue(self.index.find('semantic', allow_stale=True))

    def test_evidence_snapshot_tamper_is_not_current(self):
        self.index.sync(self.run)
        (self.run / 'evidence/S01.md').write_text('changed evidence')
        self.assertEqual(self.index.check(self.run)['status'], 'integrity_error')

    def test_partial_save_keeps_previous_generation(self):
        self.index.sync(self.run)
        old = self.index.db.execute('SELECT fingerprint FROM runs').fetchone()[0]
        (self.run / 'claims.jsonl').write_text('{unfinished')
        result = self.index.refresh(self.run, 'resume', 'off')
        self.assertEqual(result['status'], 'invalid_input')
        self.assertEqual(old, self.index.db.execute('SELECT fingerprint FROM runs').fetchone()[0])

    def test_input_generation_changed_before_commit_rolls_back(self):
        self.index.sync(self.run)
        old = self.index.db.execute('SELECT fingerprint FROM runs').fetchone()[0]
        report = self.run / 'report.md'; report.write_text(report.read_text() + '\nfirst change\n')
        calls = 0
        def changing(root):
            nonlocal calls
            calls += 1
            if calls == 2: report.write_text(report.read_text() + '\nconcurrent change\n')
            return snapshot(root)
        with patch.object(idx, 'snapshot', side_effect=changing):
            result = self.index.refresh(self.run, 'resume', 'off')
        self.assertEqual(result['status'], 'busy')
        self.assertEqual(old, self.index.db.execute('SELECT fingerprint FROM runs').fetchone()[0])

    def test_embedding_batches_survive_failure_without_write_lock(self):
        self.index.sync(self.run)
        calls = 0
        def flaky(cmd, input, **kwargs):
            nonlocal calls
            other = sqlite3.connect(self.path, timeout=.1)
            other.execute('BEGIN IMMEDIATE'); other.rollback(); other.close()
            calls += 1
            if calls == 2: return subprocess.CompletedProcess(cmd, 1, '', 'failed')
            return worker(cmd, input, **kwargs)
        with patch.object(idx.subprocess, 'run', side_effect=flaky):
            with self.assertRaises(ValueError): self.index.build_embeddings('fixture-python', 'fixture/model', 'rev', batch=3)
        self.assertEqual(len(self.vector_rows()), 3)
        total = self.index.status()['texts']
        self.assertEqual(self.build(batch=3)['built'], total-3)

    def test_changed_during_embedding_rejects_old_vectors(self):
        self.index.sync(self.run)
        def changing(cmd, input, **kwargs):
            report = self.run / 'report.md'; report.write_text(report.read_text() + '\nchanged during inference\n')
            return worker(cmd, input, **kwargs)
        with patch.object(idx.subprocess, 'run', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'changed during embedding'):
                self.index.build_embeddings('fixture-python', 'fixture/model', 'rev')
        self.assertEqual(len(self.vector_rows()), 0)

    def test_move_keeps_ids_vectors_and_review_digest(self):
        self.index.sync(self.run); self.build()
        before = self.vector_rows()
        old_digest = fixture.research.Records(self.run).fingerprint('final')
        key = self.index.db.execute('SELECT run_key FROM runs').fetchone()[0]
        moved = self.base / 'moved'; self.run.rename(moved)
        result = self.index.relocate(self.run, moved)
        self.assertEqual(result['run_key'], key)
        self.assertEqual(before, self.vector_rows())
        self.assertEqual(old_digest, fixture.research.Records(moved).fingerprint('final'))
        self.assertTrue(self.index.find('semantic'))

    def test_copy_requires_explicit_fork(self):
        self.index.sync(self.run)
        copy = self.base / 'copy'; shutil.copytree(self.run, copy)
        self.assertEqual(self.index.refresh(copy)['status'], 'identity_conflict')
        self.assertEqual(self.index.status()['runs'], 1)
        self.index.fork(copy)
        self.assertEqual(self.index.refresh(copy, semantic='off')['status'], 'synced')
        self.assertEqual(self.index.status()['runs'], 2)

    def test_temporarily_missing_is_not_deleted(self):
        self.index.sync(self.run)
        self.run.rename(self.base / 'unmounted')
        self.assertEqual(self.index.runs()[0]['status'], 'missing')
        self.assertEqual(self.index.find('semantic'), [])
        self.assertEqual(self.index.status()['runs'], 1)

    def test_explicit_forget_of_missing_run_blocks_old_copy(self):
        self.index.sync(self.run); self.build()
        saved = self.base / 'saved'; self.run.rename(saved)
        result = self.index.forget(self.run)
        self.assertTrue(result['removed'])
        self.assertEqual(self.index.status()['runs'], 0)
        self.assertEqual(self.index.find('semantic', allow_stale=True), [])
        saved.rename(self.run)
        self.assertEqual(self.index.refresh(self.run)['status'], 'excluded')

    def test_semantic_query_rechecks_source_after_model_execution(self):
        self.index.sync(self.run); self.build()
        def changing(cmd, input, **kwargs):
            report = self.run / 'report.md'
            report.write_text(report.read_text() + '\nchanged during query embedding\n')
            return worker(cmd, input, **kwargs)
        with patch.object(idx.subprocess, 'run', side_effect=changing):
            result = self.index.semantic('old report')
        self.assertEqual(result['results'], [])
        self.assertEqual(result['coverage'][0]['status'], 'stale')

    def test_scope_removes_only_its_contributions_and_blocks_restoration(self):
        self.index.sync(self.run); self.build()
        second = fixture.build(self.base / 'second'); self.index.sync(second)
        meta = metadata(self.run)
        self.index.set_scope(self.run, 'off')
        self.assertEqual(self.index.status()['runs'], 1)
        self.assertEqual(self.index.status()['documents'], 0)
        self.assertEqual(self.index.find('semantic', allow_stale=True), [])
        # Even an old copy of the policy file cannot silently re-enable global retention.
        write_metadata(self.run, meta, replace=True)
        self.assertEqual(self.index.refresh(self.run)['status'], 'excluded')
        self.assertTrue((self.run / 'report.md').exists())
        self.assertTrue(self.index.set_scope(self.run, 'global')['status'] in {'synced', 'unchanged'})

    def test_readonly_commands_do_not_create_or_chmod_anything(self):
        missing = self.base / 'untouched' / 'missing.sqlite3'
        for command in (['status'], ['runs'], ['check', '--run', str(self.run)]):
            with redirect_stdout(io.StringIO()): self.assertEqual(idx.main(['--index', str(missing), *command]), 0)
        self.assertFalse(missing.parent.exists())
        self.index.sync(self.run)
        self.path.chmod(0o640); self.path.parent.chmod(0o750)
        before = self.path.read_bytes()
        with redirect_stdout(io.StringIO()): idx.main(['--index', str(self.path), 'status'])
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o750)

    def test_duplicate_citations_are_counted_and_preserved(self):
        result = self.index.sync(self.run)
        audit = result['graph_coverage'][0]
        self.assertEqual((audit['expected'], audit['indexed'], audit['duplicates']), (3, 2, 1))
        payload = self.index.db.execute('SELECT payload FROM observations').fetchone()[0]
        self.assertEqual(json.loads(payload)['references'].count('10.1000/beta'), 2)

    def test_doi_correction_rebuilds_aliases_from_current_observations(self):
        self.index.sync(self.run)
        with collect.open_corpus(self.run) as corpus:
            corpus.add_candidates('openalex', [{'provider_id': 'https://openalex.org/W600', 'doi': '10.1000/corrected', 'title': 'Corrected', 'references': []}])
        self.index.sync(self.run)
        alias = self.index.db.execute("SELECT work_key FROM aliases WHERE alias='openalex:W600'").fetchone()[0]
        self.assertEqual(alias, 'doi:10.1000/corrected')
        self.assertFalse(self.index.db.execute("SELECT 1 FROM works WHERE work_key='doi:10.1000/alpha'").fetchone())
        self.assertEqual(self.index.db.execute('SELECT work_key FROM documents').fetchone()[0], alias)

    def test_unit_vector_byte_tamper_is_detected(self):
        self.index.sync(self.run); self.build()
        with self.index.db: self.index.db.execute('UPDATE embeddings SET vector=?', (struct.pack('<ff', 0., 1.),))
        with patch.object(idx.subprocess, 'run', side_effect=worker):
            with self.assertRaisesRegex(ValueError, 'bytes changed'): self.index.semantic('query')

    def test_required_semantics_without_setup_is_explicit(self):
        with patch.object(idx.subprocess, 'run', side_effect=AssertionError('must not install')):
            result = self.index.refresh(self.run, semantic='required')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['semantic_error'], 'not_configured')
        self.assertTrue(self.index.find('semantic'))

    def test_schema_one_upgrade_preserves_rows_and_vectors(self):
        self.index.sync(self.run); self.build()
        legacy = self.base / 'legacy.sqlite3'
        old = sqlite3.connect(legacy); old.executescript(idx.SCHEMA)
        tables = ['runs','records','record_edges','works','aliases','observations','documents','texts','text_search','embeddings','citation_edges','sync_audits','settings']
        for table in tables:
            count = 7 if table == 'embeddings' else len(old.execute('PRAGMA table_info('+table+')').fetchall())
            rows = [tuple(r)[:count] for r in self.index.db.execute('SELECT * FROM '+table)]
            old.executemany('INSERT INTO '+table+' VALUES('+','.join('?' for _ in range(count))+')', rows)
        old.execute('PRAGMA user_version=1'); old.commit(); old.close()
        digest = fixture.research.Records(self.run).fingerprint('final')
        migrated = idx.GlobalIndex(legacy)
        try:
            self.assertEqual(migrated.version, 3)
            self.assertEqual(migrated.status()['semantic_vectors'], 0)
            self.assertGreater(migrated.status()['semantic']['pending'], 0)
            before = {r[0]: r[1] for r in migrated.db.execute('SELECT text_id,vector FROM embeddings')}
            migrated.sync(self.run)
            self.assertEqual(before, {r[0]: r[1] for r in migrated.db.execute('SELECT text_id,vector FROM embeddings')})
            self.assertEqual(digest, fixture.research.Records(self.run).fingerprint('final'))
        finally: migrated.close()


if __name__ == '__main__': unittest.main()
