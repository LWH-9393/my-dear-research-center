# 나의 친애하는 연구센터

ISP/ISMP 흐름으로 연구 범위를 정의하고, 자료를 폭넓고 깊게 수집한 뒤 원출처 추적·교차검증·반증·적대적 검토를 거쳐 결론과 실행 요건을 연결하는 Codex 스킬입니다. 다른 연구 스킬이나 CLI를 실행 중 호출하지 않으며, 검토한 방법론을 이 패키지의 독립 절차로 구현합니다.

## 주요 기능

- 질문·검색·출처·주장·리드·검토·판단·보고서를 연결하는 근거 장부
- Crossref, OpenAlex, Europe PMC, Unpaywall 기반 학술 자료 및 공개 원문 탐색
- 공개 PDF/XML/HTML 추출과 원본·추출 지문 검증
- 여러 연구 실행을 아우르는 로컬 SQLite 통합 색인
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

연구 실행을 만든 뒤 전역 색인에 명시적으로 추가할 수 있습니다.

```bash
python3 scripts/index.py sync /absolute/path/to/research-run
python3 scripts/index.py find "찾을 단어"
python3 scripts/index.py semantic-search "표현이 달라도 의미가 가까운 내용"
python3 scripts/index.py graph "10.xxxx/논문" --depth 2
```

자세한 연구 계약은 `SKILL.md`, 수집 명령은 `references/collection-tools.md`, 전역 색인과 개인정보 범위는 `references/global-index.md`를 확인하세요.

## 검증과 제한

1.3.0 제작본은 Python 3.14와 3.12에서 각각 77개 회귀 시험, 외부 패키지 경로를 막은 격리 시험 77개를 통과했습니다. 독립 전진 검토에서 확인된 식별자 병합 순서, 수집 본문 변조, 관계 누락, 의미 벡터 무결성, 개인 파일 권한 문제를 수정했습니다.

자동 수집, 검색 순위, 의미 유사도와 구조 검사는 사실의 진실성이나 실제 정독을 증명하지 않습니다. 원문 위치와 근거 장부를 다시 읽고 최종 검토를 수행해야 합니다. 개인 설정, 연구 결과, 전역 색인 DB, 의미 모델과 Python 환경은 이 저장소에 포함하지 않습니다.
