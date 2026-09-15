"""One-time exact, hash-checked application of reviewed changes; removed after CI."""
from pathlib import Path
import hashlib

CHANGES = [('README.md',
  '47c80cebc5200075b4519449095a73a8591adec6386365b50f20204a13874ac9',
  '76b1e4b3bb8ff1d9d248ede894d8db19d3918f28bcde90e77ef994f1d884899e',
  [(52,
    52,
    '1.5.0은 실제 토크나이저 기반 창 분할, 창별 의미 검색, UTF-8 근거 노트 본문 색인을 추가합니다. `refuted`에는 읽을 수 있는 반박 근거, `primary=done`에는 읽을 수 있는 '
    '원자료 연결이 필요합니다. 비텍스트 근거의 검색 누락은 `coverage.unindexed_evidence`에 표시합니다.\n'
    '\n'
    '이전 전에 원본 실행과 DB를 백업하세요. 기존 DB는 첫 쓰기 시 스키마 3으로 이전하며 구벡터 바이트는 보존하지만 검색에는 재사용하지 않습니다. 관련 실행의 `refresh --semantic '
    'off` 후 `semantic-build` 또는 `refresh --semantic required`로 토큰 창 벡터를 재계산하세요. 이미 구성된 모델만 사용하며 자동 다운로드는 하지 않습니다.\n'
    '\n'
    '\n'),
   (60,
    61,
    '1.3.0/1.4.0 DB의 스키마 3 이전과 구벡터 재계산 조건은 위 설명과 `references/global-index.md`를 따릅니다. 이전 전 원본과 DB 사본을 보관하고, 복구 시 스킬과 DB '
    '버전을 함께 되돌리세요. `local/off` 정책은 전역 색인 기여를 제거하며 원본 연구를 삭제하지 않습니다. 별도 백업에는 같은 보존 결정을 적용해야 합니다.\n'),
   (65,
    65,
    '\n'
    '### 검색 검증의 범위\n'
    '\n'
    '기본 회귀시험은 네트워크·모델 없이 기록, 토큰 창 계약, 근거 노트 검색, 창별 점수 처리, 증분 갱신 및 보존 정책을 검사합니다. 가짜 벡터 시험을 실제 모델의 검색 정확도라고 제시하지 않습니다.\n'
    '\n'
    '실제 고정 리비전 토크나이저의 한글·영문·혼합·공백·긴 문자열 검사는 선택적으로 실행합니다. 캐시만 쓰는 기본 실행은 `python3 evals/check_tokenizer.py`, 토크나이저 파일 '
    '다운로드를 허용하는 실행은 `python3 evals/check_tokenizer.py --allow-download`입니다. Transformers가 있는 별도 환경이 필요하며 모델 가중치나 외부 추론 '
    'API는 사용하지 않습니다. GitHub CI는 이 토크나이저 검사와 Python 3.10·3.12·3.14의 표준 라이브러리 회귀시험을 분리합니다. 실제 모델 검색 순위와 에이전트 연구 행동의 우수성은 '
    '별도의 평가가 필요합니다.\n')]),
 ('SKILL.md',
  '2ad755c23162384a7df50030d031700ca8a53a4eb64e9cc21cdab003c005286e',
  '2b1c77e72bdecd5e726c244072f25618726cf79a7fcc785d0e0aa7c802f732ab',
  [(4, 5, '  version: "1.5.0"\n')]),
 ('evals/fixture.py',
  '37769c48a0d22244d7b264abd0227d4638b3be21f880226f57806431ba08d68b',
  '5db878ad6c3a2fe7e92b27a7219f808de1c1be27b2ceefcb1e40b65c5c279d45',
  [(144,
    144,
    '\n'
    '\n'
    'def window_manifest(texts):\n'
    '    """Synthetic one-window protocol for plumbing tests; not tokenizer evidence."""\n'
    '    from semantic_chunks import WINDOW_VERSION\n'
    '    return {"window_version": WINDOW_VERSION, "max_seq_length": 128,\n'
    '            "spans": [{"input": i, "start": 0, "end": len(text), "token_count": 1}\n'
    '                      for i, text in enumerate(texts)]}\n')]),
 ('evals/rubric.md',
  '4bbe8ca7491c687f70d97432d38572259303c7fc72c3a3f7c53cc9c5849cfa1c',
  '655ba01c54b3258a281e1bbdfb45e1f51643971b0f27907d0347ccc588f89924',
  [(30,
    31,
    '1.1.0의 문헌 검색·실증 방법은 `cross-corpus-versions`, `retrieval-gap-without-cap`, `experimental-comparison-contract`, '
    '`experimental-negative-vs-error`, `experimental-lineage` 사례로 별도 행동 점검한다. 이 사례들은 평가 지침이며 기본 자동 회귀시험에 포함된다는 뜻은 아니다. '
    '실제 수행한 결과와 미수행 범위를 구분해 기록한다.\n'
    '\n'
    '## 검색 보완 회귀시험\n'
    '\n'
    '`test_retrieval_integrity.py`는 읽기 가능한 반박/원자료 요건, 근거 노트 전용 검색, 바이너리 누락 공개, 전체 토큰 창 커버리지, 뒷부분 창 점수, 창 변조 탐지, 구벡터 '
    '재계산을 검사한다. CharacterTokenizer와 벡터는 가상 시험 장치이며 실제 언어 검색 성능 자료가 아니다. `check_tokenizer.py`는 별도 환경의 실제 고정 리비전 토크나이저로 '
    '잘림 없는 창과 전체 입력 범위를 검사하며, 기본적으로 다운로드하지 않는다. 실행하지 않은 모델 검색 순위·에이전트 행동 평가는 미수행으로 남긴다.\n')]),
 ('evals/test_index.py',
  '9695e7be3d46aaebb768843e284effe7b2c67a818df7031a8229aa4d5dc7c725',
  '86a4a441d57aade0408a86f4fcb66c8d68dfe98868614d4cab0a4906a56835c7',
  [(175,
    176,
    '            return subprocess.CompletedProcess(cmd, 0, '
    'json.dumps({**fixture.window_manifest(json.loads(input)["texts"]), "model": "fixture/model", "revision": '
    '"revision", "dimension": 2, "vectors": vectors}), "")\n'),
   (194,
    195,
    '            return subprocess.CompletedProcess(cmd, 0, '
    'json.dumps({**fixture.window_manifest(json.loads(input)["texts"]), "model": "fixture/model", "revision": '
    '"revision", "dimension": 1, "vectors": [[1.0] for _ in json.loads(input)["texts"]]}), "")\n'),
   (204,
    205,
    '            return subprocess.CompletedProcess(cmd, 0, '
    'json.dumps({**fixture.window_manifest(json.loads(input)["texts"]), "model": "wrong", "revision": "revision", '
    '"dimension": 1, "vectors": [[1.0] for _ in json.loads(input)["texts"]]}), "")\n'),
   (208,
    209,
    '            return subprocess.CompletedProcess(cmd, 0, '
    'json.dumps({**fixture.window_manifest(json.loads(input)["texts"]), "model": "fixture/model", "revision": '
    '"revision", "dimension": 1, "vectors": [[2.0] for _ in json.loads(input)["texts"]]}), "")\n')]),
 ('evals/test_refresh.py',
  'b57a13612082c8f152bceb281ebcf92b98d7206aa3100293645475c9120e9d9f',
  '2c6e11d12b1c358ef1973ffe0052a2873f4f7969249ba63a933e3eae5b53cd4f',
  [(25,
    26,
    "    return subprocess.CompletedProcess(cmd, 0, json.dumps({**fixture.window_manifest(request['texts']), 'model': "
    "'fixture/model', 'revision': 'rev', 'dimension': 2,\n"),
   (289,
    291,
    '            self.assertEqual(migrated.version, 3)\n'
    "            self.assertEqual(migrated.status()['semantic_vectors'], 0)  # Legacy vectors require token-window "
    'rebuild.\n')]),
 ('references/evidence-contract.md',
  '8ab5888b1cd37a16fd75e049905b2fdda7a9a47b21c440b463c0494e78643130',
  '678d3bd3e931a822e38044b0551b6d8f70a363ad6dedf35493b47f971ebd5c0c',
  [(34,
    35,
    '`primary=done`은 읽을 수 있는 `kind=primary` 출처를 연결해야 한다. 사용자 제공 원본도 원자료로 사용할 수 있다. 원자료 접근이 실패하면 `primary=limited`로 '
    '표시한다. `breadth`·`primary`를 해당 없음으로 처리하지 않는다. 다른 관점의 `not_applicable`은 왜 해당 검토가 판단에 영향을 주지 않는지 구체적으로 설명한 경우만 '
    '사용한다.\n'),
   (83,
    83,
    '`refuted`는 읽을 수 있는 `relation=refutes` 근거가 필요하다. 직접 계산·실험·논리적 반증도 실제 실행 결과나 증명 노트를 출처로 연결한다. 근거 부족은 `refuted`가 아니라 '
    '`unresolved`로 구분한다. 이는 연결 검사이며 반증 내용의 타당성은 별도로 검토한다.\n'
    '\n')]),
 ('references/global-index.md',
  '64853c9c05bab5a425a5490bc821cab6e21cdea134cf2ddca0c3ddd94a6d2a19',
  'a642001dd1c9c7d89dac2689df88f1634985a7602278ded879d205992c09cc17',
  [(88,
    89,
    '1.3.0/1.4.0 DB는 쓰기 명령을 실행할 때 스키마 3으로 이전한다. 기존 실행 키와 벡터 바이트를 보존하되, 토큰 창 정보가 없는 구벡터는 `pending`이며 검색에 사용하지 않는다. '
    '`refresh --semantic required` 또는 `semantic-build`로 재계산한다. 최초 이전에는 관련 실행의 `refresh --semantic off`를 먼저 수행해 근거 노트 '
    '본문도 반영한다. 1.3.0 실행 ID는 첫 `refresh`에서 연결한다. 읽기 전용 명령은 이전하지 않는다. 원본 실행과 DB 백업을 먼저 보관하고 복사본에서 검증한다. 구버전으로 되돌릴 때는 해당 '
    '스킬과 이전에 백업한 동일 버전 DB를 함께 복구한다.\n'),
   (93,
    93,
    '\n'
    '## 1.5.0 검색 범위와 토큰 창\n'
    '\n'
    '단어 색인의 1,400자 묶음은 저장·위치 추적용이며 모델의 입력 단위가 아니다. 의미 worker는 실제 모델 토크나이저로 특수 토큰까지 세고 `max_seq_length` 이내의 겹치는 창으로 '
    '재분할한다. 모든 입력 위치가 마지막 문자까지 덮였는지 검사하고 창별 벡터를 따로 보존한다. 검색은 평균 벡터 대신 질의 창과 문서 창 사이의 최대 유사도로 부모 묶음을 정렬하며, 일치한 창의 본문과 '
    '`window_start`, `window_end`, `window_count`를 반환한다. 오프셋은 해당 `text_id`의 저장 문자열 기준이다. 여러 주제를 섞은 긴 질의는 어느 한 창과만 가까워도 '
    '상위에 올 수 있으므로 질문별 질의와 원문 재확인이 필요하다. 이 점수는 사실 지지·반박 판정이 아니다.\n'
    '\n'
    '청크/worker 프로토콜은 버전 2다. 모델 리비전과 분할 버전이 다른 벡터는 재사용하지 않는다. 첫 벡터는 기존 BLOB, 나머지는 추가 BLOB에 보존하고 창 경계·벡터 지문·차원·정규화·입력 전체 '
    '범위를 검사한다. 변경 없는 갱신은 모델을 호출하지 않으며 배치 단위 저장·동일 내용 재사용·제외 시 삭제는 유지한다.\n'
    '\n'
    '`sources.jsonl`에 연결된 UTF-8 근거 노트는 `kind=evidence`, 출처 ID, 노트 상대 경로와 함께 단어·의미 검색 대상에 포함한다. PDF·비텍스트 바이트는 해시만 확인하며 '
    '자동으로 읽었다고 표시하지 않는다. 검색 `coverage`의 `unindexed_evidence`에 미반영 출처와 사유를 표시하므로 `collect.py`로 추출하거나 UTF-8 근거 노트를 연결한다. '
    '해시 검사와 검색 반영은 정독·검토를 대체하지 않는다.\n')]),
 ('scripts/collect.py',
  '9d5b1c7965fe9a0d93693a8010c33de23ab4e31cf20df980347ffa04aeb4c576',
  'd08d27d88187aedd304386ac2a76a9cfab39a0f42de97f49bebed40b53334e5f',
  [(30, 31, 'VERSION = "1.5.0"\n')]),
 ('scripts/index.py',
  '15f7226861f92d1fabeeae80e79b81f50f72719884fb8fbaa5564c6cc5d60a5c',
  '566450368048b29fa3808c7b832e761ec9223209a7cc8dfa8596195d8a3ea562',
  [(23, 23, 'from semantic_chunks import WINDOW_VERSION, validate_spans, pack_tail, unpack_tail\n'),
   (24, 25, 'VERSION = "1.5.0"\n'),
   (105, 106, '        if self.version not in {0, 1, 2, 3}:\n'),
   (131,
    133,
    '            for column, declaration in (("window_manifest", "TEXT"), ("window_tail", "BLOB"), ("window_sha256", '
    '"TEXT")):\n'
    '                if column not in columns:\n'
    '                    self.db.execute("ALTER TABLE embeddings ADD COLUMN " + column + " " + declaration)\n'
    '            self.db.execute("PRAGMA user_version=3")\n'
    '        self.version = 3\n'),
   (178,
    178,
    '            if self.version >= 3: sql += " AND e.window_manifest IS NOT NULL"\n'
    '            else: sql += " AND 0"\n'),
   (197, 197, '                      "unindexed_evidence": snap["unindexed_evidence"],\n'),
   (248,
    248,
    '        for note in snap["evidence_texts"]:\n'
    '            add("evidence", note["source_id"], note["path"], note["text"])\n'),
   (275,
    275,
    '            if row["chunk_version"] == CHUNK_VERSION:\n'
    '                stored_windows(row, old[row["text_id"]]["text"])\n'),
   (291,
    292,
    '                self.db.execute("INSERT OR IGNORE INTO embeddings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (tid, '
    'vector["backend"], vector["model"], vector["revision"], vector["dimension"], vector["vector"], row[7], '
    'vector["vector_sha256"], CHUNK_VERSION, vector["window_manifest"], vector["window_tail"], '
    'vector["window_sha256"]))\n'),
   (474,
    475,
    '        rows = self.db.execute("SELECT t.* FROM texts t LEFT JOIN embeddings e ON e.text_id=t.text_id AND '
    "e.backend='sentence-transformers' AND e.model=? AND e.revision=? AND e.chunk_version=? WHERE (e.text_id IS NULL "
    'OR e.text_sha256!=t.text_sha256 OR e.window_manifest IS NULL) AND t.run_key IN (" + ",".join("?" for _ in '
    'allowed) + ") ORDER BY t.text_id", [model, revision, CHUNK_VERSION, *sorted(allowed)]).fetchall()\n'),
   (476,
    477,
    '        for row in self.db.execute("SELECT e.*,t.text FROM embeddings e JOIN texts t USING(text_id) WHERE '
    'e.model=? AND e.revision=? AND t.run_key IN (" + ",".join("?" for _ in allowed) + ")", [model, revision, '
    '*sorted(allowed)]):\n'),
   (478,
    478,
    '            if row["chunk_version"] == CHUNK_VERSION:\n                stored_windows(row, row["text"])\n'),
   (487,
    488,
    '                groups, dimension = worker_windows(result, model, revision, [r["text"] for r in selected], '
    'dimension)\n'),
   (494, 495, '                    for row, windows in zip(selected, groups):\n'),
   (498,
    500,
    '                        blob = struct.pack("<" + "f" * dimension, *windows[0][1])\n'
    '                        manifest = canonical_json({"version": WINDOW_VERSION, "maximum": '
    'result["max_seq_length"],\n'
    '                                                   "spans": [span for span, _ in windows]})\n'
    '                        tail = pack_tail([vector for _, vector in windows], dimension)\n'
    '                        self.db.execute("INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", '
    '(row["text_id"], "sentence-transformers", model, revision, dimension, blob, row["text_sha256"], sha(blob), '
    'CHUNK_VERSION, manifest, tail, sha(manifest.encode() + b"\\0" + tail)))\n'),
   (522,
    523,
    '        groups, dimension = worker_windows(result, config["model"], config["revision"], [query], '
    'config["dimension"])\n'),
   (525, 526, '        queries, scores = [v for _, v in groups[0]], []\n'),
   (529,
    533,
    '            if self.version < 3 or item["chunk_version"] != CHUNK_VERSION: continue\n'
    '            windows = stored_windows(item, item["text"], dimension)\n'
    '            score, best = max((max(sum(a*b for a,b in zip(q, vector)) for q in queries), i)\n'
    '                              for i, (_, vector) in enumerate(windows))\n'
    '            span = windows[best][0]\n'
    '            scores.append({"text_id": item["text_id"], "run_key": item["run_key"], "kind": item["kind"], '
    '"object_id": item["object_id"], "locator": item["locator"], "score": max(-1., min(1., score)), "snippet": '
    'item["text"][span["start"]:span["end"]][:500],\n'
    '                           "window_start": span["start"], "window_end": span["end"], "window_count": '
    'len(windows)})\n'),
   (599,
    599,
    'def worker_windows(result, model, revision, texts, dimension=None):\n'
    '    if not isinstance(result, dict) or result.get("window_version") != WINDOW_VERSION:\n'
    '        raise IndexProblem("semantic_error", "semantic worker window protocol mismatch; rebuild with the current '
    'worker")\n'
    '    try:\n'
    '        spans = result.get("spans")\n'
    '        groups = validate_spans(spans, texts, result.get("max_seq_length"))\n'
    '        vectors, dimension = validate_vectors(result, model, revision, len(spans), dimension)\n'
    '        output, offset = [], 0\n'
    '        for rows in groups:\n'
    '            output.append([({**span, "input": 0}, vector) for span, vector in zip(rows, '
    'vectors[offset:offset+len(rows)])])\n'
    '            offset += len(rows)\n'
    '        return output, dimension\n'
    '    except ValueError as exc:\n'
    '        raise IndexProblem("semantic_error", str(exc)) from exc\n'
    '\n'
    '\n'
    'def stored_windows(row, text, dimension=None):\n'
    '    first = validate_blob(row, dimension)\n'
    '    try:\n'
    '        manifest, tail = row["window_manifest"], row["window_tail"]\n'
    '        if not isinstance(manifest, str) or not isinstance(tail, bytes):\n'
    '            raise ValueError("semantic window data missing; rebuild required")\n'
    '        if sha(manifest.encode() + b"\\0" + tail) != row["window_sha256"]:\n'
    '            raise ValueError("stored semantic window bytes changed")\n'
    '        meta = strict_json(manifest)\n'
    '        if not isinstance(meta, dict) or meta.get("version") != WINDOW_VERSION:\n'
    '            raise ValueError("semantic window version mismatch")\n'
    '        spans = validate_spans(meta.get("spans"), [text], meta.get("maximum"))[0]\n'
    '        vectors = [first] + unpack_tail(tail, len(spans)-1, row["dimension"])\n'
    '        return list(zip(spans, vectors))\n'
    '    except (ValueError, TypeError, KeyError) as exc:\n'
    '        raise IndexProblem("integrity_error", str(exc)) from exc\n'
    '\n'
    '\n'),
   (623, 624, '    _, dimension = worker_windows(strict_json(proc.stdout), model, revision, ["연구 색인 준비"])\n')]),
 ('scripts/index_inputs.py',
  'b461d1d8814fe683d93db12a79b4c69c605abc3b423ba18097ee713d23452bf0',
  '32348acb2361c4ee4938965ba83544e5d8c9e31bd8ca04f8c521c5887314b9c8',
  [(13, 15, 'INDEX_VERSION = 3\nCHUNK_VERSION = 2\n'),
   (123, 124, '    evidence, evidence_texts, unindexed_evidence = {}, [], []\n'),
   (127, 128, '            blob = path.read_bytes()\n            digest = sha(blob)\n'),
   (131,
    131,
    '            try:\n'
    '                text = blob.decode("utf-8-sig")\n'
    '                if "\\x00" in text or blob.startswith(b"%PDF-"):\n'
    '                    raise ValueError("binary evidence")\n'
    '                evidence_texts.append({"source_id": row["id"], "path": row["evidence_file"], "text": text})\n'
    '            except (UnicodeError, ValueError):\n'
    '                unindexed_evidence.append({"source_id": row["id"], "path": row["evidence_file"],\n'
    '                                           "reason": "non_text_evidence; extract with collect.py or add a UTF-8 '
    'note"})\n'),
   (172,
    173,
    '               "records": records, "evidence": evidence, "evidence_texts": evidence_texts,\n'
    '               "unindexed_evidence": unindexed_evidence, "candidates": candidates, "documents": documents}\n')]),
 ('scripts/research.py',
  '80d88448d68c7704d0fcfa881d5e862d894abb2953b8259baaae1a7cecc4e3d8',
  '4cf60a163438016653bf6afa5de321244a578e97e887e1dcace9acc1c64855e0',
  [(253, 254, '            supports, refutes = [], []\n'),
   (265,
    265,
    '                elif binding.get("relation") == "refutes":\n                    refutes.append(source)\n'),
   (267,
    267,
    '            if claim.get("status") == "refuted" and not refutes:\n'
    '                self.error("NO_REFUTATION", key, "refuted claims need readable refuting evidence")\n'),
   (319,
    319,
    '                if lens == "primary" and cell.get("status") == "done":\n'
    '                    if not any(sidx.get(sid, {}).get("kind") == "primary" and\n'
    '                               sidx.get(sid, {}).get("access") in {"full", "partial"} for sid in sources):\n'
    '                        self.error("PRIMARY_WITHOUT_PRIMARY_SOURCE", key, "primary=done needs a readable primary '
    'source; otherwise use limited")\n')]),
 ('scripts/semantic_worker.py',
  '81040bee3d082e7566d5434cf758e17bf14f52c97fb6edea0e4c0b8aa514b504',
  '1594995fb7c70676d503887d9e2ac5e37a63227a6e9f34e915c7ab7e0e53af00',
  [(1, 2, '"""Local token-window embeddings. JSON in/out; no remote inference API."""\n'),
   (7,
    7,
    '\n'
    'from semantic_chunks import WINDOW_VERSION, token_windows, validate_spans\n'
    '\n'
    '\n'
    'def encode_windows(model, texts, batch_size):\n'
    '    maximum = model.max_seq_length\n'
    '    if type(maximum) is not int:\n'
    '        raise ValueError("model does not expose a finite token limit")\n'
    '    spans, windows = [], []\n'
    '    for idx, text in enumerate(texts):\n'
    '        for span in token_windows(text, model.tokenizer, maximum):\n'
    '            spans.append({"input": idx, **span})\n'
    '            windows.append(text[span["start"]:span["end"]])\n'
    '    validate_spans(spans, texts, maximum)\n'
    '    # Explicit empty prompt prevents a saved default prompt changing the budget.\n'
    '    vectors = model.encode(windows, batch_size=min(batch_size, max(1, len(windows))),\n'
    '                           prompt="", convert_to_numpy=True,\n'
    '                           normalize_embeddings=True, show_progress_bar=False)\n'
    '    rows = vectors.astype("float32").tolist()\n'
    '    return {"window_version": WINDOW_VERSION, "max_seq_length": maximum,\n'
    '            "spans": spans, "vectors": rows,\n'
    '            "dimension": len(rows[0]) if rows else model.get_sentence_embedding_dimension()}\n'),
   (19,
    19,
    '    batch_size = request.get("batch_size", 32)\n'
    '    if type(batch_size) is not int or batch_size < 1:\n'
    '        raise ValueError("batch_size must be a positive integer")\n'),
   (20,
    41,
    '    model = SentenceTransformer(args.model, revision=args.revision,\n'
    '                                local_files_only=args.offline)\n'
    '    print(json.dumps({"model": args.model, "revision": args.revision,\n'
    '                      **encode_windows(model, texts, batch_size)}))\n')])]

prepared = []
for name, before, after, operations in CHANGES:
    path = Path(name)
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == before, (name, "unexpected baseline")
    lines = raw.decode("utf-8").splitlines(True)
    for start, end, text in reversed(operations):
        lines[start:end] = [text]
    value = "".join(lines).encode("utf-8")
    assert hashlib.sha256(value).hexdigest() == after, (name, "patch mismatch")
    prepared.append((path, value))
for path, value in prepared:
    path.write_bytes(value)
    print("APPLIED", path, hashlib.sha256(value).hexdigest())
