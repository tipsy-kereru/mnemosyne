# Onyx–Mnemosyne 통합 구현 계획과 유즈케이스

## 문서 상태

- 작성일: 2026-08-02
- 상태: 구현 전 설계안
- 범위: 개인 메모리, 외주 프로젝트 지식, 사내 프로젝트의 미팅·메시지·요구사항
- 기준: 현재 mnemosyne 저장소와 참조 대화의 설계 방향

## 1. 결론과 권장 구조

Onyx와 Mnemosyne을 하나의 애플리케이션으로 합치기보다 역할을 분리한 두 계층으로 연결한다.

~~~text
Slack · GitHub · Jira · Gmail · Drive · 회의 기록
                    │
                    ▼
Onyx: 인증 · 커넥터 동기화 · 원문 검색 · 사용자 권한 · 업무용 질의
                    │
                    ▼
Onyx–Mnemosyne Adapter / Export Worker
                    │
                    ▼
Mnemosyne: 원본 보존 · scope 분리 · 엔티티/관계 · 시간 이력 · Wiki · 모순 검토
                    │
                    ▼
Claude Code · Codex · OpenCode · MCP · CLI
~~~

권장 구현 순서는 다음과 같다.

1. **Mnemosyne → Onyx push**: Mnemosyne Wiki와 구조화 지식을 Onyx Ingestion API로 재색인한다.
2. **Onyx → Mnemosyne export**: Onyx가 만든 공통 Document를 Export Worker로 Mnemosyne에 증분 수집한다.
3. **양방향 정제 루프**: Onyx 원문을 Mnemosyne에서 구조화하고, 검토된 요약·결정·요구사항만 다시 Onyx에 게시한다.
4. **권한·운영 강화**: ACL, 재시도, 체크포인트, 감사 로그, 삭제 대신 tombstone을 완성한다.

