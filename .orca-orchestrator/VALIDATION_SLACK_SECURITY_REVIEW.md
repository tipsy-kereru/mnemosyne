# Slack 통합 독립 검증 보고서 (wp-slack-validation)

- 작업: `task_22f7b0f46027` / dispatch `ctx_18bb154bbf1c`
- 대상: `docs/SLACK_INTEGRATION_CONTRACT.ko.md` v1 계약과 그 구현
- 방식: 읽기 전용. 저장소 파일 수정 없음, 비밀/사적 노트 미열람, 의존성 미설치, Slack/Onyx 미호출
- 판정: **조건부 통과 (CONDITIONAL PASS)** — 실제로 악용 가능한 유출은 발견되지 않았으나, 계약 게이트 1건이 실제로는 충족되지 않는다

> **이해상충 고지.** 이 검토의 대상 코드는 같은 세션의 앞선 작업에서 **본인이 작성한 것**이다. 독립성이 구조적으로 제한되므로, 기존 테스트를 재확인하는 대신 **테스트가 다루지 않는 경로를 공격적으로 탐침**하는 방식으로 보완했다. 아래 발견 9건 중 6건은 기존 테스트가 통과하는 상태에서 나왔다. 그럼에도 이 보고서는 제3자 검토를 대체하지 않는다.

---

## 1. 요약

| 구분 | 건수 |
|---|---|
| BLOCKER | 0 |
| HIGH | 1 (V-01) |
| MEDIUM | 4 (V-02 ~ V-05) |
| LOW | 4 (V-06 ~ V-09) |
| 검증 통과 항목 | 13 |

핵심 안전 속성 — **격리(INV-1), 토큰 비영속, 격리 스냅샷 메타데이터 한정, ACL 선행, live 차단** — 은 모두 바이트 수준 또는 호출 순서 수준에서 **실증 확인되었다.** 발견된 결함은 (a) 계약이 요구한 격리 기록이 실제로 생성되지 않는 경로 1건, (b) 저하된 입력에 대해 fail-open 하는 경로 3건, (c) INV-1 덕분에 현재는 도달 불가능한 심층 방어 구멍 4건이다.

---

## 2. 발견 사항

### V-01 (HIGH) — ACL 단계의 API 오류가 격리 기록을 만들지 않는다

**계약 위반.** §10은 `not_in_channel`·`channel_not_found`·`is_archived`·`restricted_action`을 "격리, fetch 중단"으로 규정하고, 인수 테스트 T-MK-4가 이를 보증하기로 되어 있다.

실제로는 `SlackSyncEngine.sync()` / `.reconcile()`의 `try/except`가 **`history` 열거 루프만** 감싸고 있어, `_acl_gate()` 안의 `connector.channel_info()`에서 발생한 `SlackApiError`가 **그대로 전파된다.**

증거 (`probe4.py`):

```
E not_in_channel:    UNCAUGHT not_in_channel;    quarantine_records=0  status=registered
E channel_not_found: UNCAUGHT channel_not_found; quarantine_records=0  status=registered
E is_archived:       UNCAUGHT is_archived;       quarantine_records=0  status=registered
B invalid_auth:      UNCAUGHT invalid_auth;      quarantine_records=0  status=registered  last_error=''
```

결과: 격리 레코드 0건, 소스 상태는 `registered` 그대로, `last_error` 공란. 운영자가 나중에 `quarantine list` / `status`로 확인할 수 있는 흔적이 **아무것도 남지 않는다.**

완화 요인: CLI는 `SlackApiError`를 잡아 종료 코드 2로 매핑하므로 즉시 실행한 사람은 실패를 본다. 자동 승격도 일어나지 않는다(fetch 자체가 중단됨). 따라서 데이터 유출은 아니다.

**기존 테스트가 왜 놓쳤는가:** `test_mock_api.py::test_permission_errors_surface_for_quarantine`은 커넥터가 예외를 던지는지만 단언한다. 함수 이름은 "for_quarantine"이지만 격리 레코드를 확인하지 않는다. **계약 게이트를 검증하는 것처럼 보이면서 검증하지 않는 테스트다.**

권고: `_acl_gate`를 `try/except SlackApiError`로 감싸고, `QUARANTINE_ERRORS`에 속하면 `_quarantine(...)` 후 `SyncResult(quarantined=1)` 반환, 그 외에는 `failed`로 계상하고 `record_error`. 테스트는 예외가 아니라 **격리 레코드와 소스 상태**를 단언해야 한다.

---

