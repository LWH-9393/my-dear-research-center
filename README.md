# 나의 친애하는 연구센터

ISP/ISMP 흐름으로 연구 범위를 정의하고, 자료를 폭넓고 깊게 수집한 뒤 원출처 추적·교차검증·반증·적대적 검토를 거쳐 결론과 실행 요건을 연결하는 Codex 스킬입니다. 다른 연구 스킬이나 CLI를 실행 중 호출하지 않으며, 검토한 방법론을 이 패키지의 독립 절차로 구현합니다.

## 주요 기능

- 질문·검색·출처·주장·리드·검토·판단·보고서를 연결하는 근거 장부
- Crossref, OpenAlex, Europe PMC, Unpaywall 기반 학술 자료 및 공개 원문 탐색
- 공개 PDF/XML/HTML 추출과 원본·추출 지문 검증
- 여러 연구 실행을 아우르는 로컬 SQLite 통합 색인
- 연구 시작·재개·검색·마감에 AI가 호출하는 증분 갱신과 벡터 재사용
- 경로 독립 실행 ID, 이동·복사 구분, 전역 보존 범위 관리
- 선택적으로 설치하는 다국어 Sentence Transformers 기반 로컬 의미 검색
- 수집된 참고문헌·수정·관계를 누락 없이 보존하는 인용 그래프

‘완전한 인용 그래프’는 수집된 응답에 포함된 관계를 모두 보존한다는 뜻입니다. 전 세계 문헌의 전체 인용망을 제공한다는 뜻은 아닙니다.

## 설치

이 저장소를 Codex 스킬 폴더의 `my-dear-research-center`로 복제합니다. Python 3.10 이상과 표준 라이브러리만으로 기록·검증·단어 색인을 사용할 수 있습니다. PDF 추출에는 PyMuPDF가 있는 별도 Python이 필요합니다.

로컬 의미 검색은 모델과 격리 환경을 저장소에 포함하지 않습니다. 내려받기를 명시적으로 허용할 때만 설치합니다.

```bash
python3 scripts/index.py semantic-setup --allow-download
python3 scripts/index.py semantic-build
```

기본 모델은 고정 리비전의 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`이며, 문장은 외부 추론 API가 아닌 로컬 환경에서 처리합니다.

## 사용

```text
$my-dear-research-center [주제]를 폭넓고 깊게 조사하고, 핵심 근거와 반대 증거를 검증해 결론과 필요한 실행계획을 정리해 주세요.
```

연구를 시작·재개하거나 이전 근거를 찾을 때 AI가 필요한 실행의 색인을 갱신합니다. 직접 사용하는 명령은 다음과 같습니다.

```bash
python3 scripts/index.py runs
python3 scripts/index.py check --run /absolute/path/to/research-run
python3 scripts/index.py refresh --run /absolute/path/to/research-run --reason resume --semantic off
python3 scripts/index.py find "찾을 단어"
python3 scripts/index.py refresh --run /absolute/path/to/research-run --reason before_search --semantic required
python3 scripts/index.py semantic-search "표현이 달라도 의미가 가까운 내용"
python3 scripts/index.py graph "10.xxxx/논문" --depth 2
```

자세한 연구 계약은 `SKILL.md`, 수집 명령은 `references/collection-tools.md`, 전역 색인과 개인정보 범위는 `references/global-index.md`를 확인하세요.

## 검증과 제한

1.5.0은 실제 토크나이저 기반 창 분할, 창별 의미 검색, UTF-8 근거 노트 본문 색인을 추가합니다. `refuted`에는 읽을 수 있는 반박 근거, `primary=done`에는 읽을 수 있는 원자료 연결이 필요합니다. 비텍스트 근거의 검색 누락은 `coverage.unindexed_evidence`에 표시합니다.

이전 전에 원본 실행과 DB를 백업하세요. 기존 DB는 첫 쓰기 시 스키마 3으로 이전하며 구벡터 바이트는 보존하지만 검색에는 재사용하지 않습니다. 관련 실행의 `refresh --semantic off` 후 `semantic-build` 또는 `refresh --semantic required`로 토큰 창 벡터를 재계산하세요. 이미 구성된 모델만 사용하며 자동 다운로드는 하지 않습니다.


1.4.0은 경로 독립 실행 ID와 공통 `refresh` 명령을 추가합니다. 보고서만 수정하면 변경 구간의 벡터만 계산하고, 변경 없는 갱신은 모델을 호출하지 않습니다. 원본 바이트만 바뀌어도 현재성 검사에서 감지합니다. 의미 벡터는 배치별로 저장해 중단 후 이어갈 수 있습니다. `check/status/runs`는 파일을 생성하거나 변경하지 않습니다.

회귀 시험은 다음 명령으로 실행합니다. Python 3.14·3.12와 외부 서비스 접근을 차단한 격리 환경에서 검증하며, 실제 로컬 다국어 모델을 이용한 검색·증분 갱신도 별도로 확인합니다.

```bash
python3 -B -m unittest discover -s evals -p 'test_*.py'
```

1.3.0/1.4.0 DB의 스키마 3 이전과 구벡터 재계산 조건은 위 설명과 `references/global-index.md`를 따릅니다. 이전 전 원본과 DB 사본을 보관하고, 복구 시 스킬과 DB 버전을 함께 되돌리세요. `local/off` 정책은 전역 색인 기여를 제거하며 원본 연구를 삭제하지 않습니다. 별도 백업에는 같은 보존 결정을 적용해야 합니다.

검색은 기본적으로 현재성이 검증된 실행만 반환하고 누락 범위를 `coverage`에 알립니다. 데몬은 없으므로 AI가 작업하지 않는 동안의 변경은 다음 확인에 반영됩니다.

자동 수집, 검색 순위, 의미 유사도와 구조 검사는 사실의 진실성이나 실제 정독을 증명하지 않습니다. 원문 위치와 근거 장부를 다시 읽고 최종 검토를 수행해야 합니다. 개인 설정, 연구 결과, 전역 색인 DB, 의미 모델과 Python 환경은 이 저장소에 포함하지 않습니다.

### 검색 검증의 범위

기본 회귀시험은 네트워크·모델 없이 기록, 토큰 창 계약, 근거 노트 검색, 창별 점수 처리, 증분 갱신 및 보존 정책을 검사합니다. 가짜 벡터 시험을 실제 모델의 검색 정확도라고 제시하지 않습니다.

실제 고정 리비전 토크나이저의 한글·영문·혼합·공백·긴 문자열 검사는 선택적으로 실행합니다. 캐시만 쓰는 기본 실행은 `python3 evals/check_tokenizer.py`, 토크나이저 파일 다운로드를 허용하는 실행은 `python3 evals/check_tokenizer.py --allow-download`입니다. Transformers가 있는 별도 환경이 필요하며 모델 가중치나 외부 추론 API는 사용하지 않습니다. GitHub CI는 이 토크나이저 검사와 Python 3.10·3.12·3.14의 표준 라이브러리 회귀시험을 분리합니다. 실제 모델 검색 순위와 에이전트 연구 행동의 우수성은 별도의 평가가 필요합니다.