Onyx는 문서 Ingestion API와 커넥터를 제공한다. 커넥터는 Load/Poll/Slim 흐름으로 전체·증분·존재 여부를 나누므로, Onyx 내부의 공통 Document 단계에 Export Worker를 연결하는 것이 커넥터별 API를 Mnemosyne에서 다시 구현하는 것보다 적합하다. [Onyx Ingestion API](https://docs.onyx.app/developers/guides/index_files_ingestion_api), [Onyx connector guide](https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/connectors/README.md)

## 2. 현재 저장소와 통합 경계

현재 Mnemosyne에서 재사용할 수 있는 기반:

- add/update: 파일·URL·텍스트 수집과 해시 기반 증분 갱신
- scope_id/source_channel: 프로젝트·주제·수집 경로 구분
- SQLite 지식 그래프와 FTS/검색
- Markdown LLM Wiki와 wiki-links
- 엔티티 변경 이력, 모순·충돌 검토
- 삭제 대신 tombstone을 사용하는 유지보수
- MCP 서버와 Codex/Claude Code hook

따라서 1차 통합의 핵심은 새 메모리 엔진이 아니라 Onyx Document를 기존 ingest 계약으로 안전하게 변환하는 일이다.

| 관심사 | Onyx | Mnemosyne |
|---|---|---|
| 외부 인증·커넥터 | 주 소유 | 직접 재구현하지 않음 |
| 원문 수집·증분 동기화 | 주 소유 | Export 문서를 소비 |
| 원문 검색·업무 UI | 주 소유 | MCP/CLI로 보조 |
| 개인·프로젝트 scope | Connector와 연동 | scope_id의 기준 시스템 |
| 지식 관계·시간 이력 | 검색 보조 | 엔티티·관계·버전의 기준 |
| 결정·요구사항·모순 | 검색 가능한 원문 | 검토된 지식으로 승격 |
| 접근 제어 | 사용자 권한의 1차 소스 | ACL snapshot으로 전파 차단 |
| 삭제 | 원본 시스템의 상태 | tombstone과 과거 이력 보존 |

Onyx의 권한 동기화 범위는 배포 버전에 따라 다르므로 Mnemosyne이 ACL을 대체한다고 가정하지 않는다. [Onyx connectors](https://docs.onyx.app/overview/core_features/connectors)

## 3. 공통 데이터 계약

### 3.1 원문 Envelope

~~~json
{
  "contract_version": "1.0",
  "source_system": "onyx",
  "source_type": "github",
  "onyx_connector_id": "connector-17",
  "onyx_cc_pair_id": 243,
  "external_document_id": "github:org/repo:issue:193",
  "external_revision": "source-revision-or-updated-at",
  "external_uri": "https://github.com/org/repo/issues/193",
  "title": "인증 방식 결정",
  "sections": [{"text": "원문 또는 정규화된 섹션", "link": "https://..."}],
  "source_updated_at": "2026-08-02T10:20:00Z",
  "captured_at": "2026-08-02T10:21:03Z",
  "content_hash": "sha256:...",
  "scope_id": "client-a",
  "source_channel": "github",
  "visibility": "project",
  "classification": "internal",
  "access_snapshot": {"users": [], "groups": ["project-client-a"]},
  "sync_origin": "onyx",
  "do_not_reimport": false
}
~~~

식별자 규칙:

- 원문 ID: onyx:{connector_id}:{external_document_id}
- Mnemosyne source ID: 원문 ID + source revision 또는 content hash
- 엔티티 ID: scope_id + entity_type + canonical_name
- Onyx 게시 ID: mnemosyne:{scope_id}:{entity_type}:{entity_id}

보존 규칙:

1. 동일 문서는 재수집되어도 ID가 바뀌지 않는다.
2. 동일 content hash는 no-op으로 처리한다.
3. 내용이 바뀌면 새 버전과 source revision을 만들고 이전 버전을 삭제하지 않는다.
4. external_uri, source ID, source updated time을 승격 지식에 남긴다.
5. 삭제는 물리 삭제가 아니라 tombstone과 valid_to로 기록한다.
6. Mnemosyne 생성 문서는 do_not_reimport: true로 표시한다.
7. ACL을 확인할 수 없는 문서는 quarantine하고 자동 승격하지 않는다.
8. API 키와 토큰은 환경 변수 또는 secret store에만 보관한다.

## 4. 전체 동기화 상태 머신

~~~mermaid
stateDiagram-v2
    [*] --> Discovered: Onyx connector detects document
    Discovered --> Fetched: Load or Poll succeeds
    Discovered --> RetryPending: timeout or rate limit
    RetryPending --> Fetched: backoff retry succeeds
    RetryPending --> Failed: retry budget exhausted
    Fetched --> Fingerprinted: normalize and hash
    Fingerprinted --> NoOp: hash already processed
    Fingerprinted --> Quarantined: missing scope or ACL
    Fingerprinted --> IngestPending: new or changed document
    IngestPending --> Ingested: Mnemosyne add succeeds
    IngestPending --> RetryPending: transient ingest failure
    Ingested --> Extracted: extraction succeeds
    Ingested --> ReviewPending: review required
    Extracted --> ReviewPending: conflict or low confidence
    Extracted --> ActiveMemory: accepted automatically
    ReviewPending --> ActiveMemory: reviewer accepts
    ReviewPending --> Rejected: reviewer rejects
    ActiveMemory --> OnyxPublishPending: curated knowledge selected
    OnyxPublishPending --> PublishedToOnyx: stable ID and push succeed
    OnyxPublishPending --> RetryPending: push failure
    PublishedToOnyx --> Superseded: newer decision or requirement wins
    ActiveMemory --> Tombstoned: source deleted or withdrawn
    Tombstoned --> HistoricalOnly: valid_to recorded
    NoOp --> [*]
    Failed --> [*]
    Rejected --> [*]
    HistoricalOnly --> [*]
~~~

ReviewPending과 HistoricalOnly가 핵심이다. LLM 추출 결과를 곧바로 사실로 만들지 않고, 삭제된 원문도 과거의 근거로 남긴다.

## 5. 유즈케이스별 상태 머신

### UC-01. 개인 메모리·연구 지식 수집

웹페이지, 텍스트, 개인 메모를 검색 가능한 원문에서 재사용 가능한 기억으로 승격한다. 개인 지식은 개인 scope로 격리하고 프로젝트로 명시적으로 연결할 때만 링크한다.

~~~mermaid
stateDiagram-v2
    [*] --> Captured: URL, text, note, file, transcript
    Captured --> RawStored: preserve original and metadata
    RawStored --> Normalized: normalize title and timestamps
    Normalized --> Extracted: entities, claims, topics, links
    Extracted --> PersonalReview: uncertain or sensitive content
    Extracted --> PersonalActive: high-confidence note
    PersonalReview --> PersonalActive: accept into personal scope
    PersonalReview --> Rejected: reject extraction, keep raw
    PersonalActive --> LinkedToProject: user explicitly links project
    LinkedToProject --> PersonalActive: record link without copy
    PersonalActive --> Superseded: newer note or correction
    Superseded --> HistoricalOnly
    Rejected --> HistoricalOnly
    HistoricalOnly --> [*]
~~~

권장 입력:

~~~bash
mnemosyne add ./notes/research.md \
  --domain daily \
  --scope-id personal \
  --source-channel personal-note
~~~

### UC-02. 외주 프로젝트 지식 수집

고객 요청, PRD, GitHub Issue/PR, 회의록을 같은 scope_id로 묶되 원문·추출 지식·고객 승인 결정을 구분한다.

~~~mermaid
stateDiagram-v2
    [*] --> ConnectorMapped: connector mapped to client scope
    ConnectorMapped --> SourceArrived: message, issue, file, meeting
    SourceArrived --> Imported: Export Worker sends document
    Imported --> Classified: requirement or decision candidate
    Classified --> EvidenceOnly: raw evidence with provenance
    Classified --> RequirementReview: scope or requirement candidate
    Classified --> DecisionReview: approval or decision candidate
    RequirementReview --> RequirementActive: owner confirms current state
    DecisionReview --> DecisionActive: client approval verified
    RequirementReview --> ConflictReview: contradicts active requirement
    DecisionReview --> ConflictReview: contradicts existing decision
    ConflictReview --> RequirementActive: supersedes relation accepted
    ConflictReview --> DecisionActive: latest decision accepted
    RequirementActive --> Implemented: linked to code, issue, release
    DecisionActive --> Implemented: linked to implementation evidence
    Implemented --> Reopened: client change or regression
    Reopened --> RequirementReview
    EvidenceOnly --> [*]
    Implemented --> [*]
~~~

핵심 질문:

- 고객이 승인했지만 아직 코드에 반영되지 않은 결정은 무엇인가?
- 현재 요구사항과 폐기된 요구사항은 어떻게 다른가?
- Slack/메일 합의 중 Jira/GitHub에 기록되지 않은 것은 무엇인가?
- 고객 요청이 계약 범위 또는 마일스톤을 넘어서는가?

### UC-03. 사내 프로젝트의 미팅·메시지·요구사항 연결

여러 사용자가 접근하므로 scope_id만으로는 충분하지 않다. ACL이 전달되지 않은 문서는 조직 전체 지식이 되지 않는다.

~~~mermaid
stateDiagram-v2
    [*] --> Detected: Slack, Gmail, Drive, Jira, GitHub, meeting
    Detected --> PermissionChecked: source ACL available
    Detected --> AccessQuarantined: ACL missing or stale
    PermissionChecked --> ProjectScoped: mapping resolves project
    PermissionChecked --> MappingReview: mapping ambiguous
    ProjectScoped --> Normalized: common envelope created
    Normalized --> Indexed: Mnemosyne source index updated
    Indexed --> Linked: message, meeting, requirement connected
    Linked --> TeamVisible: ACL filtered for authorized users
    TeamVisible --> Restricted: membership or classification changes
    Restricted --> TeamVisible: ACL refresh confirms access
    MappingReview --> ProjectScoped: owner approves mapping
    MappingReview --> AccessQuarantined: owner rejects mapping
    AccessQuarantined --> PermissionChecked: ACL or mapping refreshed
    TeamVisible --> HistoricalOnly: source withdrawn or access revoked
    HistoricalOnly --> [*]
~~~

### UC-04. 코딩 에이전트가 프로젝트를 이어서 작업

에이전트는 현재 scope와 권한을 포함한 검색을 거쳐야 한다. 답변에는 원문 링크와 지식의 시점을 함께 반환한다.

~~~mermaid
stateDiagram-v2
    [*] --> QueryReceived: Codex, Claude, or OpenCode asks
    QueryReceived --> ScopeResolved: resolve project and user scope
    ScopeResolved --> AccessFiltered: apply ACL and classification
    AccessFiltered --> EvidenceRetrieved: FTS, graph, vector, hybrid
    EvidenceRetrieved --> TimelineBuilt: compare current and history
    TimelineBuilt --> Answered: cite source and confidence
    TimelineBuilt --> ClarificationNeeded: conflict or incomplete evidence
    ClarificationNeeded --> Answered: user confirms decision
    Answered --> MemoryWriteCandidate: durable fact observed
    MemoryWriteCandidate --> ReviewPending: explicit write or policy
    ReviewPending --> ActiveMemory: user accepts write
    ReviewPending --> Answered: user declines write
    Answered --> [*]
~~~

자동 기록은 기본적으로 ReviewPending을 거친다. 코드 hook으로 수집되는 파일 변경과 고객 승인 결정은 같은 기억으로 취급하지 않는다.

### UC-05. 변경·삭제·모순 처리

현재 사실과 과거에 사실이었던 것을 함께 다룬다.

~~~mermaid
stateDiagram-v2
    [*] --> ActiveVersion: source or fact is current
    ActiveVersion --> SameContent: next sync has same hash
    SameContent --> ActiveVersion: no-op and checkpoint advance
    ActiveVersion --> ChangedContent: source revision differs
    ChangedContent --> NewVersion: append history
    NewVersion --> ActiveVersion: new version accepted
    NewVersion --> ConflictPending: incompatible property or relation
    ConflictPending --> ActiveVersion: supersedes resolution accepted
    ConflictPending --> ActiveVersion: both kept with context
    ActiveVersion --> SourceWithdrawn: deletion or access revocation
    SourceWithdrawn --> TombstoneWritten: write tombstone and valid_to
    TombstoneWritten --> HistoricalOnly: retain provenance and history
    HistoricalOnly --> Reinstated: source returns or reviewer restores
    Reinstated --> ActiveVersion
~~~

## 6. 구현 계획

### Phase 0. 계약·보안 스파이크

- [ ] Onyx 배포 방식·버전·Ingestion API 사용 가능 여부 확인
- [ ] Connector/CC pair와 Mnemosyne scope_id 매핑 형식 확정
- [ ] Envelope JSON Schema와 stable ID 규칙 추가
- [ ] ACL 누락 문서의 quarantine 정책 확정
- [ ] secret 환경 변수와 로그 redaction 규칙 확정
- [ ] 실제 개인·고객 원문이 없는 synthetic fixture 작성

**완료 기준**: 동일 ID, 동일 hash, ACL 누락, 재시도 실패를 재현한다.

### Phase 1. Mnemosyne → Onyx push

추가 후보 모듈:

~~~text
mnemosyne/integrations/onyx/
├── client.py
├── mapper.py
├── exporter.py
├── sync_state.py
└── acl.py
~~~

제안 CLI:

~~~bash
mnemosyne sync onyx push --scope-id client-a --dry-run
mnemosyne sync onyx push --scope-id client-a
mnemosyne sync onyx status --scope-id client-a
~~~

원칙:

- 전체 Wiki가 아니라 project, requirement, decision, meeting-summary, conflict, action-item부터 게시한다.
- stable document ID와 doc_updated_at을 유지한다.
- API accepted와 indexed를 별도 상태로 기록한다.
- do_not_reimport: true인 문서는 Export 대상에서 제외한다.

**완료 기준**: dry-run, 신규 생성, 동일 hash no-op, 변경 update, retry, 링크 확인이 자동 테스트로 통과한다.

### Phase 2. Onyx → Mnemosyne Export Worker

커넥터별 원문 API를 Mnemosyne에서 직접 호출하지 않고 Onyx 공통 Document 단계에서 export한다.

~~~text
Onyx Load/Poll/Slim connector
             │
             ▼
      common Document
        ├───────────────► Onyx index
        └───────────────► Export Worker
                              │
                              ▼
                 Envelope → mnemosyne add/update
~~~

필수 기능:

- connector별 checkpoint와 watermark
- at-least-once 전달을 전제로 한 idempotency
- rate limit, timeout, schema 오류 분류
- mapping 실패 quarantine
- raw source 저장 후 구조화 추출
- 삭제/누락을 tombstone 후보로 전달

**완료 기준**: 반복 전달에도 중복이 없고, 중단 후 checkpoint부터 재개되며, source deletion이 tombstone으로 남는다.

### Phase 3. 구조화 지식 승격

- [ ] project, client, stakeholder, requirement, decision, meeting, action-item, risk, blocker, release 매핑
- [ ] REQUESTED_BY, DECIDED_IN, SUPERSEDES, CONFLICTS_WITH, IMPLEMENTS, BLOCKS, VERIFIED_BY, DERIVED_FROM 관계 추가
- [ ] 원문 수집과 검토된 엔티티 승격 분리
- [ ] confidence, extractor version, reviewer, reviewed_at 기록
- [ ] 현재 버전과 과거 버전의 timeline query 추가

**완료 기준**: 현재/폐기 요구사항, 결정 근거, 미해결 action item을 scope와 시간 조건으로 재현한다.

### Phase 4. 권한·검색·에이전트 연동

- [ ] MCP/CLI 검색에 scope_id, actor, classification 필터 적용
- [ ] ACL snapshot 만료 문서는 기본 비공개
- [ ] source URL·revision·captured_at을 citation에 포함
- [ ] 에이전트 memory write를 명시적 승인 또는 정책 기반으로 제한
- [ ] 개인·고객·사내 scope 간 cross-link를 감사 로그로 기록

**완료 기준**: 권한 없는 검색·그래프 경로·MCP 응답에 제한 문서가 노출되지 않는다.

### Phase 5. 운영·관측성

- [ ] sync status, retry, quarantine list, replay 명령
- [ ] 마지막 성공 시각, 처리량, 실패율, quarantine 수, stale 수
- [ ] payload schema version과 mapper version 기록
- [ ] Onyx mock server와 contract fixture
- [ ] 장애 시 Onyx 검색은 유지되고 Mnemosyne 정제만 지연되는 격리

## 7. 권장 설정 예시

~~~yaml
version: 1
onyx:
  base_url: $ONYX_BASE_URL
  api_key_env: ONYX_API_KEY
  ingestion_cc_pair_id_env: ONYX_MNEMOSYNE_CC_PAIR_ID

mappings:
  - connector_id: client-a-github
    scope_id: client-a
    source_channel: github
    default_classification: confidential
    acl_mode: require_snapshot
  - connector_id: client-a-slack
    scope_id: client-a
    source_channel: slack
    default_classification: confidential
    acl_mode: require_snapshot
  - connector_id: personal-files
    scope_id: personal
    source_channel: personal-file
    default_classification: private
    acl_mode: owner_only

sync:
  max_attempts: 5
  initial_backoff_seconds: 5
  checkpoint_store: sqlite
  deletion_policy: tombstone
  reimport_generated_documents: false
~~~

API 키 자체가 아니라 환경 변수 이름만 설정 파일에 둔다.

## 8. 테스트 전략

계약 테스트:

- Onyx Document → Envelope 필수 필드·타입 검증
- stable ID가 connector/section 순서에 좌우되지 않는지 검증
- 동일 content_hash의 no-op 검증
- 알 수 없는 contract_version의 quarantine 또는 명시적 실패 검증

상태 전이 테스트:

- 신규: Discovered → Fetched → Ingested → ActiveMemory
- 일시 오류: RetryPending → Fetched
- 반복 실패: RetryPending → Failed
- ACL 누락: Fetched → Quarantined
- 변경: ActiveVersion → ChangedContent → NewVersion
- 삭제: SourceWithdrawn → TombstoneWritten → HistoricalOnly
- 모순: NewVersion → ConflictPending → ActiveVersion

권한 테스트:

- 서로 다른 scope_id 간 검색 격리
- project/private ACL 차단
- ACL snapshot 만료 시 기본 deny
- 그래프 경로를 통한 간접 정보 누출 차단
- private/restricted 문서가 Onyx에 게시되지 않는지 검증

수동 검증:

1. 외주 프로젝트 고객 요청을 Onyx에서 수집한다.
2. Mnemosyne Wiki에서 원문 링크·scope·source channel을 확인한다.
3. 같은 요청을 재동기화해 중복이 없는지 확인한다.
4. 요구사항 변경 후 이전 버전이 supersedes 관계로 남는지 확인한다.
5. 원문 권한을 제거한 뒤 검색과 에이전트 응답에서 사라지는지 확인한다.
6. Mnemosyne 생성 요약이 다시 원문으로 수집되지 않는지 확인한다.

## 9. 위험과 결정 게이트

| 위험 | 대응 | 결정 게이트 |
|---|---|---|
| 공개 API만으로 원문/ACL/이벤트 회수가 불완전할 수 있음 | Onyx 내부 Export Worker 또는 공통 Document hook 우선 | Phase 0에서 실제 지점 확인 |
| scope_id만으로 사용자 권한이 부족함 | ACL snapshot + 기본 deny | Phase 4 전 사내 전체 공개 금지 |
| 양방향 게시 무한 루프 | stable ID, sync_origin, do_not_reimport | Phase 1부터 계약에 포함 |
| LLM 추출 오류 | 원문·confidence·review queue·provenance | 자동 승격 타입 제한 |
| 삭제가 과거 근거까지 제거 | tombstone + valid_to | 물리 삭제 금지 |
| 개인·외주·사내 자료 혼합 | scope mapping 필수, cross-link 승인 | mapping 없는 문서 quarantine |
| 버전 변화로 계약 파손 | schema version, mock contract test, mapper version | 업그레이드 전 suite 실행 |

## 10. 최종 권장안

> **Mnemosyne의 검토된 Wiki/엔티티를 stable ID와 provenance를 보존한 Onyx 문서로 게시하고, 이후 Onyx의 공통 Document 단계에서 원문을 증분 export해 Mnemosyne의 기존 add/update·scope·history·tombstone 흐름으로 수용한다.**

초기 배포에서 제외할 것:

- Mnemosyne이 Slack/GitHub/Jira 인증과 커넥터를 직접 재구현하는 것
- ACL 없는 문서를 조직 전체 기억으로 자동 승격하는 것
- LLM 요약을 원문과 같은 신뢰도로 취급하는 것
- 과거 원문을 즉시 물리 삭제하는 것
- 개인 scope와 고객 scope를 암묵적으로 합치는 것

Onyx는 **수집·검색·권한·업무 UI**, Mnemosyne은 **관계·시간·근거·장기 기억**에 집중한다. 이 경계를 지키면 개인 메모리와 외주·사내 프로젝트를 같은 기술 기반에서 다루되 scope·ACL·provenance를 통해 섞이지 않게 운영할 수 있다.

## 참고 자료

- [Mnemosyne README](../README.md)
- [Mnemosyne Korean README](../README.ko.md)
- [Mnemosyne architecture](../ARCHITECTURE.md)
- [Onyx Ingestion API](https://docs.onyx.app/developers/guides/index_files_ingestion_api)
- [Onyx Core Concepts](https://docs.onyx.app/developers/core_concepts)
- [Onyx Connector Overview](https://docs.onyx.app/admins/connectors/overview)
- [Onyx Connector implementation guide](https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/connectors/README.md)

