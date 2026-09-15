# AI 주도형 유동 색인

AI는 현재 연구·이미 등록된 실행에서 갱신 대상과 시점을 선택한다. `scripts/index.py`는 입력 검증, 증분 반영, 벡터 재사용과 처리 상태를 관리한다. 상시 데몬·예약 작업은 없으며, AI가 작업하지 않는 동안의 외부 변경은 다음 확인 때 발견한다.

기본 DB는 `~/.local/share/my-dear-research-center/research-index.sqlite3`다. 개인 연구 텍스트·관계·실행 경로가 들어 있으므로 공개 패키지에 포함하지 않는다. 원본은 각 연구 폴더와 근거 장부다.

## 시작·재개·수집·검색·마감

아래 `<skill>`은 이 스킬 경로, `<run>`은 연구 실행 절대 경로다. `--reason`에는 그 시점의 한 가지 이유를 지정한다.

```bash
python3 <skill>/scripts/index.py runs
python3 <skill>/scripts/index.py check --run <run>
python3 <skill>/scripts/index.py refresh --run <run> --reason resume --semantic off
python3 <skill>/scripts/index.py find "찾을 단어"
```

- 시작·재개·단어 검색 전: 관련 실행에 `refresh`를 호출한다. 이유는 `start`, `resume`, `before_search`를 사용한다.
- 수집 도중: 자료 묶음을 저장·추출하고 장부에 반영한 뒤 `--reason collection_complete --semantic off`로 갱신한다.
- 의미 검색 전: `--semantic required`로 필요한 벡터를 갱신한 뒤 `semantic-search`를 호출한다.
- 마감: 연구 검토 후 `--reason closeout --semantic auto`로 갱신한다. 색인 실패를 연구 검토 성공으로 덮지 않는다.

`auto`는 이미 설정된 모델만 사용한다. `off`는 텍스트·관계만 갱신한다. `required`에서 환경 미설정·벡터 실패가 있으면 `partial`을 반환하고 종료 코드 2로 미완료를 알린다. 텍스트 색인은 완료됐을 수 있으므로 `semantic`, `semantic_error`를 별도로 확인한다.

`check`, `runs`, `status`는 디렉터리·DB·실행 ID·잠금·설정을 생성하거나 파일 권한을 수정하지 않는다. 없는 DB는 `not_initialized`, 기존 미등록 실행은 `new`로 표시한다. 첫 등록은 `refresh` 또는 기존 호환 명령 `sync <run>`으로 수행한다.

## 현재성, 비용과 실패

수집 DB는 SQLite 읽기 트랜잭션에서 후보·문서·페이지를 읽는다. JSONL·보고서·원본 문서·근거 파일의 내용과 해시를 확인하고 반영 전 재확인한다. 저장 중·끊어진 참조·원본 변조를 발견하면 기존 유효 세대를 보존한다. 열린 질문과 진행 중 연구는 색인할 수 있지만 깨진 구조를 성공으로 처리하지 않는다.

요청 캐시 이벤트나 SQLite 파일 내부 배치의 변화는 본문 재색인 이유가 아니다. 문서·페이지·레코드의 추가·제거·변경만 반영하며, 같은 텍스트·모델 리비전·분할 버전의 벡터를 같은 실행 안에서 재사용한다. 변경 없는 갱신은 모델 worker를 호출하지 않는다. 원본 무결성 확인에 필요한 읽기 비용은 남는다.

벡터는 배치별로 저장하므로 중단 후 미처리분부터 이어간다. 모델 계산 중에는 긴 DB 쓰기 잠금을 잡지 않으며 반영 전에 현재 입력과 텍스트 해시를 확인한다. 데이터 쓰기는 SQLite 트랜잭션으로 직렬화한다. 1.3.0의 `.sqlite3.lock`이 남아 있으면 기존 프로세스를 확인한 후 해당 오래된 잠금을 정리해야 한다.

`refresh`는 실행별 최근 상태와 시도 이유를 남긴다. `busy`는 수집 저장·다른 쓰기를 마친 다음 체크포인트에서 재검사한다. `integrity_error`, `invalid_input`, `identity_conflict`는 원인을 해결한 뒤 재실행한다. 실패를 고정 횟수로 무한 반복하거나 자동 완료 처리하지 않는다.

## 검색 결과를 사용하는 규칙

