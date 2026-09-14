# 전역 연구 색인과 인용 그래프

`scripts/index.py`는 여러 연구 실행 폴더를 하나의 로컬 SQLite 데이터베이스에 명시적으로 동기화한다. 기본 위치는 `~/.local/share/my-dear-research-center/research-index.sqlite3`다. 연구 원문과 근거 파일을 복사하지 않고 검색용 텍스트·식별자·관계·원본 실행 경로와 지문을 저장한다. 공개 저장소나 연구 결과물에 이 개인 색인을 포함하지 않는다.

## 프로젝트 동기화

연구 실행이 유효하고 수집 작업이 종료된 뒤 동기화한다.

```bash
python3 <skill>/scripts/index.py sync /absolute/path/to/research-run
python3 <skill>/scripts/index.py status
python3 <skill>/scripts/index.py find "찾을 단어" --limit 20
```

`sync`는 `query.md`, `run.json`, 보고서와 모든 JSONL 기록, 프로젝트의 `collection/corpus.sqlite3`를 읽는다. 질문·검색·출처·주장·리드·검토·판단·보고서 연결, 수집 문서의 페이지·절, 학술 후보를 함께 색인한다. 수집 DB 무결성, 원본 바이트 해시, 추출 페이지 지문과 경로 범위를 먼저 검사하므로 변조되거나 실행 폴더 밖을 가리키는 문서는 거부한다. 같은 실행과 같은 지문은 `unchanged`로 끝나며, 변경된 실행은 해당 실행에서 유래한 레코드·텍스트·관계를 한 트랜잭션 안에서 교체한다. 다른 실행의 자료는 유지한다.

전역 검색 결과는 원래 `run_key`, 레코드 종류, 문서 ID, 페이지 위치를 반환한다. 검색 결과 자체는 근거 검토가 아니다. 원본 실행 폴더로 돌아가 해시와 실제 문서·근거 장부를 확인한다. 실행 폴더를 이동하면 경로가 새 실행 정체성에 포함되므로 기존 색인을 자동으로 재지정하지 않는다.

## 로컬 벡터 의미 검색

기본 다국어 모델은 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`이며 고정 리비전을 사용한다. 모델 카드가 설명하는 50개 언어의 384차원 임베딩을 로컬에서 계산한다. 외부 추론 API에 문장을 보내지 않는다. 모델과 Python 패키지는 저장소에 포함하지 않으며 명시적 설치 명령에서만 전용 환경에 받는다.

```bash
python3 <skill>/scripts/index.py semantic-setup --allow-download
python3 <skill>/scripts/index.py semantic-build
python3 <skill>/scripts/index.py semantic-search "표현이 달라도 의미가 가까운 내용" --limit 20
```

`semantic-setup`은 `uv`로 `~/.local/share/my-dear-research-center/semantic-env`를 만들고 고정된 Sentence Transformers 버전과 모델 리비전을 준비한다. 내려받기·디스크 사용이 있으므로 `--allow-download` 없이는 실행하지 않는다. 다른 환경을 쓰려면 `semantic-build --python <경로> --model <모델> --revision <리비전>`으로 명시한다.

동기화 시 텍스트를 겹치는 구간으로 나누고, `semantic-build`가 정규화 벡터와 원문 해시를 저장한다. 이후 새로 동기화한 텍스트만 추가 계산한다. 검색은 저장된 전체 벡터와 코사인 유사도를 로컬에서 계산한다. 빌드와 검색 모두 worker가 돌려준 모델·리비전·차원·정규화·유한값을 검사하고, 저장 벡터의 길이와 정규화도 다시 검사한다. 모델·리비전이 다른 벡터를 섞지 않고, 원문이 바뀌면 기존 벡터를 폐기한다.

의미 유사도는 사실성·인과관계·찬반 관계를 판정하지 않는다. 상위 결과는 후보 발견에만 사용하고 원문 위치와 주장 장부를 검토한다. 큰 색인은 현재 모든 벡터를 순회하므로 규모가 커지면 ANN 색인 도입 여부를 실측으로 판단한다.

## 인용 그래프

```bash
python3 <skill>/scripts/index.py graph "10.xxxx/논문" --depth 2 --direction both
python3 <skill>/scripts/index.py graph "https://openalex.org/W123" --direction out
```

학술 후보에서 실제로 받은 모든 `references`, Crossref 업데이트·관계 필드를 간선으로 변환한다. DOI와 OpenAlex 식별자는 별칭 테이블을 통해 같은 논문 노드로 합친다. 식별자가 없는 참고문헌도 버리지 않고 원래 메타데이터의 해시를 가진 `unresolved:` 외부 노드로 보존한다.

각 동기화는 다음 수를 `sync_audits`에 기록한다.

- 원본 레코드 관계 수와 색인된 관계 수
- 가져온 인용·수정 관계 수와 색인된 간선 수
- 현재 색인에 원문 노드가 없고 외부 식별자 또는 메타데이터만 있는 간선 수
- 지원하지 않는 형태의 참고문헌 수

기대 수와 실제 색인 수가 다르면 트랜잭션을 실패시킨다. 여기서 ‘완전’은 **수집된 응답과 연구 장부에 포함된 관계를 조용히 버리지 않았다**는 뜻이다. 전 세계 논문의 전체 인용망, 제공자가 누락한 참고문헌, 아직 가져오지 않은 피인용 관계까지 확보했다는 뜻은 아니다. `unresolved_citations`는 실패가 아니라 후속 식별 작업 목록이다.

논문 인용 그래프와 연구 논리 그래프를 구분한다. `citation_edges`는 논문·수정 관계이고, `record_edges`는 질문·검색·출처·주장·리드·검토·판단 추적·보고서 사이에 장부가 명시한 관계를 보존한다. 같은 DOI 노드를 공유해도 서로 다른 제공자의 관찰은 `observations`에 별도로 남긴다. DOI와 OpenAlex 별칭의 통합 상태는 현재 모든 관찰에서 결정적으로 다시 계산하므로 동기화 순서가 논문 정체성을 바꾸지 않는다.

## 운영과 백업

전역 색인은 파생 자료다. 원본 연구 실행 폴더와 근거 파일이 진실 원천이며, 색인이 손상되면 빈 데이터베이스에 실행 폴더들을 다시 `sync`한다. 개인 경로와 연구 내용이 들어 있으므로 GitHub에 커밋하지 않는다. 기본 데이터 디렉터리는 `0700`, 색인 DB와 잠금은 `0600` 권한으로 강제한다. 동기화·임베딩·검색은 전역 잠금 파일로 동시에 쓰는 작업을 막는다. 비정상 종료 뒤 잠금이 남으면 실제 프로세스가 없는지 확인한 후 그 잠금만 정리한다.

모델 출처: [Sentence Transformers 공식 문서](https://www.sbert.net/), [다국어 MiniLM 모델 카드](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2). 모델 라이선스와 리비전은 설치 전에 현재 원문을 다시 확인한다.