### V-02 (MEDIUM) — reconcile이 원격에 존재하는 메시지를 삭제로 오판한다

R24는 "저하된 응답을 삭제 근거로 삼지 말 것"을 요구한다. 예외 발생 경로는 올바르게 방어되지만, **파싱은 되었으나 `ts`가 형식 위반인 원격 메시지**는 `window`에서 탈락 → `remote_keys`에 없음 → 로컬 사본이 `reconcile:remote_absent`로 **tombstone 된다.**

증거 (`probe5.py` H): 원격이 `ts(1)` 메시지를 여전히 반환(단 `ts`가 `"BAD-TS"`)했는데도

```
H reconcile: tombstoned=1  rejected=1  watermark='1712345679.000100'
H msg ts(1) tombstoned: True  reason: reconcile:remote_absent
```

tombstone은 되돌리려면 명시적 조작이 필요한 상태 파괴 연산이므로, 저하 입력에서 fail-open 하는 것은 방향이 반대다. 워터마크도 함께 전진했다.

발생 가능성은 낮다(Slack `ts` 형식은 안정적). 그러나 **유일하게 상태를 파괴하는 경로**에서의 fail-open이므로 심각도를 유지한다.

권고: `invalid`가 비어 있지 않으면 예외 경로와 동일하게 **tombstone 0건으로 reconcile 중단**.

---

### V-03 (MEDIUM) — `X-OAuth-Scopes` 헤더가 없으면 과잉 권한 검사가 통과한다

`assert_scopes_allowed(parse_scope_header(None))` → 빈 집합 → 통과. 즉 헤더가 없는 응답은 R30 검사를 **무력화**한다.

증거 (`probe5.py` G): 목 서버가 `granted_scopes=""`로 응답 → `G missing scope header -> ALLOWED (fail-open)`.

실제 Slack은 항상 이 헤더를 보내므로 현재 영향은 낮다. 그러나 헤더를 제거하는 프록시나 예상 밖 응답 형태에서 조용히 검사가 사라진다. 실패 폐쇄 원칙상, **비루프백 호스트에서는 헤더 부재 자체를 거부**해야 한다.

---

### V-04 (MEDIUM) — revoked 소스도 `source_id`를 명시하면 내용을 반환한다

R3은 revoked 소스에 대해 fetch·질의 모두 거부를 요구한다. `search_messages`는 `source_id=None` 분기에서만 revoked를 제외하고, `list_messages`는 상태를 아예 보지 않는다.

증거 (`probe4.py` D), revoke 이후:

```
D search(None): 0        ← 필터됨
D search(explicit sid): 1  ← 반환됨
D list_messages(explicit sid): 1  ← 반환됨
```

완화 요인: CLI `cmd_query`가 별도로 revoked를 검사해 `deny:source_revoked`(종료 코드 2)를 반환하므로 **출하된 경로는 안전하다.** 저장소 API를 직접 쓰는 향후 호출자에 대한 심층 방어 구멍이다.

---

### V-05 (MEDIUM) — `KnowledgeGraph` 초기화가 Onyx 패키지 전체를 끌어온다

`schema.py`를 표준 라이브러리 전용으로 분리한 목적("KG 초기화가 onyx/yaml 체인을 당기지 않도록")이 **실제로는 달성되지 않았다.** `import mnemosyne.integrations.slack.schema`가 먼저 패키지 `__init__.py`를 실행하고, 그것이 `store`/`sync`/`acl`을 모두 임포트하며, `acl` → `mnemosyne.integrations.onyx.acl` → onyx 패키지 `__init__`이 `client`·`worker`·`exporter`를 전부 로드한다.

증거:

```
baseline (KG deps minus slack)      yaml: False | onyx: False | urllib.request: False
import slack.schema alone           yaml: True  | onyx: True  | slack.store: True
KnowledgeGraph() 초기화 후           yaml: True  | onyx: True  | urllib.request: True
incremental slack.schema import: 12.7–13.0 ms
```

즉 Slack 변경 이전에는 KG 초기화에 존재하지 않던 yaml·urllib·Onyx HTTP 클라이언트가 이제 **모든 `KnowledgeGraph()` 생성마다** 로드된다(약 +13 ms). 훅, `mnemosyne-query`, MCP 서버 기동 등 잦은 경로에 붙는 비용이다.

권고: `slack/__init__.py`의 즉시 재수출을 걷어내거나(모듈 직접 임포트 방식), `acl.py`가 onyx 심볼을 함수 내부에서 지연 임포트. 후자가 더 작은 변경이다.