`find`, `semantic-search`, `graph`는 현재 등록 범위의 원본 상태를 읽기 전용으로 확인하고 `coverage`를 반환한다. 범위를 줄이려면 단어·의미 검색의 `--run-key`를 사용한다. `current`인 실행만 기본 결과에 포함한다. 오래된 자료를 새로 찾기 위해 관련 실행을 `refresh`한 뒤 다시 검색한다.

`stale`, `missing`, `busy`, 오류·ID 충돌은 자료 없음과 다르다. 과거 저장본이 필요한 경우에만 `--allow-stale`을 사용한다. 정책상 제외되었거나 ID가 충돌한 실행은 이 옵션으로도 반환하지 않는다. 원본 위치에 접근할 수 없는 장부의 `local_path`는 `unavailable_source_links`에 출처 ID로 알린다. 보존된 근거 스냅샷을 검증할 수 있다는 사실과 원래 경로를 열 수 있다는 사실을 구분한다.

`semantic.status=ready`는 현재 저장 텍스트에 대응하는 벡터 수에 대한 상태이며 모델 프로세스의 실행 성공을 보증하지 않는다. 실제 검색은 로컬 worker를 실행하고 모델·리비전·차원·정규화·원문 및 벡터 바이트 해시를 검사한다. 누락 벡터 수와 과거 실행 시도는 `semantic` 및 `last_attempt`에 표시한다.

색인의 `current`는 로컬 원본과 일치한다는 뜻이다. 원문 주장의 사실성·현재 유효성·정독·검토 독립성을 증명하지 않는다. 검색 결과를 채택할 때 원본 위치·시점·조건과 근거 장부를 다시 확인한다.

## 토큰 구간과 근거 노트 (1.4.1)

단어 색인의 기본 텍스트 묶음과 모델 입력 구간은 다릅니다. 모델 worker는 실제 토크나이저로 특수 토큰까지 센 뒤 입력 한도 안에서 겹치는 구간을 만듭니다. 구간마다 원래 문자열의 시작·끝 위치, 실제 토큰 수, 벡터를 보존하며 전체 문자열의 끝까지 덮었는지 검사합니다. 긴 질의도 같은 절차를 따릅니다.

검색 순위는 질의 구간과 문서 구간 사이의 최대 코사인 유사도(`max_window_cosine`)입니다. 문서 전체의 조건 충족이나 긴 질의의 모든 요구를 만족한다는 의미가 아닙니다. 결과 `window`와 `snippet`은 일치 구간을, `locator`와 `ordinal`은 소스 위치와 텍스트 묶음을 가리킵니다. 시작·끝 문자 위치의 기준은 `offset_basis=indexed_text_chunk`이며 원본 파일 전체의 절대 오프셋이 아닙니다.

UTF-8 텍스트 근거 노트도 출처 ID와 파일 위치를 연결해 색인합니다. PDF·바이너리·비 UTF-8 자료는 잘못 디코딩하지 않고 `check` 및 검색의 `coverage[].unindexed_evidence`에 남깁니다. 해당 자료는 `collect.py` 추출 또는 명시적인 UTF-8 근거 노트로 연결해야 합니다. 이 목록은 자료 부재가 아니라 텍스트 검색 미반영 범위입니다.

구간 manifest와 벡터는 같은 트랜잭션에서 저장하며 해시와 전체 입력 범위를 검사합니다. 이동에 따른 동일 텍스트 재사용·중단 후 재개·전역 제외 시 삭제에도 구간 정보를 함께 처리합니다. 구간을 나누므로 저장 크기와 추론 횟수는 이전보다 커질 수 있습니다. 실제 문서 규모에서 비용을 측정해야 합니다.

## 로컬 의미 환경

```bash
python3 <skill>/scripts/index.py semantic-setup --allow-download
python3 <skill>/scripts/index.py semantic-build
python3 <skill>/scripts/index.py refresh --run <run> --reason before_search --semantic required
python3 <skill>/scripts/index.py semantic-search "표현이 달라도 의미가 가까운 내용" --limit 20
```

설치 명령은 `uv`로 `~/.local/share/my-dear-research-center/semantic-env`를 준비한다. 기본 모델은 고정 리비전의 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, Sentence Transformers는 고정 버전을 사용한다. 모델과 패키지는 별도 다운로드이며 연구 문장을 외부 추론 API로 보내지 않는다. 이후 빌드·검색은 캐시된 모델만 오프라인으로 로딩한다.

`semantic-build --run-key <키> --batch 32`로 범위와 처리 배치 크기를 지정할 수 있다. 다른 명시적 환경은 `--python`, `--model`, `--revision`으로 구성한다. 전체 벡터를 순회하는 검색이므로 큰 자료에서는 실측 비용을 확인한다. 모델 유사도는 사실성·찬반·인과관계 판정이 아니다.

