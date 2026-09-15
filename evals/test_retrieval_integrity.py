"""Retrieval/record acceptance regressions. All model outputs here are synthetic."""
import copy
import json
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).resolve().parent)]
import fixture
import index as idx
from index_inputs import CHUNK_VERSION, snapshot
from semantic_chunks import token_windows, validate_spans
from semantic_worker import encode_windows


class CharacterTokenizer:
    """Deliberately not a real model tokenizer; exercises hard budget contracts."""
    def __call__(self, text, add_special_tokens=True, truncation=False, **kwargs):
        if truncation:
            raise AssertionError('silent truncation is forbidden')
        return {'input_ids': [ord(c) for c in text] + ([1, 2] if add_special_tokens else [])}


class Array:
    def __init__(self, rows): self.rows = rows
    def astype(self, kind): return self
    def tolist(self): return self.rows


class Model:
    max_seq_length = 128
    tokenizer = CharacterTokenizer()
    def encode(self, texts, **kwargs):
        assert kwargs['prompt'] == ''
        assert all(len(self.tokenizer(t)['input_ids']) <= self.max_seq_length for t in texts)
        return Array([[0., 1.] if 'TAILFACT' in text else [1., 0.] for text in texts])
    def get_sentence_embedding_dimension(self): return 2


def worker(python, model, revision, texts, batch=32):
    return {'model': model, 'revision': revision, **encode_windows(Model(), texts, batch)}


