# 방법론 계보와 유지보수

패키지 버전: 1.4.0. 작성 기준: 2026-09-14.

1.4.0은 AI의 연구 체크포인트에 연결하는 `refresh`, 읽기 전용 현재성 확인, 경로 독립 실행 ID, 내용별 증분 색인·벡터 재사용, 배치 중단 복구, 이동·복사·보존 범위 관리를 추가했다. 원본 바이트만 변경된 경우도 검증하며, 문헌 관계는 현재 원래 관찰에서 다시 구성한다. 데몬이나 외부 추론 API를 추가하지 않는다.

1.2.0은 자체 수집 도구를 추가했다. Crossref/OpenAlex/Europe PMC 검색, DOI 조회, Unpaywall/Europe PMC 공개 사본 탐색, 선택적 PyMuPDF 페이지·표 추출, SQLite 캐시·FTS5, 기술 문서와 GitHub 자료 반입을 공식 API·문서에 근거해 구현했다. 1.2.1은 기술 문서 수집을 공식 문서·릴리스 노트·원본 저장소 직접 확인으로 정리했다. 원본 스킬 엔진은 복사하지 않았다. 개인 이메일·Python 경로는 사용자 설정에 보관한다. 수집·추출 성공과 실제 정독·의미 검증은 별도다.

1.3.0은 여러 연구 실행을 명시적으로 동기화하는 전역 SQLite 색인, 50개 언어 Sentence Transformers 모델을 사용하는 선택적 로컬 벡터 검색, 수집된 참고문헌·수정 관계의 완전성 감사를 포함한 인용 그래프, 질문·주장·출처·판단의 연구 논리 그래프를 추가했다. 모델·전용 환경·개인 색인 데이터베이스는 패키지에 포함하지 않는다. ‘완전한 그래프’는 가져온 필드의 모든 관계를 보존한다는 범위로 제한한다.

연구 절차와 검증 코드는 이 패키지용으로 새로 작성했다. 아래 원천에서는 방법론을 검토하여 채택·조정했다. 이 목록은 출처와 설계 이유를 보존하기 위한 자료이며 실행 중 다른 스킬을 읽거나 호출하라는 지시가 아니다. 원천 스킬의 코드·CLI·런타임·프롬프트 파일을 패키지에 복사하지 않았다.

| 원천 | 확인한 범위 | 반영 내용과 조정 |
|---|---|---|
| ISP/ISMP | NIA 2026년 정보화 투자관리 가이드 제1판, 부록 1, 인쇄면 80–84 | 진단·전략·목표·요건·이행의 연결. 일반 연구에 맞게 목적별 결과를 조절 |
| Insane Research 2.9.0 | 설치본 진입점, 단계 계약, 주장·출처 검증 규칙과 검증 코드 일부, 검색·자료 품질 지침 | 주장 장부·반증·재개·추적. 출처 수로 진실을 판정하지 않고 구조 검사와 내용 검토를 구분 |
| Insane Search 0.3.1 | 설치본 진입점과 접근 실패·응답 검증 지침 | 접근 유형별 대체 경로와 본문 확인. 자동 설치·모든 경로 소진을 기본으로 삼지 않음 |
| 로컬 Deep Research 및 Work 0.1.15 | 진입점, 로컬 methodology | 질문·독자·범위, 교차검증, 증거에 따른 구조 수정, 전달 형식별 출처 |
| HyperResearch 0.11.1 Codex 포트 | 진입점·포트 계보·width sweep·depth investigation·contradiction graph·corpus critic | 폭·원출처 및 후속 연구·모순·초안 전 공백 검토. 고정 자료 수·단계·다중 초안 횟수 대신 실제 질문과 근거 충분성 사용 |
| 내 친애하는 적대자 3.1.0 | 원본 Codex 지침, 고정 리비전 efc93e93ae30e955483d758527a26cbc1561f6f2 | 강한 해석·숨은 전제·파급·방어 논리·근거와 영향 검토. 페르소나·외부 호출·고정 보고서 양식은 가져오지 않음 |
| alphaXiv/OpenResearch | 고정 리비전 `cf4baa720f9f891182336d4b7e2fa0f800d12a47`의 문헌 검색·실험 계보·실행 증거 지침 | 키워드·의미 탐색 조합, 자료원 간 후보 정규화·중복 제거·표적 후속 검색, 비교 계약과 실험 결과 보존, 실제 로그 확인. 짧은 검색·정독 상한, 자동 종료 횟수, 원본 CLI·서버·모델·컴퓨트·위임 규칙은 가져오지 않음 |

외부 원천 확인 위치:

- [NIA 가이드 배포](https://www.nia.or.kr/site/nia_kor/ex/bbs/View.do?bcIdx=29431&cbIdx=99835)
- [HyperResearch 원천](https://github.com/jordan-gibbs/hyperresearch)
- [내 친애하는 적대자 확인 리비전](https://github.com/LWH-9393/my-dear-adversary/blob/efc93e93ae30e955483d758527a26cbc1561f6f2/codex/my-dear-adversary/SKILL.md)
- [OpenResearch 문헌 검색](https://github.com/alphaXiv/OpenResearch/blob/cf4baa720f9f891182336d4b7e2fa0f800d12a47/agent-skills/orx-lit-review/SKILL.md)
- [OpenResearch 실험 계보](https://github.com/alphaXiv/OpenResearch/blob/cf4baa720f9f891182336d4b7e2fa0f800d12a47/agent-skills/orx-experiment-tree/SKILL.md)
- [OpenResearch 실행 증거](https://github.com/alphaXiv/OpenResearch/blob/cf4baa720f9f891182336d4b7e2fa0f800d12a47/agent-skills/orx-evidence/SKILL.md)

원천에서 확인한 MIT 고지는 [third-party-notices.txt](third-party-notices.txt)에 보존한다. 원문을 그대로 모은 패키지가 아니며 위 원천과 동일한 구현이나 공식 호환성을 주장하지 않는다.

유지보수 시에는 실제 실패나 개선 요구를 근거로 내부 절차와 평가 사례를 함께 수정한다. 원천 업데이트를 자동 상속하지 않고 버전·수정 이유·검증 결과를 확인한다. 출처 자체의 품질 평가와 특정 원천 스킬의 성능 주장은 별개다.