## 이동·복사·제외

실행 폴더의 `.research-index.json`에 `run_id`와 `scope`를 보관한다. 신규 `research.py init`은 이 파일을 만들며, 기존 연구는 첫 갱신에 추가한다. 연구 본문과 `run.json`은 그대로이므로 기존 검토 지문은 유지한다.

```bash
python3 <skill>/scripts/index.py relocate --from <old-run> --to <new-run>
python3 <skill>/scripts/index.py fork --run <copied-run>
python3 <skill>/scripts/index.py scope --run <run> --set local
python3 <skill>/scripts/index.py forget --run <run>
```

`relocate`는 사용자가 명시했거나 AI가 수행한 이동에 호출한다. 원래 경로가 사라지고 새 경로에 같은 등록 ID가 있어야 하며, 실행 키·벡터·관계를 유지한다. 두 경로가 동시에 존재하면 자동 병합하지 않는다. 별도 연구로 복사한 경우 `fork`로 복사본 ID를 새로 만든 뒤 갱신한다. 단순 경로 부재는 이동·삭제의 증명이 아니다.

`global`은 전역 등록 허용, `local`은 해당 연구 폴더의 수집·검색만 사용, `off`는 전역 파생 보존 제외다. 신규 연구에는 `research.py init --index-scope local|off`로 적용한다. 기존 연구에는 `scope --set local|off` 또는 `forget`을 적용해 전역 본문·벡터·관계·개인 경로·시도 로그를 제거한다. 원본 연구 파일은 삭제하지 않는다. 과거 파일을 복원해도 재등록하지 않도록 내용·경로 없는 실행 UUID 차단 표식만 남긴다. 다시 포함하려는 명시적 지시에는 `scope --set global`을 사용한다.

외장 볼륨 연결 해제 같은 `missing` 상태는 자동 삭제하지 않는다. 오래된 실행 제거는 실제 보존·제거 지시에 따른다. 이 도구는 다른 폴더·클라우드·운영체제 백업을 관리하지 않으므로 사용자 관리 백업에도 같은 비보존 지시를 적용해야 한다. 이 한계를 숨기고 모든 사본이 지워졌다고 주장하지 않는다.

## 인용과 연구 논리 관계

```bash
python3 <skill>/scripts/index.py graph "10.xxxx/논문" --depth 2 --direction both
```

현재 포함된 원래 학술 관찰에서 DOI·OpenAlex 별칭을 재구성한다. 정정·제외 이전의 파생 별칭을 새 근거로 삼지 않는다. 같은 DOI라도 제공자 관찰은 따로 남기고, 중복 인용은 `graph_coverage`에서 원래 개수·색인된 개수·중복 개수를 구분한다. 식별자 없는 문헌과 지원하지 않는 관계 형태도 원래 payload와 외부 노드로 남기고 수를 표시한다.

‘완전’은 가져온 응답과 연구 장부의 관계를 조용히 버리지 않는 범위다. 전 세계 인용망이나 아직 가져오지 않은 관계를 뜻하지 않는다. `record_edges`에는 질문·검색·출처·주장·리드·검토·판단·보고서의 명시된 연결을 보존한다. 색인 관계를 사실 검증으로 취급하지 않는다.

## 이전과 복구

1.3.0/1.4.0 DB는 쓰기 명령을 실행할 때 스키마 3으로 이전한다. 이전 벡터의 바이트는 보존하지만 구간 버전 2와 manifest를 다시 구축하기 전까지 의미 검색 준비 상태로 세지 않는다. 기존 실행 키와 벡터를 보존하고 첫 `refresh`에서 각 실행 ID를 연결한다. 읽기 전용 명령은 이전하지 않는다. 원본 실행과 DB 백업을 먼저 보관하고 복사본에서 검증한다. 구버전으로 되돌릴 때는 스킬과 해당 버전의 DB 백업을 함께 복구한다.

새 전용 데이터 디렉터리는 `0700`, DB·실행 ID 파일은 `0600`으로 만든다. 사용자가 지정한 기존 부모 폴더의 권한을 임의로 좁히지 않는다. 개인 DB·실행 ID·모델·환경·백업을 스킬 저장소에 커밋하지 않는다.

모델 출처: [Sentence Transformers](https://www.sbert.net/), [다국어 MiniLM 모델 카드](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).