---

### V-06 (LOW, 잠재) — `get_entity_history` / `get_entity_timeline`이 격리 엔티티 본문을 반환한다

`entity_history` 테이블에는 `source_channel` 컬럼이 없어 격리 술어가 적용되지 않는다.

증거 (`probe2.py`):

```
history record: [{"entity_id":"e-iso", ..., "properties": {"body": "CONFIDENTIAL-PAYLOAD"}, ...}]
timeline current: None          ← get_entity는 올바르게 차단
timeline history leaks payload: True
```

도달성: MCP `_get_entity`/`_update_entity`는 먼저 `kg.get_entity()`로 게이트하므로 **404에서 멈춘다**(확인함). 출하된 표면에서는 도달 불가. INV-1로 해당 행 자체가 존재하지 않는다. 계약 §6.2가 열거한 보호 대상 메서드 목록에서 이 둘이 빠져 있다는 점이 실제 결함이다.

부수 효과: `tombstone_entity("e-iso")`가 `False`를 반환한다(`get_entity`가 None이라). 격리 엔티티는 tombstone도 불가능하다.

---

### V-07 (LOW, 잠재) — `get_stats()`의 `density`·`connected_components`가 격리 노드를 포함한다

`entities`·`relations`·`by_type`은 올바르게 제외되지만, 두 그래프 지표는 필터되지 않은 `nx_graph`에서 계산된다.

증거 (`probe1.py`), 가시 노드 2 + 격리 노드 1, 간선 2:

```
P2 entities: 2   by_type: {'note': 2}      ← 제외 정상
P2 density: 0.333   components: 1          ← 격리 노드 포함 (필터 시 0.0 / 2)
```

계약 §6.2는 "별도 격리 건수 필드를 만들지 않는다(존재 노출 방지)"고 적었는데, 이 두 수치가 정확히 그 존재를 노출한다. 수치 부채널이며 내용 유출은 아니다.

---

### V-08 (LOW, 잠재) — 관계 질의가 격리 엔티티의 ID를 노출한다

관계는 자신의 `source_channel`로 필터되므로, `source_channel='manual'`인 관계가 격리 엔티티를 끝점으로 가지면 그대로 반환된다(`probe1.py` P5: `relation:links count: 2`). 노출되는 것은 엔티티 **ID**이며 이름·본문은 아니다.

---

### V-09 (LOW/INFO) — `slack/__init__.py` docstring이 사실과 다르다

"importing them pulls in urllib and a YAML parser that the core ingestion path does not need"라고 적혀 있으나, V-05대로 코어 임포트가 이미 둘 다 끌어온다. 문서가 실제 동작을 반대로 서술한다.

---

## 3. 검증 통과 항목

| # | 항목 | 증거 |
|---|---|---|
| P-01 | **ACL 선행(R12)** — 거부 채널에서 `history`/`replies` 호출 0회, 저장 메시지 0건. 합성·HTTP 양쪽 | `probe4.py` C, `test_acl.py::test_acl_before_fetch_order_is_enforced`, `test_mock_api.py::test_acl_gate_holds_over_http` |
| P-02 | **격리 스냅샷 메타데이터 한정(R16)** — 멤버 ID 없음, `member_count`만. 본문·표시명·토큰 없음 | `probe4.py` C: `{'channel_type':'private_channel', 'member_count':1, ...}` |
| P-03 | **거부 채널 본문 비영속** — DB+WAL+SHM 바이트 스캔에서 메시지 본문 미검출 | `probe4.py` C: `secret bytes in DB: False` |
| P-04 | **토큰 비영속(R27/R29)** — 성공 경로·인증 실패 경로 모두 DB+WAL+SHM에 토큰 바이트 없음, `xoxb` 문자열 자체가 없음 | `probe4.py` A/B: `token bytes in DB: False`, `'xoxb' anywhere: False` |
| P-05 | **격리(INV-1)** — 전체 동기화 후 `entities`/`relations`에 `work-slack` 0행 | `test_isolation.py::test_slack_sync_writes_nothing_into_the_graph` |
| P-06 | **재기동 후 경로 질의 격리 유지** — `_build_networkx`가 `source_channel`을 복원하므로 필터가 fail-open 하지 않음 | `probe1.py` P1: 재오픈 후 `No path found`, nx 속성 `work-slack` |
| P-07 | **FTS 경로 격리** — FTS5 활성 상태에서 격리 엔티티 미반환 | `probe1.py` P3: `fts_ready: True`, 결과 `['alpha','omega']` |
| P-08 | **체크포인트 안전(R18)** — 역행 불가, 미해소 항목 앞에서 정지, 전량 거부 시 미전진 | `probe5.py` I/J |
| P-09 | **live 차단(R31/R35)** — 비루프백 호출은 승인 없이 전부 `blocked:live_not_approved`, CLI 종료 코드 5 | `test_credentials.py::test_real_slack_is_blocked_without_approval`, 앞선 E2E 스모크 |
| P-10 | **자동화 부재(P4)** — launchd·cron·scheduler·watchdog·Timer·Socket Mode·Events API·RTM 참조 0건(문서 문장 제외) | 정적 스캔 |
| P-11 | **네트워크 경계** — `api.py`/`mock_api.py` 외 Slack 패키지 어디에도 소켓/HTTP 호출 없음. 로컬 질의 경로는 커넥터를 구성하지 않음 | 정적 스캔 + `cmd_query` 코드 독해 |
| P-12 | **Onyx 무변경** — Slack 패키지의 onyx 참조는 `onyx.acl`·`onyx.contract` 헬퍼 **읽기 재사용**뿐. client/worker/exporter 호출 없음 | 정적 스캔 |
| P-13 | **의존성 무변경** — `pyproject.toml` diff는 콘솔 스크립트 1줄뿐. `slack_sdk`는 어디에도 임포트되지 않음(docstring 언급만) | `git diff pyproject.toml`, 정적 스캔 |

