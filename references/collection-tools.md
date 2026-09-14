# 자료 수집과 실행 환경

`scripts/collect.py`는 Python 3.10 이상 표준 라이브러리로 검색·공개 원문 조회·캐시·SQLite FTS5·등록을 수행한다. PDF만 별도의 PyMuPDF가 있는 인터프리터로 처리한다. 원본 연구 스킬이나 CLI는 호출하지 않는다.

## 환경

먼저 `python3 <skill>/scripts/collect.py runtime`으로 PDF 인터프리터를 확인한다. 명시한 경로 → 개인 설정 → 현재 Python → Codex 기본 번들 경로 순으로 실제 import를 시험한다. 찾지 못하면 호스트 `load_workspace_dependencies`가 반환하는 현재 Python 경로를 `configure --pdf-python <경로>`로 지정한다. 없다고 다른 리서치 스킬 가상환경을 차용하거나 패키지를 자동 설치하지 않는다.

`configure --unpaywall-email <사용자가 제공한 이메일>`은 Unpaywall에 사용할 연락 정보를 `~/.config/my-dear-research-center/settings.json`에 저장한다. 개인 설정은 배포 패키지에 포함하지 않는다. 이 이메일은 Unpaywall 요청에만 보낸다. Crossref·OpenAlex·Europe PMC는 현재 기본 공개 경로를 사용한다. 키를 임의로 탐색하거나 유료 계정으로 자동 전환하지 않는다.

## 조사 단계

먼저 기존 `research.py init`으로 연구 폴더를 만든다. 아래의 `<run>`은 그 폴더이고 `<skill>`은 현재 스킬 폴더다.

```bash
python3 <skill>/scripts/collect.py search <run> --provider crossref --query "주제"
python3 <skill>/scripts/collect.py search <run> --provider openalex --query "주제"
python3 <skill>/scripts/collect.py search <run> --provider openalex --semantic --query "찾으려는 연구의 의미를 설명하는 문장"
python3 <skill>/scripts/collect.py search <run> --provider europepmc --query "주제"
python3 <skill>/scripts/collect.py resolve <run> --doi "10.xxxx/논문"
python3 <skill>/scripts/collect.py lookup <run> --doi "10.xxxx/논문"
```

`--size`는 한 번의 API 배치 크기다. 출력의 `next_cursor`를 `--cursor`로 전달해 이어서 검색한다. 한 배치를 받은 것으로 조사가 충분하다고 판단하지 않는다. OpenAlex 의미 검색은 현재 API의 입력·결과 제한을 명시적으로 처리하며 키워드 검색으로 조용히 바꾸지 않는다. 의미 검색을 연속 실행할 때는 공식 1초 간격을 지킨다. 인용 목록·후속 연구는 반환된 DOI·OpenAlex ID 및 현재 웹 도구로 따라간다. Crossref는 DOI·서지·관계, OpenAlex는 인용 관계·자료원 위치, Europe PMC는 생명과학 자료를 보강한다.

같은 논문은 `work_key`로 묶지만 자료원별 관찰은 남긴다. 다른 판본·수정·철회 여부는 원문과 메타데이터를 대조한다. 공통 DOI나 여러 색인 결과를 독립 근거 여러 개로 세지 않는다. `is_retracted` 또는 수정 관계가 없다고 철회·수정이 없다고 단정하지 않는다.

원문은 원발행처와 저자·기관 저장소도 확인한다. `resolve`는 Unpaywall과 Europe PMC의 공개 사본 후보·판본·라이선스·조회 실패를 기록한다. `no_candidates_in_checked_indexes`는 두 색인에서 후보를 얻지 못했다는 뜻이다. `lookup_incomplete`, `rate_limited`, `configuration_required`, `blocked`를 원문 부재로 바꾸지 않는다. 결과의 링크는 아직 다운로드하거나 정독한 자료가 아니다.

DOI를 알고 있으면 `lookup`으로 Crossref 레코드를 직접 조회한다. 제목 검색의 순위 결과를 DOI 동일성 확인 대신 사용하지 않는다. `fetch --resolution <resolve의 event_id>`는 선택 URL이 그 조회에서 나온 후보인지 확인하고 취득 기록에 판본·라이선스·해석 주체를 연결한다. 직접 원문 URL이나 호스트에서 얻은 URL이라면 `--resolution`은 생략한다.

```bash
python3 <skill>/scripts/collect.py fetch <run> --url "확인한 공개 원문 URL" --title "확인한 제목" --candidate P-... --resolution A-... --tables
python3 <skill>/scripts/collect.py read <run> --document D-... --locator page:1
python3 <skill>/scripts/collect.py find <run> --query "자료 안의 단어"
```

PDF의 실제 시그니처를 검사하고 모든 페이지의 1부터 시작하는 번호·텍스트·표 위치를 보존한다. 텍스트가 없는 페이지는 OCR/시각 확인 필요로 표시한다. `--tables`는 표 후보를 추출하며 정확성을 보증하지 않는다. 중요한 표·각주·열 순서는 실제 페이지를 렌더링해 확인한다. HTML/XML은 실제 페이지 번호를 만들지 않고 `document` 위치로 기록한다. 제목·본문·분량이 맞는지 확인하고 로그인 안내·검색 요약·탐색 메뉴를 원문으로 등록하지 않는다.