class TokenWindowTests(unittest.TestCase):
    def test_multilingual_head_middle_tail_all_covered(self):
        for text in ('word ' * 250 + 'TAILFACT', '한글근거😀' * 200 + 'TAILFACT', 'x' * 1500, '', ' ' * 400):
            with self.subTest(length=len(text)):
                windows = token_windows(text, CharacterTokenizer(), 128)
                coverage = set()
                for window in windows:
                    fragment = text[window['start']:window['end']]
                    self.assertLessEqual(len(CharacterTokenizer()(fragment)['input_ids']), 128)
                    coverage.update(range(window['start'], window['end']))
                self.assertEqual(coverage, set(range(len(text))))
                self.assertEqual(windows[-1]['end'], len(text))

    def test_exact_budget_and_one_over(self):
        self.assertEqual(len(token_windows('x' * 126, CharacterTokenizer(), 128)), 1)
        self.assertGreater(len(token_windows('x' * 127, CharacterTokenizer(), 128)), 1)

    def test_invalid_budget_overlap_and_impossible_character(self):
        for limit in (None, 1, True):
            with self.assertRaises(ValueError): token_windows('x', CharacterTokenizer(), limit)
        with self.assertRaises(ValueError): token_windows('x', CharacterTokenizer(), 128, -1)
        with self.assertRaises(ValueError): token_windows('x', CharacterTokenizer(), 2)

    def test_worker_returns_separate_tail_vector_and_exact_spans(self):
        texts = ['alpha ' * 180 + 'TAILFACT', '한국어 근거 ' * 40]
        result = worker('python', 'fixture/model', 'rev', texts)
        grouped = validate_spans(result['spans'], texts, result['max_seq_length'])
        self.assertGreater(len(grouped[0]), 1)
        groups, dimension = idx.worker_windows(result, 'fixture/model', 'rev', texts)
        self.assertEqual(dimension, 2)
        self.assertEqual(groups[0][-1][1], [0., 1.])
        self.assertEqual(groups[0][-1][0]['end'], len(texts[0]))

    def test_old_worker_protocol_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'protocol'):
            idx.worker_windows({'vectors': [[1., 0.]]}, 'fixture/model', 'rev', ['text'])

    def test_gaps_missing_tail_wrong_order_and_token_overflow_rejected(self):
        texts = ['x' * 400, 'another']
        original = worker('python', 'fixture/model', 'rev', texts)
        mutations = [
            lambda r: r['spans'][0].update(start=1),
            lambda r: r['spans'][-1].update(end=3),
            lambda r: r['spans'][1].update(start=r['spans'][0]['end']+1),
            lambda r: r['spans'][0].update(token_count=129),
            lambda r: r['spans'][0].update(input=True),
            lambda r: r['spans'].reverse(),
        ]
        for mutate in mutations:
            result = copy.deepcopy(original); mutate(result)
            with self.assertRaises(ValueError): idx.worker_windows(result, 'fixture/model', 'rev', texts)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.run = fixture.build(self.base / 'run')
        self.index = idx.GlobalIndex(self.base / 'index.sqlite3'); self.addCleanup(self.index.close)

    def note(self, content):
        target = self.run / 'evidence/unique.md'; target.write_bytes(content)
        rows = fixture.read_lines(self.run, 'sources')
        rows.append({**rows[0], 'id': 'S900', 'title': 'Unique evidence note',
                     'evidence_file': 'evidence/unique.md', 'evidence_sha256': idx.sha(content)})
        fixture.write_lines(self.run, 'sources', rows)

    def build(self):
        with patch.object(idx, 'run_worker', side_effect=worker):
            return self.index.build_embeddings('python', 'fixture/model', 'rev')

    def test_evidence_only_text_is_lexically_searchable_with_source_locator(self):
        self.note('노트에만 있는 UNIQUE_NEEDLE 근거입니다.'.encode())
        self.index.sync(self.run)
        hits = self.index.find('UNIQUE_NEEDLE')
        self.assertEqual(len(hits), 1)
        self.assertEqual((hits[0]['kind'], hits[0]['object_id'], hits[0]['locator']),
                         ('evidence', 'S900', 'evidence/unique.md'))

    def test_binary_notes_are_hashed_but_unindexed_scope_is_visible(self):
        self.note(b'%PDF-1.7\x00\xff')
        self.index.sync(self.run)
        check = self.index.check(self.run)
        self.assertEqual(check['status'], 'current')
        self.assertEqual(check['unindexed_evidence'][0]['source_id'], 'S900')
        self.assertEqual(len(snapshot(self.run)['evidence_texts']), 8)
        self.index.find('anything')
        self.assertTrue(self.index.last_coverage[0]['unindexed_evidence'])

    def test_note_mutation_invalidates_current_generation(self):
        self.note(b'UNIQUE_NEEDLE')
        self.index.sync(self.run)
        (self.run / 'evidence/unique.md').write_bytes(b'changed')
        self.assertEqual(self.index.check(self.run)['status'], 'integrity_error')
        self.assertEqual(self.index.find('UNIQUE_NEEDLE'), [])

    def test_tail_only_evidence_is_ranked_by_its_own_window(self):
        self.note(('ordinary context ' * 65 + 'TAILFACT').encode())
        self.index.sync(self.run); self.build()
        with patch.object(idx, 'run_worker', side_effect=worker):
            hits = self.index.semantic('TAILFACT')['results']
        self.assertEqual(hits[0]['object_id'], 'S900')
        self.assertEqual(hits[0]['kind'], 'evidence')
        self.assertIn('TAILFACT', hits[0]['snippet'])
        self.assertGreater(hits[0]['window_start'], 128)
        self.assertGreater(hits[0]['window_count'], 1)

    def test_no_change_reuses_all_windows_without_model_execution(self):
        self.note(('context ' * 150 + 'TAILFACT').encode())
        self.index.sync(self.run); self.build()
        with patch.object(idx, 'run_worker', side_effect=AssertionError('unexpected worker')):
            result = self.index.refresh(self.run)
        self.assertEqual(result['embedding_build']['worker_calls'], 0)
        self.assertEqual(result['semantic']['status'], 'ready')

    def test_tail_vector_byte_tamper_rejected(self):
        self.note(('context ' * 150 + 'TAILFACT').encode())
        self.index.sync(self.run); self.build()
        with self.index.db:
            self.index.db.execute("UPDATE embeddings SET window_tail=? WHERE text_id=(SELECT text_id FROM texts WHERE object_id='S900' AND kind='evidence' LIMIT 1)", (struct.pack('<ff', 1., 0.),))
        with patch.object(idx, 'run_worker', side_effect=worker):
            with self.assertRaisesRegex(ValueError, 'bytes changed'): self.index.semantic('TAILFACT')

    def test_missing_tail_manifest_rejected_even_if_its_hash_is_recomputed(self):
        self.note(('context ' * 150 + 'TAILFACT').encode())
        self.index.sync(self.run); self.build()
        row = self.index.db.execute("SELECT e.* FROM embeddings e JOIN texts t USING(text_id) WHERE t.kind='evidence' AND t.object_id='S900'").fetchone()
        manifest = json.loads(row['window_manifest']); manifest['spans'][-1]['end'] -= 1
        raw = idx.canonical_json(manifest)
        with self.index.db:
            self.index.db.execute('UPDATE embeddings SET window_manifest=?,window_sha256=? WHERE text_id=?',
                                  (raw, idx.sha(raw.encode()+b'\0'+row['window_tail']), row['text_id']))
        with patch.object(idx, 'run_worker', side_effect=worker):
            with self.assertRaisesRegex(ValueError, 'full input'): self.index.semantic('TAILFACT')

    def test_legacy_vectors_are_retained_but_require_rebuild(self):
        self.index.sync(self.run); self.build()
        before = dict(self.index.db.execute('SELECT text_id,vector FROM embeddings'))
        with self.index.db:
            self.index.db.execute('UPDATE embeddings SET chunk_version=1,window_manifest=NULL,window_tail=NULL,window_sha256=NULL')
        self.assertEqual(self.index.semantic_status()['ready'], 0)
        with patch.object(idx, 'run_worker', side_effect=worker):
            self.assertEqual(self.index.semantic('TAILFACT')['results'], [])
        self.assertEqual(before, dict(self.index.db.execute('SELECT text_id,vector FROM embeddings')))
        self.assertGreater(self.build()['built'], 0)
        self.assertEqual(self.index.semantic_status()['status'], 'ready')

    def test_exclusion_removes_evidence_and_window_vectors(self):
        self.note(b'UNIQUE_NEEDLE TAILFACT')
        self.index.sync(self.run); self.build(); self.index.forget(self.run)
        self.assertEqual(self.index.find('UNIQUE_NEEDLE', allow_stale=True), [])
        self.assertEqual(self.index.db.execute('SELECT count(*) FROM embeddings').fetchone()[0], 0)


class RecordRequirementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.run = fixture.build(Path(temp.name) / 'run')

    def result(self):
        fixture.seal(self.run)
        return fixture.research.Records(self.run).validate(final=True)

    def codes(self): return {e['code'] for e in self.result()['errors']}

    def test_refuted_claim_without_refutes_relation_fails(self):
        for evidence in ([], [{'source_id': 'S05', 'locator': 'body', 'relation': 'context', 'note': 'context only'}]):
            rows = fixture.read_lines(self.run, 'claims'); rows[2]['evidence'] = evidence
            fixture.write_lines(self.run, 'claims', rows)
            self.assertIn('NO_REFUTATION', self.codes())

    def test_refuted_claim_with_readable_counterevidence_passes(self):
        self.assertTrue(self.result()['records_valid'])

    def test_refuted_claim_with_unread_counterevidence_fails(self):
        sources = fixture.read_lines(self.run, 'sources'); sources[4]['access'] = 'metadata'
        fixture.write_lines(self.run, 'sources', sources)
        self.assertTrue({'NO_REFUTATION', 'UNREAD_EVIDENCE'} <= self.codes())

    def test_primary_done_with_only_secondary_sources_fails(self):
        rows = fixture.read_lines(self.run, 'questions')
        for row in rows: row['coverage']['primary']['source_ids'] = ['S02', 'S03']
        fixture.write_lines(self.run, 'questions', rows)
        self.assertIn('PRIMARY_WITHOUT_PRIMARY_SOURCE', self.codes())

    def test_primary_limited_is_honest_and_valid(self):
        rows = fixture.read_lines(self.run, 'questions')
        for row in rows:
            row['coverage']['primary'].update(status='limited', source_ids=['S02'], note='Primary unavailable; secondary only.')
        fixture.write_lines(self.run, 'questions', rows)
        self.assertTrue(self.result()['records_valid'])

    def test_user_provided_primary_source_is_accepted(self):
        rows = fixture.read_lines(self.run, 'questions')
        for row in rows: row['coverage']['primary']['source_ids'] = ['S08']
        fixture.write_lines(self.run, 'questions', rows)
        self.assertTrue(self.result()['records_valid'])


if __name__ == '__main__': unittest.main()