### 테스트 실행 결과

```
tests/integrations/slack/                                    177 passed
tests/test_knowledge_graph_session.py, test_mcp_tools.py,
test_fts_search.py, test_cli.py, test_cli_groups.py,
test_main_entry.py, test_ask_chat_endpoints.py               208 passed
mnemosyne-query 종료 코드 회귀 (--stats/--examples/모듈 위임)   0 / 0 / 0
```

검토자에 의한 저장소 수정 없음 — `git status`는 wp-slack-adapter-cli 종료 시점과 동일하며, 탐침 스크립트는 전부 scratchpad에 있다.

---

## 4. 게이트 판정

| 게이트 | 판정 | 근거 |
|---|---|---|
| 독립 focused 테스트 | **통과** | 177 + 208 전부 통과 |
| 읽기 전용 보안 검토 | **통과** | 수정·비밀 열람·설치·외부 호출 없음 |
| 비밀/네트워크/Onyx 미접촉 | **통과** | P-04, P-11, P-12, P-13 |
| 명시적 채널/scope 격리 | **통과** (잠재 결함 V-06~V-08 동반) | P-05 ~ P-07 |
| ACL 선행 | **통과** | P-01 |
| 격리 메타데이터 한정 | **통과** | P-02, P-03 |
| 편집/삭제/reconcile 정확성 | **조건부** | V-02 |
| 체크포인트 안전 | **통과** | P-08 |
| 토큰 리댁션/비영속 | **통과** (V-03 동반) | P-04 |
| 계약 §10 거부 의미론 | **미충족** | **V-01** |

---

## 5. `gate-real-slack` 이전 필수 수정

1. **V-01** — ACL 단계 API 오류를 격리로 처리하고, 테스트를 예외가 아닌 격리 레코드·소스 상태로 재작성
2. **V-02** — 형식 위반 원격 항목이 섞이면 tombstone 0건으로 reconcile 중단
3. **V-03** — 비루프백 호스트에서 `X-OAuth-Scopes` 헤더 부재를 거부

## 6. 후속 권고 (차단 아님)

4. **V-04** — `list_messages`/`search_messages`에 revoked 검사를 저장소 계층으로 이동
5. **V-05 / V-09** — `slack/__init__.py` 즉시 재수출 제거 또는 `acl.py`의 onyx 지연 임포트, docstring 정정
6. **V-06** — `entity_history` 조회에 `entities` 조인으로 격리 술어 적용, 계약 §6.2 메서드 목록 보강
7. **V-07** — `density`/`connected_components`를 필터된 부분그래프에서 계산
8. **V-08** — 관계 질의에서 끝점이 격리된 관계 제외

## 7. 이월 상태 확인

`gate-real-slack`은 여전히 차단 상태가 타당하다. 실제 워크스페이스 자산(team/channel ID, 앱 설치, 토큰 주입), 비공개 채널/DM 주체 정책, 클라우드 LLM 승인, 재조정 주기는 모두 미결이며, 코드상 실제 Slack에 도달할 수 있는 경로는 존재하지 않는다(P-09).
