# 다음 작업 명세

이 문서는 [AGENT_HANDOFF.ko.md](./AGENT_HANDOFF.ko.md)를 읽은 코딩 에이전트가 바로 실행할 수 있는 우선순위 backlog다.
> **현재 상태 (2026-08-06):** mapper/exporter의 classification/visibility/ACL freshness/tombstone deny,
> explicit section allowlist, live-row suppression, destination URL validation,
> inbound ACL-before-noop/checkpoint/tombstone lifecycle, scope-bound quarantine,
> reinstatement history, scope-bound operational approval gate, and regression tests
> are complete (`169 passed`).
> 남은 P0 차단은 실제 승인 레코드 입력, scope별 destination capability/ACL 승인,
> withdrawal/suppression API 검증, provider/privacy 승인과 reviewed live-export preflight 기록이다.

## P0 — Onyx outbound 안전 게이트 닫기

### 목표

`Mnemosyne -> Onyx` read-only export가 source classification, ACL, tombstone을 위반하지 않도록 mapper와 exporter의 실제 실행 경계를 고정한다.

### 대상 코드

- `mnemosyne/integrations/onyx/mapper.py`
- `mnemosyne/integrations/onyx/exporter.py`
- `mnemosyne/integrations/onyx/contract.py`
- `mnemosyne/integrations/onyx/client.py`
- `tests/integrations/onyx/`

### 권장 구현 순서

1. outbound policy 입력을 명시한다: source classification, visibility, ACL snapshot/freshness, destination capability, `tombstoned_at`, `valid_to`.
2. destination이 source보다 덜 제한적이거나 ACL을 표현할 수 없으면 `deny` 또는 `quarantine`한다.
3. tombstone entity는 mapping 단계 또는 exporter 단계에서 publish하지 않는다.
4. withdrawal API가 있으면 stable Onyx document ID로 withdrawal하고, 없으면 subsequent export suppression을 기록한다.
5. blocked 결과는 이유, entity ID, scope, policy decision만 남기고 note body와 credential은 로그에 남기지 않는다.
6. exporter가 `publish` client를 호출하기 전에 policy decision을 강제한다.

### 필수 테스트

- private source + shared destination → deny/quarantine
- restricted source + missing ACL → default-deny
- stale ACL snapshot → deny/quarantine
- tombstoned source → no publish
- allowed synthetic source → publishable mapping
- exporter blocked result → Onyx client 미호출
- stable ID/content hash가 유지되는 정상 update → duplicate 없음

### P0 완료 조건

핵심 코드 조건은 충족되었다.

- private/restricted source와 public/shared destination은 deny/quarantine
- missing/stale ACL은 default-deny
- tombstoned source는 mapping/exporter 모두 no-publish
- exporter blocked result는 Onyx client를 호출하지 않음
- stable ID/content hash 정상 update는 duplicate를 만들지 않음

실제 Onyx credential이나 destination을 사용하지 않고 위 조건을
`tests/integrations/onyx/test_outbound_policy.py`와 scoped suite로 검증했다.
실제 export를 열기 위한 destination capability/ACL 승인, withdrawal 검증,
provider/privacy 승인, reviewed dry-run/live-export preflight는 별도 gate다.

## P1 — 로컬 개인 runtime smoke path

P0 이후, 사용자가 승인한 개인 경로를 실제로 사용하기 전에 synthetic 디렉터리로 운영 명령을 검증한다.

- 명시적 `--db-path`, `--raw-root`, 별도 `--wiki-root`
- source channel `obsidian`
- 생성 Wiki가 ingest source에 재포함되지 않음
- `wiki status`, `wiki lint`, `graph query --stats` 확인
- dry-run에서 파일 수, entity 수, scope, 오류 목록 확인

SQLite는 iCloud/OneDrive Vault 안에 두지 않는다. Markdown과 Wiki만 동기화 대상으로 삼고 DB는 로컬 또는 별도 백업 정책을 사용한다.

## P2 — provider/privacy 승인 후 개인 Markdown ingest

이 단계는 코드 에이전트가 임의로 시작하면 안 된다. 사용자 승인 후에만 수행한다.

승인 전에 확인할 항목:

- 개인 문서가 외부 provider로 전송되는지
- provider의 보존·학습 정책
- LLM bridge가 어떤 provider/CLI를 선택하는지
- 개인/회사/혼합 문서 분류 결과
- attachment와 Joplin 링크 검증 범위
- 실패 시 원문이 로그에 남지 않는지

승인 후에도 처음에는 명시적으로 선택된 작은 범위로 `dry-run -> add -> wiki status/lint -> graph stats` 순서로 진행한다.

## P3 — 실제 Onyx export 준비

P0와 P2가 모두 통과한 뒤에만 수행한다.

- Onyx API 버전과 ingestion contract 재확인
- destination ACL/classification 매핑 확인
- `cc_pair_id`와 API key는 environment/secret storage에서만 주입
- synthetic dry-run을 먼저 실행하고 문서 ID/hash/classification을 검토
- 실제 export는 사용자가 범위를 승인한 뒤 수행
- export 결과와 accepted/indexed/withdrawn 상태를 분리 기록

API key, bearer token, 개인 note body를 코드·fixture·로그·문서에 기록하지 않는다.

## P4 — 변경 자동화

수동 `update`가 안정화된 뒤에만 watcher나 launchd를 검토한다.

- 변경 감지 대상은 원본 Markdown만 포함
- generated Wiki는 재수집에서 제외
- 중복 실행은 content hash와 checkpoint로 no-op
- provider/ACL 실패는 재시도하되 privacy policy를 완화하지 않음
- 삭제는 물리 삭제가 아니라 tombstone/withdrawal로 처리

## 작업 중단 조건

- private/restricted 문서가 shared destination으로 매핑됨
- tombstoned 문서가 publish 대상으로 남음
- ACL이 없는데 allow로 fallback함
- provider가 승인되지 않았는데 개인 문서를 전송하려 함
- credential이 로그나 fixture에 노출됨
- 기본 전역 DB에 개인 데이터를 잘못 기록함
- Orca task 상태와 실제 작업 트리 상태가 불일치함

## 보고 형식

다음 에이전트는 작업 종료 시 아래를 반드시 보고한다.

1. 변경 파일과 핵심 결정
2. 실행한 테스트 명령과 통과/실패 수
3. privacy·ACL·tombstone 게이트 상태
4. 사용자 승인이 필요한 항목과 다음 명령