일반 웹 검색과 브라우저는 호스트 도구를 사용한다. 이 수집기는 로그인 브라우저 자동화나 원본 Insane Search를 실행하지 않는다. 호스트가 확보한 파일은 아래 `ingest`로 같은 저장소에 연결한다.

## 공식 문서·GitHub 연결

기술 문서는 현재 버전에 해당하는 공식 문서·릴리스 노트·원본 저장소를 직접 확인한다. 호스트 검색·웹 읽기·브라우저로 실제 본문을 읽고 원문 URL·문서 버전·확인 범위를 보존한다. 저장한 원문 발췌는 `ingest --provider web --url <원문URL> --revision <문서버전> --content-level fulltext`로 넣고, 브라우저에서 확보한 자료는 `--provider browser`로 기록한다. 응답이 설명·요약뿐이면 `--content-level ai_summary` 또는 `abstract`를 지정한다. 발췌를 전체 공식 문서 정독으로 취급하지 않는다.

GitHub는 현재 호스트의 읽기 도구 또는 이미 인증된 읽기 경로로 커밋을 먼저 확정하고 해당 파일을 읽는다. `ingest --provider github --url <커밋에 고정된 blob URL> --revision <커밋SHA>`를 사용한다. 파일 내용에 없는 기능·전체 저장소 동작을 추론한 경우 별도 검증한다.

```bash
python3 <skill>/scripts/collect.py ingest <run> --file <실제원문발췌파일> --provider web --url <원출처URL> --revision <문서버전> --title "공식 문서 발췌" --content-level fulltext
python3 <skill>/scripts/collect.py ingest <run> --file <읽은코드파일> --provider github --url <고정blobURL> --revision <SHA> --title "코드 경로"
```

호스트 도구가 없으면 공식 웹 문서·공개 저장소 읽기로 대체하고 실제 사용 방법을 기록한다. 같은 결과를 얻으려고 새 MCP나 별도 계정을 자동 설치하지 않는다.

## 근거 장부에 연결

검색·다운로드·추출 기록은 `collection/corpus.sqlite3`와 `collection/blobs/`에 저장된다. 검색 결과는 metadata, 내려받은 본문은 미검토 자료다. 기존 `sources.jsonl`·`claims.jsonl`을 자동으로 확정하지 않는다.

실제로 필요한 페이지·절을 읽고, 확인한 사실·조건·한계를 별도 노트에 쓴 뒤 등록한다. `questions.jsonl`의 실제 질문 ID가 먼저 있어야 한다.

```bash
python3 <skill>/scripts/collect.py register <run> --document D-... --source-id S01 --note-file <검토노트.md> --read-scope "page:2 표 1 및 제한사항" --origin "원발행 주체" --group "공통 원자료 식별자" --question Q01 --kind primary
```

등록은 읽은 범위를 `partial`로 기록하고 근거 노트·해시·문서 ID·원본 파일 해시를 연결한다. `metadata/abstract/ai_summary`는 이 방식의 원문 근거 등록을 거부한다. 주장의 판정·내용 검토는 기존 증거 계약에 따라 별도로 작성한다. `register` 성공도 의미 검증이 아니다. 이후 기존 `research.py validate`와 최종 내용 검토를 수행한다.

여러 연구 프로젝트에서 자료를 다시 찾거나 인용 관계를 따라갈 필요가 있으면 [전역 연구 색인](global-index.md)에 따라 해당 실행을 명시적으로 동기화한다. 프로젝트 내부의 `find`는 현재 실행만, 전역 `index.py find`와 `semantic-search`는 동기화된 실행 전체를 검색한다.

## 캐시·실패·재개

기본 응답 캐시는 24시간이며 `--refresh`로 다시 조회한다. 시점이 중요한 수정·철회·릴리스 정보는 새로 확인한다. 조회 오류는 성공 응답 캐시에 넣지 않는다. 원본과 추출 자료는 연구 폴더 안에 보존하고 JSONL은 기존 최종 검토 지문의 기준으로 유지한다. 같은 연구 폴더는 한 기록 책임자가 사용한다. `.collection.lock`은 동시에 쓰는 작업을 막으며 비정상 중단 뒤에는 실제 실행 프로세스가 없는지 확인하고 해당 잠금만 정리한다.

FTS5는 저장된 단어 기반 검색이다. 한국어 활용형·동의어 검색이나 의미 검색이 아니므로 필요하면 검색어 변형과 원문 대조를 병행한다. API 배치·다운로드 바이트 한도는 운영 제약이며 조사 충분성 기준이 아니다. 한도 때문에 못 읽은 자료와 열린 쟁점은 연구 결과에 남긴다.

공식 근거: [Crossref REST](https://api.crossref.org/swagger-docs), [OpenAlex 의미 검색](https://help.openalex.org/api/semantic-search/), [Unpaywall](https://unpaywall.org/products/api), [Europe PMC](https://europepmc.org/RestfulWebService), [PyMuPDF](https://github.com/pymupdf/PyMuPDF/blob/main/docs/the-basics.rst). 구현에 사용한 실제 라이브러리·호스트 런타임은 `runtime` 결과로 확인한다.
