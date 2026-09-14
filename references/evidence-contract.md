# 연구 기록 계약 v1

이 기록은 실제로 수행한 조사·판단·검토를 보존한다. 채우기 위해 검색·열람·검토를 수행한 것처럼 기입하지 않는다. 자동 검사는 기록의 존재·참조·변경을 확인하며 내용의 진실성은 판정하지 않는다.

## 파일과 상태

`scripts/research.py init`이 아래 파일을 만든다. 각 JSONL은 빈 파일로 시작하며 실제 작업 결과를 한 줄에 JSON 객체 하나씩 기록한다. 모든 레코드 `id`는 실행 전체에서 유일해야 한다. 예: `Q01`, `S01`, `C01`, `A01`, `L01`, `T01`, `R01`, `M01`.

| 파일 | 내용 |
|---|---|
| `query.md` | 최초 사용자 요청 원문. 수정하지 않고 추가 지시는 `run.json.amendments`에 기록 |
| `run.json` | 스키마·목적·조사 강도·현재 단계·범위·후속 지시·마감 근거 |
| `questions.jsonl` | 하위 질문, 중요도, 답변 상태, 네 관점의 수집 범위와 깊이 조사 |
| `searches.jsonl` | 실제 검색·읽기·API·브라우저·로컬 조사 기록 |
| `sources.jsonl` | 원자료 식별·시점·접근 범위·공통 원천·근거 노트 |
| `claims.jsonl` | 지지·반대 근거에 연결된 핵심 주장과 내용 검토 |
| `leads.jsonl` | 새롭게 발견한 미조사 쟁점과 처리 결과 |
| `trace.jsonl` | 문제·대안·판단·요건·실행을 연결하는 관계 |
| `reviews.jsonl` | 초안 전 증거 검토와 최종 보고서 검토 이력 |
| `report.md`, `report-map.jsonl` | 전달할 본문과 핵심 문장→주장 연결 |
| `evidence/` | 허용되는 짧은 발췌·자체 근거 노트·실제 실행 결과 |

문자열은 구체적인 내용을 적는다. 배열은 해당 항목이 없을 때 `[]`를 사용한다. 시각은 시간대가 있는 ISO-8601 형식, 알 수 없는 발행일은 `null`이다. 모든 근거 파일은 실행 디렉터리 안의 상대 경로이며, `evidence_sha256`은 실제 파일 바이트의 SHA-256이다. 이는 자료의 신뢰도 점수가 아니다.

`run.json` 초기 필드 중 `scope`에는 범위·독자·기준 시점·제약·성공 기준을 기술한다. `phase`는 `scope|breadth|depth|synthesis|review|delivery`다. `amendments`의 항목은 `at`, `instruction`, `impact`를 갖는다. 기본 `research_depth=broad-deep`를 유지한다. 사용자가 제한한 경우에만 `user-limited`와 해당 지시를 `depth_change_instruction`에 기록한다.

마감 시 `closeout.reason`은 `evidence_sufficient|bounded_limits|user_limit` 중 선택하고 `rationale` 및 `limitations` 문자열 배열을 작성한다. 질문·수집 범위·중요 리드·핵심 주장에 미확정이 남아 있으면 `evidence_sufficient`를 사용하지 않는다.

## 질문과 수집 범위

질문 필수 필드는 `id`, `text`, `importance`(`key|supporting`), `status`(`open|answered|bounded`), `claim_ids`다. `bounded`는 무엇을 판단할 수 없는지 `limitation`에 기록한다. ‘답이 없다’는 결론도 적절한 조사와 근거가 필요하다.

중요 질문은 `coverage`에 `breadth`, `primary`, `counter`, `applicability`를 모두 둔다. 각 관점의 필드는 `status`(`done|limited|not_applicable`), `search_ids`, `source_ids`, `note`다. `done`은 실제 조사 기록이 있어야 하며, `counter`를 제외한 관점은 읽은 자료도 연결한다. 반증 검색이 빈 결과를 반환할 수 있으므로 `counter`의 자료 배열은 비어 있을 수 있다. 빈 결과의 의미와 한계는 기록한다.

원자료 접근이 실패하면 `primary=limited`로 표시한다. `breadth`·`primary`를 해당 없음으로 처리하지 않는다. 다른 관점의 `not_applicable`은 왜 해당 검토가 판단에 영향을 주지 않는지 구체적으로 설명한 경우만 사용한다.

중요 질문의 `depth`에는 다음 다섯 문자열을 기록한다.

- `primary_trace`: 중요한 근거의 원출처와 인용·후속 검증을 어디까지 추적했는지.
- `methods`: 방법·표본·비교 기준·계산·실측을 확인한 내용과 제한.
- `counterevidence`: 강한 반대 근거, 다른 설명, 확인한 방어 논리.
- `applicability`: 질문의 기간·정의·대상·환경에 적용할 수 있는 조건.
- `change_mind`: 어떤 새 증거가 판단을 바꾸는지 또는 왜 좁은 명제에서 해당하지 않는지.

## 조사 기록과 출처

`searches.jsonl`의 필드:

| 필드 | 값 |
|---|---|
| `id`, `question_ids` | 조사 식별자와 대상 질문 |
| `query`, `method` | 실제 쿼리·문서 위치·API 요청의 요약과 사용 도구/방법 |
| `lens` | `breadth|primary|counter|applicability|followup` |
| `executed_at`, `outcome` | 실제 실행 시각, `found|empty|blocked` |
| `source_ids`, `note` | 확인한 자료, 결과·접근 범위·한계 |

사용자 자료만 허용된 연구에서는 `method=local_read`로 실제 검색어·파일·범위를 기록한다. 가용 자료 전체를 확인하는 폭과 그 안의 근거를 추적하는 깊이를 확보한다. 허용되지 않은 웹 검색을 추가하지 않는다.

`sources.jsonl`의 필드:

| 필드 | 값 |
|---|---|
| `id`, `title` | 원자료 식별자·제목 |
| `url` 또는 `local_path` | 실제 원문 위치. `local_path`는 출처 정보이며 검증 도구가 외부 파일을 읽지 않음 |
| `kind` | `primary|secondary|context` |
| `origin`, `independence_group` | 원발행 주체와 공통 원자료 그룹. 다른 웹사이트라는 이유로 다른 그룹을 부여하지 않음 |
| `derived_from` | 등록된 재인용 원자료 ID 배열. 파생 자료는 원천 그룹을 함께 사용 |
| `published_at`, `accessed_at` | 발행 시점 또는 `null`, 실제 열람 시각 |
| `applicability`, `read_scope` | 적용 시점·버전·대상과 실제 읽은 부분 |
| `access` | `full|partial|metadata|blocked` |
| `evidence_file`, `evidence_sha256` | `full`·`partial` 자료의 근거 노트 또는 허용된 발췌 파일과 해시 |

`full`은 이 연구에 필요한 본문에 접근했다는 뜻이며 문서 전체 정독 여부는 `read_scope`로 명시한다. `metadata`·`blocked`는 지지·반박 근거로 사용할 수 없다. 부분 열람은 확인한 구절 범위에서만 사용한다. 근거 노트에는 문서 위치와 원문에서 확인한 사실·조건을 적고, 모델의 해석은 별도 표시한다.

## 주장과 내용 검토

`claims.jsonl` 필수 필드는 `id`, `text`, `question_ids`, `importance`, `kind`, `status`, `rationale`, `applicability`, `evidence`다.

- `kind`: `observed`(직접 관찰·계산), `source_claim`(출처가 설명하는 내용), `inference`(근거를 연결한 판단).
- `status`: `supported|conditional|unresolved|refuted`. 결론의 적용 조건이 핵심이면 `conditional`로 표현한다.
- `evidence`: `{source_id, locator, relation, note}`의 배열. `relation`은 `supports|refutes|context`다. `locator`는 페이지·절·표·코드·시간 위치이며 `note`는 왜 해당 근거인지 설명한다.
- `content_review`: `{reviewer, checked_at, result, note}`. 실제 원문 대조 후 기록한다. 상태별 `result`는 `supported→supports`, `conditional→qualified`, `unresolved→insufficient`, `refuted→refutes`다.

‘문서에 X라고 쓰여 있다’와 ‘현실에서 X가 성립한다’를 같은 명제로 취급하지 않는다. 첫 명제는 원문으로 확인할 수 있지만 두 번째는 주장 성격에 맞는 실증·비교 조건이 필요할 수 있다. 추론도 읽은 근거에 연결하며 가정과 반대 근거를 설명한다. 정량 계산·실험을 실제 수행한 경우 재현 방법·환경·출력을 근거 파일에 보관한다.

## 확장 리드와 추적 관계

`leads.jsonl`: `id`, `text`, `question_ids`, `relevance`, `priority`(`critical|important|background`), `status`(`open|investigated|duplicate|irrelevant|unavailable|deferred`), `search_ids`, `source_ids`. `open` 이외의 상태는 `resolution`에 실제 조사 결과나 처리 이유를 적는다. 모든 열린 리드는 마감 전 조사하거나 명시적으로 처리한다. 중요 미해결 항목을 배경 항목으로 낮춰 통과시키지 않는다.

`trace.jsonl`: `id`, `kind`(`issue|option|decision|requirement|action`), `text`, `rationale`, `parent_ids`. 부모는 질문·주장·다른 추적 항목의 ID이며 순환 관계를 만들지 않는다. 모든 추적 항목은 근거가 된 주장까지 연결한다. `requirement`와 `action`에는 관찰 가능한 `acceptance`를 붙인다. `implementation` 목적은 판단·요건·실행 항목, `decision`은 판단 항목을 포함한다. 구체적 실행안을 추천할 근거가 없으면 그 판단과 필요한 증거 수집 과제를 연결한다.

## 보고서와 최종 검토

`report-map.jsonl`: `id`, `text`(보고서에 있는 정확한 핵심 문장 또는 단락), `claim_ids`, `stance`를 기록한다. `stance`는 `assert|qualified|uncertain|refuted`다. 조건부·미확정·반증 주장을 `assert`로 쓸 수 없다. 핵심 주장 전체가 본문에 대응되어야 하며, 검토자는 반대로 본문에서 누락된 핵심 단정도 찾아야 한다. 단순 문자열 검사는 의미 검토를 대체하지 않는다.

`reviews.jsonl`: `id`, `stage`(`corpus|final`), `mode`(`self|independent`), `reviewer`, `checked_at`, `scope`, `note`, `input_digest`, `verdict`(`acceptable|revise|inconclusive`), `claim_ids`, `findings`를 기록한다. `independent`는 실제 별도 컨텍스트의 식별자를 `context_ref`에 추가한다. 최종 검토는 `report_checked=true`이고 모든 핵심 주장 ID를 포함한다.

`findings`의 항목은 `id`, `severity`(`critical|major|minor`), `judgment`, `evidence`, `impact`, `status`(`open|resolved|dismissed`)를 갖는다. 해결·기각은 `resolution`이 필요하다. 여기에는 **연구 보고서의 오류**를 기록한다. 연구 대상에서 발견한 현실의 문제는 주장·추적표에 기록하므로 문제를 발견한 보고서를 무조건 실패로 처리하지 않는다.

검토 입력 지문은 `fingerprint --stage corpus|final`로 계산한다. 질문·출처·주장·검색·리드·추적과 근거 파일 바이트를 포함하고, `final`은 보고서·본문 연결도 포함한다. `reviews.jsonl`은 자기참조를 피하기 위해 지문에서 제외한다. 지문을 먼저 받은 뒤 해당 입력에 대한 실제 검토를 기록한다. 검토한 입력이 달라지면 새 지문과 검토 결과를 기록한다. 이력은 추가 순서로 유지하며 같은 입력에 대한 마지막 최종 검토가 현재 판정이다. 과거 결함을 기각·해결했다면 마지막 기록에서 그 이유를 추적할 수 있게 남긴다.

완성된 실제 형식 예시는 `evals/fixture.py`가 생성하는 **가상 평가 자료**에서 볼 수 있다. 이를 실제 조사 결과로 복사하지 않는다. 패키지 제작과 검사에 사용하는 평가 자산이며 연구 실행에 의존하지 않는다.
