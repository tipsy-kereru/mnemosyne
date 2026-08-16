# Slack 통합 계약 (v1, 합성 전용)

- 문서 상태: **계약 확정 대기 → phase-1-contract 산출물**
- 조정자: `mnemosyne-slack-2026-08-16` / run `run_c5ad3a31d1a1`
- 작업 패키지: `wp-slack-contract` (task_8181c983f838)
- 이 문서를 통과시키는 게이트: `gate-contract`
- 이 문서가 차단하는 후속 작업: `wp-slack-core`(task_1e4126603556), `wp-slack-adapter-cli`(task_27b33383c0cb), `wp-slack-validation`(task_22f7b0f46027)

이 문서는 **구현 계약**이다. 후속 작업 패키지는 여기 적힌 파일·API·스키마·거부 코드·테스트만 만들고, 여기 없는 것은 만들지 않는다. 계약과 구현이 어긋나면 구현이 아니라 계약을 먼저 고친다.

---

## 0. 승인된 입력 정책 (재확인)

`.orch-coordinator/manifest.json`의 `assumptions` / `deferred_artifacts`를 계약 조항으로 고정한다.

| # | 승인된 결정 | 계약상 귀결 |
|---|---|---|
| P1 | 모든 Slack 작업은 현재 워크트리에 머문다. 기존 dirty 변경은 보존한다. | 신규 파일은 §8 목록으로 한정. 기존 파일 수정은 §8.2의 라인 앵커로 한정. |
| P2 | 합성 픽스처와 목(mock) Web API 응답으로 충분하다. 실제 워크스페이스 스모크는 이후 사람 승인 후. | `live` 커넥터는 코드상 존재하되 **기본 차단**(§7.4). |
| P3 | `work-slack`은 명시적이고 격리된다. 범위 없는(unscoped) 질의는 이를 제외한다. | §6 격리 불변식 INV-1/INV-2. |
| P4 | 수동 CLI만. launchd·watcher·스케줄러·Socket Mode·Events API 없음. | §9 CLI가 유일한 실행 진입점. 데몬·훅·타이머 금지. |
| P5 | 비밀/사적 노트를 읽지 않고, Slack/Onyx를 호출하지 않으며, 의존성을 설치하지 않고, 외부에 게시하지 않는다. | §7 자격증명 계약, §12 범위 외. `slack_sdk`·`requests` 추가 금지. 표준 라이브러리 `urllib`만. |
| P6 | 클라우드 LLM 추출은 호출 단위 opt-in이며 소스 전용 1차 구현에는 불필요하다. | v1은 **원문 저장까지만**. 엔티티 승격·요약·추출 없음(§12). |

이월(사람 승인 필요, v1에서 사용 금지): 실제 team/channel ID, Slack 앱 설치와 토큰 주입, 비공개 채널/DM 주체 정책, 클라우드 LLM 제공자 승인, 과거 편집/삭제 재조정 주기.

---

## 1. 핵심 아키텍처 결정

### D1. Slack 원문은 `entities` / `relations`에 들어가지 않는다 (v1)

Slack 메시지는 `slack_*` 전용 테이블에만 저장한다. 지식 그래프의 엔티티/관계 테이블에는 **단 한 행도** 쓰지 않는다.

근거: 저장소에는 `_build_where_clauses`를 거치지 않고 `entities`를 직접 읽는 표면이 이미 여럿 있다 — `mnemosyne/serve/handlers.py:78`, `mnemosyne/serve/app.py:244`, `mnemosyne/retrieval/engine.py:525`, `mnemosyne/retrieval/strategies/bm25.py:143`, `mnemosyne/retrieval/strategies/graph.py:86`, `mnemosyne/wiki/llm_wiki.py:607,2218`, `mnemosyne/graph/maintenance.py:62`. 이 파일들은 이번 프로그램의 편집 허용 경로가 아니다. 따라서 "질의 필터로 가린다"는 방식은 이번 스코프에서 **완결될 수 없다**. 쓰지 않는 것이 유일하게 닫힌 해법이다.

### D2. 그래프 측 격리 술어는 그래도 넣는다 (심층 방어)

D1이 성립하면 격리 술어는 이론상 죽은 코드다. 그럼에도 `mnemosyne/graph/knowledge_graph.py`에 `work-slack` 제외 술어를 넣는다. 신뢰 경계의 기본값을 "거부"로 고정해, 향후 누군가 승격 경로를 만들 때 **먼저 열어야만** 보이도록 한다. 인수 테스트는 합성 `work-slack` 엔티티를 직접 삽입해 이 술어가 실제로 막는지 검증한다(§11 T-ISO).

### D3. 소스 = 채널 바인딩 1개

"소스"는 `(team_id, channel_id) → scope_id` 바인딩 하나다. 워크스페이스 전체나 사용자 단위 소스는 없다.

### D4. 테이블 3개

체크포인트는 소스와 1:1이므로 별도 테이블을 만들지 않고 `slack_source`의 컬럼으로 둔다. 스레드는 `thread_ts`로 파생 가능하므로 별도 테이블을 만들지 않는다. 최종: `slack_source`, `slack_message`, `slack_quarantine`.

### D5. 편집은 덮어쓰기 (의도적 천장)

v1은 편집 시 본문을 덮어쓰고 `version`·`edited_ts`·`content_hash`만 남긴다. 편집 이력의 원문은 보존하지 않는다.
> 천장: 편집 감사(audit)가 필요해지면 `entity_history`(`knowledge_graph.py:129`)를 본뜬 `slack_message_history`를 추가한다. 삭제는 v1부터 tombstone이며 물리 삭제가 아니다.

### D6. 기존 Onyx 모듈 재사용

새로 만들지 않고 가져다 쓴다.

| 재사용 대상 | 출처 | 용도 |
|---|---|---|
| `compute_content_hash(sections)` | `mnemosyne/integrations/onyx/contract.py` | 메시지 content_hash |
| `AccessSnapshot` | `mnemosyne/integrations/onyx/contract.py:175` | ACL 스냅샷 표현 |
| `is_acl_fresh`, `DEFAULT_ACL_TTL_HOURS` | `mnemosyne/integrations/onyx/acl.py:27,49` | ACL 신선도(24h) 판정 |
| quarantine 레코드 형태 | `onyx/acl.py:31`, `onyx/worker.py:210` | `slack_quarantine` 스키마와 해소 절차 |
| checkpoint 워터마크 규칙 | `onyx/worker.py:389-409`, `onyx/checkpoint.py` | 미해소 항목을 넘어 전진하지 않음 |
| stdlib HTTP + 목 서버 패턴 | `onyx/client.py`, `onyx/mock_server.py` | `urllib` 기반 어댑터와 인프로세스 목 |
| 환경변수 *이름*만 설정에 기록 | `onyx/config.py:66,300` | Slack 토큰 처리 |

---

## 2. 최소 소스 생명주기

### 2.1 소스(채널 바인딩) 상태 기계

```
                 register
        [*] ──────────────▶ registered
                                │ acl verify (§4)
                 deny ◀─────────┼─────────▶ acl_verified
                   │                             │ sync
             quarantined                         ▼
                   │ resolve                   active ──── ttl 만료 ───▶ stale
                   └──────────▶ registered       │                        │
                                                 │ revoke                 │ acl 재확인
                                                 ▼                        └───▶ acl_verified
                                              revoked
```

상태 값(문자열 상수): `registered`, `acl_verified`, `active`, `stale`, `quarantined`, `revoked`.

규칙:

- **R1.** `registered` 상태의 소스는 메시지를 가져오지 않는다. `acl_verified` 이상이어야 fetch가 가능하다.
- **R2.** `stale`(ACL 스냅샷 TTL 초과)은 fetch를 거부한다. 실패 폐쇄(fail-closed).
- **R3.** `revoked` 소스는 fetch·질의 모두 거부한다. 저장된 메시지는 남되 `mnemosyne-slack query`에서 제외된다. 삭제는 `purge`(명시적)만.
- **R4.** `quarantined` 소스는 사람이 `quarantine resolve`로 풀기 전까지 재진입하지 않는다. 자동 승격 없음.
- **R5.** 상태 전이는 `SlackStore` 안에서만 일어난다. 다른 모듈이 `slack_source.status`를 직접 UPDATE하지 않는다.

### 2.2 문서(메시지) 상태 기계

```
[*] ──fetch──▶ active ──edit(hash 변경)──▶ active(version+1)
                 │
                 └──reconcile: 원격 부재──▶ tombstoned  (본문 보존, 물리 삭제 아님)
```

`upsert_message` 반환값: `"inserted" | "updated" | "noop"`.
`tombstone_message` 반환값: `"tombstoned" | "tombstoned_noop" | "not_found"` — 재호출은 무해(idempotent).

**R6.** tombstone된 메시지 키가 다시 fetch로 들어오면 `reject:tombstoned_source`로 거부한다(자동 부활 금지). 복원은 `quarantine resolve --resolution replayed`와 동등한 명시적 조작만.

---

## 3. Slack 스레드 아이덴티티

### 3.1 안정 ID

| 이름 | 형식 | 예 |
|---|---|---|
| `source_id` | `slack:{team_id}:{channel_id}` | `slack:T0FIXTURE:C0FIXTURE1` |
| `thread_key` | `slack:{team_id}:{channel_id}:{thread_ts}` | `slack:T0FIXTURE:C0FIXTURE1:1712345678.000100` |
| `message_key` | `slack:{team_id}:{channel_id}:{ts}` | `slack:T0FIXTURE:C0FIXTURE1:1712345690.000300` |

규칙:

- **R7.** 루트 메시지는 `thread_ts == ts`. 따라서 루트의 `thread_key == message_key`. 스레드는 별도 행이 아니라 `slack_message.thread_ts` 기준 파생 뷰다.
- **R8.** `ts`는 Slack의 정렬 가능한 십진 문자열이다. 검증 정규식 `^\d{10}\.\d{6}$`. 불일치는 `reject:invalid_ts`.
- **R9.** `ts`가 고정폭(`10.6`)이므로 사전순 비교 == 수치 비교다. 워터마크 비교·정렬은 문자열 비교를 그대로 쓴다. **단, 이 등가성은 R8의 정규식 검증이 선행될 때만 성립한다.** 그러므로 검증을 통과하지 않은 `ts`는 어떤 비교에도 참여시키지 않는다(`reject:invalid_ts`로 미해소 처리). 별도 정렬 키 함수는 만들지 않는다.
- **R10.** `content_hash = compute_content_hash([{"text": text}])`. 동일 텍스트는 동일 해시여야 하며, 그것이 `noop` 판정 근거다. 첨부·이모지 반응은 해시에 포함하지 않는다(v1은 텍스트만 저장).
- **R11.** `message_key`는 재계산 가능해야 한다. DB에 저장하되, 저장값과 재계산값이 다르면 `reject:identity_mismatch`.

### 3.2 스레드 조회

`SlackStore.list_messages(source_id, thread_ts=...)`는 `thread_ts` 일치 행을 `ts` 오름차순으로 반환한다. 루트가 tombstone되어도 답글은 남으며, 응답에 `thread_root_tombstoned: true`를 표시한다.

---

## 4. ACL 및 격리(quarantine) 계약

### 4.1 ACL은 fetch보다 먼저 (ACL-before-fetch)

**R12.** `SlackSyncEngine.sync()` / `.reconcile()`은 반드시 다음 순서를 지킨다.

```
1. store.get_source(source_id)            # 상태 확인 (R1~R4)
2. connector.channel_info(channel_id)     # ACL/채널 유형 확보
3. acl.acl_denial(info)                   # 거부 사유 판정
4. 거부면  → store.quarantine(...) 후 즉시 반환. history/replies 호출 금지.
5. 허용이면 → store.record_acl(...) 후에야 connector.history(...) 호출.
```

인수 테스트는 호출 순서를 기록하는 스파이 커넥터로 이를 검증한다(§11 T-ACL-3). `history`가 `channel_info`보다 먼저 호출되면 실패다.

### 4.2 허용되는 채널 유형

**R13.** v1 허용 집합은 공개 채널 단 하나다.

```python
ALLOWED_CHANNEL_TYPES = frozenset({"public_channel"})
```

`is_private`, `is_ext_shared`, `is_org_shared`, `is_im`, `is_mpim` 중 하나라도 참이면 거부한다. 비공개 채널·DM·MPIM·외부 공유 채널의 주체(principal) 정책은 이월 항목이므로 v1에서 **판단하지 않고 거부**한다.

### 4.3 ACL 스냅샷과 신선도

**R14.** ACL 스냅샷은 `conversations.members` 결과(사용자 ID 목록)와 `captured_at`으로 구성한다. `AccessSnapshot(users=members, groups=[], captured_at=...)`로 표현하고 신선도는 `onyx.acl.is_acl_fresh(snapshot, ttl_hours=24)`로 판정한다.

**R15.** 다음은 모두 거부(실패 폐쇄)다.

- 스냅샷 없음 → `deny:acl_missing`
- `members`가 빈 목록 → `deny:acl_empty`
- `captured_at` 없음/파싱 불가 → `deny:acl_stale`
- TTL(24h) 초과 → `deny:acl_stale`

`acl_mode`는 `require_snapshot`(기본)만 지원한다. Onyx의 `open` / `owner_only`는 v1에 없다.

### 4.4 격리 레코드

**R16.** `slack_quarantine.snapshot_json`에는 **메시지 본문, 사용자 표시 이름, 토큰, URL 쿼리스트링을 넣지 않는다.** 허용 필드는 `source_id`, `channel_id`, `team_id`, `channel_type`, `is_private`, `is_ext_shared`, `is_org_shared`, `member_count`(정수), `captured_at`, `reason`뿐이다. ACL 거부는 fetch 이전에 일어나므로 격리 레코드에는 애초에 본문이 존재하지 않는다.

**R17.** 격리 해소는 사람이 `mnemosyne-slack quarantine resolve --actor <이름> --resolution replayed|rejected --reason <사유>`로만 한다. 자동 해소·자동 재시도 없음.

---

## 5. 체크포인트 / 재조정(reconcile) 계약

### 5.1 워터마크

**R18.** 소스별 워터마크는 `slack_source.last_watermark`(문자열 `ts`)다. 전진 규칙은 `onyx/worker.py:389-409`와 동일하다.

```python
def safe_watermark(committed: list[str], unresolved: list[str], previous: str) -> str:
    """미해소 항목보다 앞선 지점까지만 전진한다."""
```

- 미해소(quarantined/rejected/failed) 항목이 하나라도 있으면, 워터마크는 **가장 이른 미해소 `ts`를 넘지 않는다.**
- 미해소가 없으면 `max(committed)`까지 전진한다.
- 어떤 경우에도 `previous`보다 뒤로 가지 않는다(단조 증가).

**R19.** `noop`은 커밋으로 취급한다(이미 저장된 내용이므로 재조회 불필요).

**R20.** 오류 발생 시 `record_error(source_id, redact(msg))`로 사유를 남기되 워터마크는 전진시키지 않는다.

### 5.2 편집 감지

**R21.** 편집은 두 신호 중 하나로 감지한다. (a) `content_hash` 변경, (b) 응답의 `edited.ts` 존재. 감지 시 `version += 1`, `edited_ts` 갱신, 본문 덮어쓰기(D5). 해시가 같고 `edited_ts`도 같으면 `noop`.

### 5.3 삭제 감지 — reconcile 전용

**R22.** `conversations.history`는 삭제를 보고하지 않는다. 따라서 삭제 감지는 **오직** `reconcile`에서만 일어난다. `sync`는 절대 tombstone을 만들지 않는다.

`reconcile(source_id, since, until="")` 절차:

```
1. §4.1 ACL 게이트 통과
2. 원격 [since, until] 구간을 전량 재열거 → remote_keys
3. 로컬 같은 구간의 active 메시지 → local_keys
4. local - remote  → tombstone_message(key, "reconcile:remote_absent")
5. remote - local  → upsert_message(...)  (누락분 보강)
6. 교집합 중 hash 불일치 → upsert_message(...) → "updated"
7. 워터마크는 R18 규칙으로만 전진
```

**R23.** `reconcile`은 `--since`를 반드시 요구한다. 전체 채널 재조정은 `--since` 최소값을 명시적으로 넘겨야 한다(실수로 전량 재조정하지 않도록).

**R24.** reconcile 중 원격 조회가 부분 실패하면 tombstone을 **하나도** 만들지 않고 중단한다. 부분 응답으로 삭제를 추론하지 않는다.

---

## 6. 로컬 질의 경계 계약

### 6.1 불변식

- **INV-1.** 동기화 후 `SELECT COUNT(*) FROM entities WHERE source_channel='work-slack'` = 0, `relations`도 동일. Slack 원문은 `entities`/`relations`에 존재하지 않는다.
- **INV-2.** `work-slack` 내용을 반환하는 읽기 경로는 `mnemosyne-slack query` **하나뿐**이다.
- **INV-3.** `mnemosyne-query`, MCP 도구, `mnemosyne/serve/*` HTTP 표면, retrieval 엔진, wiki 생성기는 `work-slack` 내용을 절대 반환하지 않는다. v1에서는 INV-1에 의해 자동으로 성립한다.

### 6.2 그래프 측 격리 술어 (심층 방어, D2)

`mnemosyne/graph/knowledge_graph.py`에 모듈 상수를 추가한다.

```python
ISOLATED_SOURCE_CHANNELS = frozenset({"work-slack"})
```

적용 지점(정확한 앵커는 §8.2):

| 함수 | 현재 위치 | 요구되는 동작 |
|---|---|---|
| `query()` | `:575` | 수정자 `@channel:work-slack`가 오면 즉시 `{"error": "slack_isolated", "hint": "mnemosyne-slack query", "results": [], "count": 0}` 반환 |
| `_build_where_clauses()` | `:698` | 모든 호출에 `{alias}.source_channel NOT IN (...)` 절을 무조건 추가 |
| `_find_entity_id_by_name()` | `:980` | 동일 제외 절 추가 (path 질의 입구) |
| `_query_path()` | `:879` | `nx.subgraph_view(...)`로 격리 노드를 제외한 부분그래프에서 최단경로 계산 |
| `get_entities_by_type()` | `:558` | 동일 제외 절 추가 |
| `get_active_entities()` | `:1112` | 동일 제외 절 추가 |
| `get_stats()` | `:1005` | entities/relations/by_type/scope 조인 카운트에서 제외. 별도 "격리 건수" 필드는 만들지 않는다(존재 노출 방지) |

**R25.** 거부는 조용한 빈 결과가 아니라 **명시적 오류 객체**여야 한다 — 단, 사용자가 `work-slack`을 *명시적으로 지목한 경우에만*. 범위 없는 질의는 조용히 제외한다(존재를 노출하지 않는다).

### 6.3 `mnemosyne-slack query` 반환 계약

```json
{
  "source_id": "slack:T0FIXTURE:C0FIXTURE1",
  "scope_id": "<scope>",
  "thread_ts": "1712345678.000100",
  "thread_root_tombstoned": false,
  "count": 2,
  "results": [
    {"message_key": "...", "thread_ts": "...", "ts": "...", "user": "U0...",
     "text": "...", "version": 2, "edited_ts": "...", "tombstoned": false}
  ]
}
```

`thread_ts` / `thread_root_tombstoned`는 `--thread-ts`를 준 경우에만 포함한다(§3.2).

**R26.** `revoked` 소스와 `tombstoned` 메시지는 기본 제외한다. tombstone 포함은 `--include-tombstoned` 명시 시에만.

---

## 7. 자격증명 계약

### 7.1 토큰 취득

**R27.** 봇 토큰은 **환경변수에서만** 읽는다. 기본 변수명 `MNEMOSYNE_SLACK_BOT_TOKEN`. 설정 파일에는 값이 아니라 **변수 이름만** 기록한다(`onyx/config.py:66` 패턴). 토큰을 DB·설정·로그·CLI 출력·격리 스냅샷에 쓰지 않는다.

**R28.** 토큰 부재 시 `blocked:credential_missing`으로 종료 코드 3. 부분 동작·익명 조회 없음.

### 7.2 리댁션

**R29.** `redact(text)`는 `xox[abprse]-[A-Za-z0-9-]+`를 `xox*-***REDACTED***`로 치환한다. 모든 로그 기록, 모든 예외 메시지, 모든 CLI 출력, `record_error()` 저장값에 적용한다. 리댁션 미적용 경로는 계약 위반이다.

### 7.3 스코프 제한

**R30.** 필요한 최소 스코프는 `channels:read`, `channels:history`, `users:read`뿐이다. 응답 헤더 `X-OAuth-Scopes`에 다음이 하나라도 있으면 **호출을 중단**하고 `reject:overbroad_scope`로 실패한다.

```python
FORBIDDEN_SCOPES = ("groups:history", "groups:read", "im:history", "im:read",
                    "mpim:history", "mpim:read", "files:read", "chat:write")
```

과잉 권한 토큰은 v1에서 사용 불가다. 이는 P5(비밀 미접근)와 §4.2(공개 채널 한정)의 토큰 측 강제다.

### 7.4 live 차단 (fail-closed)

**R31.** `WebApiConnector`는 `base_url`이 루프백(`127.0.0.1`/`localhost`)이 아니면 `live_approved=True`가 필요하다. 기본값은 `False`이며, v1에서 이를 참으로 만드는 경로는 존재하지 않는다(승인 파일 경로는 계약상 예약만 하고 구현하지 않는다). 위반 시 `SlackLiveBlocked` → 종료 코드 5.

**R32.** 결과적으로 v1에서 네트워크는 루프백 목 서버로만 나간다. 실제 Slack 호출은 `gate-real-slack` 해제 이후 별도 작업 패키지다.

---

## 8. 정확한 영향 파일 / API / 스키마

### 8.1 신규 파일

| 경로 | 소유 WP | 내용 |
|---|---|---|
| `mnemosyne/integrations/slack/__init__.py` | wp-slack-core | 공개 심볼 재수출 |
| `mnemosyne/integrations/slack/identity.py` | wp-slack-core | 안정 ID, ts 검증/정렬, content_hash |
| `mnemosyne/integrations/slack/acl.py` | wp-slack-core | 채널 유형 분류, ACL 거부 판정 |
| `mnemosyne/integrations/slack/schema.py` | wp-slack-core | 3개 테이블 DDL (표준 라이브러리만 import — `KnowledgeGraph` 초기화 경로가 여기만 부른다) |
| `mnemosyne/integrations/slack/store.py` | wp-slack-core | 생명주기 전이, upsert/tombstone, 체크포인트, 격리 |
| `mnemosyne/integrations/slack/redact.py` | wp-slack-core | `redact()` — store가 `record_error`에서 이미 필요하므로 core 소유 |
| `mnemosyne/integrations/slack/connector.py` | wp-slack-core | `SlackConnector` 프로토콜 + `SyntheticConnector` |
| `mnemosyne/integrations/slack/sync.py` | wp-slack-core | `SlackSyncEngine`, `safe_watermark` |
| `mnemosyne/integrations/slack/config.py` | wp-slack-adapter-cli | `SlackConfig`, 스코프 검사 (`redact`는 `redact.py`에서 import) |
| `mnemosyne/integrations/slack/api.py` | wp-slack-adapter-cli | `WebApiConnector` (stdlib `urllib`) |
| `mnemosyne/integrations/slack/mock_api.py` | wp-slack-adapter-cli | 인프로세스 목 Slack Web API |
| `mnemosyne/integrations/slack/cli.py` | wp-slack-adapter-cli | `mnemosyne-slack` 진입점 |
| `tests/integrations/slack/__init__.py` 외 §11 목록 | 각 WP | 합성 인수 테스트 |

### 8.2 기존 파일 수정 (허용된 것만)

| 파일 | 앵커 | 변경 |
|---|---|---|
| `mnemosyne/graph/knowledge_graph.py` | 모듈 상단 | `ISOLATED_SOURCE_CHANNELS` 상수 추가 |
| " | `_init_session_schema` `:153`, `chat_store.init_chat_schema` 호출 직후 `:254` | `init_slack_schema(self.conn)` 호출 (멱등·가산, longdoc/chat 선례와 동일) |
| " | `query` `:575` | `@channel:work-slack` 명시 요청 시 `slack_isolated` 오류 반환 |
| " | `_build_where_clauses` `:698` | 제외 절 무조건 추가 |
| " | `_query_path` `:879` | 격리 노드 제외 부분그래프에서 경로 계산 |
| " | `_find_entity_id_by_name` `:980` | 제외 절 추가 |
| " | `get_entities_by_type` `:558`, `get_active_entities` `:1112`, `get_stats` `:1005` | 제외 절 추가 |
| `mnemosyne/graph/cli.py` | `QUERY_SYNTAX` `:11`, `main` `:37` | 경계 안내 문구 추가, 결과가 `slack_isolated`면 종료 코드 2 |
| `pyproject.toml` | `[project.scripts]` `:48` | `mnemosyne-slack = "mnemosyne.integrations.slack.cli:main"` 한 줄 추가. **의존성 블록은 건드리지 않는다.** |

### 8.3 명시적 무변경

- `mnemosyne/ingest/ingester.py` — **변경 없음.** Slack은 파일/URL/텍스트 인제스트 경로를 타지 않는다. 이 파일이 `wp-slack-core`의 허용 경로에 있더라도 v1에서 수정할 이유가 없다.
- `mnemosyne/integrations/onyx/**` — 읽기 전용 재사용만. 수정 금지.
- `mnemosyne/serve/**`, `mnemosyne/mcp/**`, `mnemosyne/retrieval/**`, `mnemosyne/wiki/**` — 변경 없음. INV-1이 이들을 자동으로 안전하게 만든다.

### 8.4 스키마 (DDL)

지식 그래프와 동일한 SQLite 파일에 멱등 생성한다.

```sql
CREATE TABLE IF NOT EXISTS slack_source (
    source_id           TEXT PRIMARY KEY,          -- slack:{team}:{channel}
    team_id             TEXT NOT NULL,
    channel_id          TEXT NOT NULL,
    channel_type        TEXT NOT NULL DEFAULT '',  -- public_channel | private_channel | im | mpim | ext_shared
    scope_id            TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'registered',
    acl_mode            TEXT NOT NULL DEFAULT 'require_snapshot',
    acl_users           TEXT NOT NULL DEFAULT '[]',-- JSON 배열 (사용자 ID만)
    acl_captured_at     TEXT,
    is_private          INTEGER NOT NULL DEFAULT 0,
    is_ext_shared       INTEGER NOT NULL DEFAULT 0,
    is_org_shared       INTEGER NOT NULL DEFAULT 0,
    last_watermark      TEXT NOT NULL DEFAULT '',
    last_sync_at        TEXT,
    documents_processed INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT NOT NULL DEFAULT '',
    registered_at       TEXT NOT NULL,
    revoked_at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_slack_source_scope  ON slack_source(scope_id);
CREATE INDEX IF NOT EXISTS idx_slack_source_status ON slack_source(status);

CREATE TABLE IF NOT EXISTS slack_message (
    message_key   TEXT PRIMARY KEY,                -- slack:{team}:{channel}:{ts}
    source_id     TEXT NOT NULL,
    thread_ts     TEXT NOT NULL,
    ts            TEXT NOT NULL,
    user_id       TEXT NOT NULL DEFAULT '',
    text          TEXT NOT NULL DEFAULT '',
    subtype       TEXT NOT NULL DEFAULT '',
    edited_ts     TEXT,
    content_hash  TEXT NOT NULL,
    version       INTEGER NOT NULL DEFAULT 1,
    first_seen_at TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    tombstoned_at TEXT,
    tombstone_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_slack_msg_source ON slack_message(source_id, ts);
CREATE INDEX IF NOT EXISTS idx_slack_msg_thread ON slack_message(source_id, thread_ts, ts);

CREATE TABLE IF NOT EXISTS slack_quarantine (
    source_doc_id     TEXT NOT NULL,               -- source_id 또는 message_key
    source_id         TEXT NOT NULL,
    reason            TEXT NOT NULL,
    quarantined_at    TEXT NOT NULL,
    snapshot_json     TEXT NOT NULL DEFAULT '{}',  -- R16 허용 필드만
    resolved          INTEGER NOT NULL DEFAULT 0,
    resolved_at       TEXT,
    resolved_by       TEXT,
    resolution        TEXT,                        -- replayed | rejected
    resolution_reason TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source_doc_id, source_id)
);
CREATE INDEX IF NOT EXISTS idx_slack_quarantine_source ON slack_quarantine(source_id);
```

**R33.** DDL은 `CREATE TABLE IF NOT EXISTS`와 `sqlite_master` 가드만 사용한다. `ALTER`·백필·기존 테이블 변경 금지. 실패해도 기존 그래프 초기화를 막지 않아야 한다(`longdoc_schema.py`, `chat_store.py` 선례).

### 8.5 공개 API

```python
# identity.py
SOURCE_CHANNEL: str = "work-slack"
CONTRACT_VERSION: str = "slack-1.0"
TS_PATTERN: re.Pattern                                  # ^\d{10}\.\d{6}$

def source_id(team_id: str, channel_id: str) -> str
def message_key(team_id: str, channel_id: str, ts: str) -> str
def thread_key(team_id: str, channel_id: str, thread_ts: str) -> str
def parse_source_id(value: str) -> tuple[str, str]      # (team_id, channel_id)
def is_valid_ts(value: str) -> bool                     # R8/R9의 전제. 통과 후에는 문자열 비교로 정렬
def message_hash(text: str) -> str                      # compute_content_hash([{"text": text}])

# acl.py
ALLOWED_CHANNEL_TYPES: frozenset[str]

@dataclass
class ChannelInfo:
    channel_id: str; name: str = ""
    is_private: bool = False; is_ext_shared: bool = False; is_org_shared: bool = False
    is_im: bool = False; is_mpim: bool = False
    members: list[str] = field(default_factory=list)
    captured_at: str | None = None

def classify_channel(info: ChannelInfo) -> str
def acl_denial(info: ChannelInfo, *, ttl_hours: int = 24, now: datetime | None = None) -> str
    """빈 문자열이면 허용. 그 외에는 §10의 deny:* 코드."""

# store.py
SOURCE_REGISTERED = "registered"; SOURCE_ACL_VERIFIED = "acl_verified"
SOURCE_ACTIVE = "active"; SOURCE_STALE = "stale"
SOURCE_QUARANTINED = "quarantined"; SOURCE_REVOKED = "revoked"

@dataclass
class SlackSource: ...      # 8.4 컬럼 1:1
@dataclass
class SlackMessage: ...     # 8.4 컬럼 1:1
@dataclass
class SlackQuarantineRecord: ...

# schema.py (stdlib import만)
def init_slack_schema(conn: sqlite3.Connection) -> None   # 멱등, knowledge_graph에서 호출

# redact.py
def redact(text: str) -> str

class SlackStore:
    def __init__(self, db_path: str | Path) -> None
    def register_source(self, team_id: str, channel_id: str, scope_id: str, *,
                        acl_mode: str = "require_snapshot") -> SlackSource
    def get_source(self, source_id: str) -> SlackSource | None
    def list_sources(self, *, status: str | None = None) -> list[SlackSource]
    def record_acl(self, source_id: str, info: ChannelInfo) -> SlackSource
    def set_status(self, source_id: str, status: str, *, error: str = "") -> SlackSource
    def revoke_source(self, source_id: str, reason: str) -> bool
    def upsert_message(self, msg: SlackMessage) -> str             # inserted|updated|noop
    def tombstone_message(self, message_key: str, reason: str) -> str
    def list_messages(self, source_id: str, *, thread_ts: str | None = None,
                      since: str = "", until: str = "",
                      include_tombstoned: bool = False, limit: int = 200) -> list[SlackMessage]
    def search_messages(self, source_id: str | None, term: str, *, limit: int = 50) -> list[SlackMessage]
    def save_checkpoint(self, source_id: str, watermark: str, processed: int) -> None
    def record_error(self, source_id: str, error: str) -> None     # redact() 적용 후 저장
    def quarantine(self, source_id: str, source_doc_id: str, reason: str,
                   snapshot: dict[str, Any]) -> SlackQuarantineRecord
    def list_quarantine(self, *, resolved: bool = False) -> list[SlackQuarantineRecord]
    def resolve_quarantine(self, source_doc_id: str, source_id: str, *,
                           actor: str, resolution: str, reason: str) -> bool
    def purge_source(self, source_id: str) -> int                  # 명시적 물리 삭제 (유일)
    def close(self) -> None

# connector.py
@dataclass
class FetchedMessage:
    ts: str; thread_ts: str; user: str = ""; text: str = ""
    edited_ts: str | None = None; subtype: str = ""

class SlackConnector(Protocol):
    def channel_info(self, channel_id: str) -> ChannelInfo: ...
    def history(self, channel_id: str, *, oldest: str = "", limit: int = 200) -> Iterator[FetchedMessage]: ...
    def replies(self, channel_id: str, thread_ts: str, *, oldest: str = "") -> Iterator[FetchedMessage]: ...

class SyntheticConnector:                    # 픽스처 dict 기반, 네트워크 없음
    def __init__(self, fixture: dict[str, Any]) -> None

# sync.py
STATUS_INGESTED = "ingested"; STATUS_UPDATED = "updated"; STATUS_NOOP = "noop"
STATUS_TOMBSTONED = "tombstoned"; STATUS_QUARANTINED = "quarantined"
STATUS_REJECTED = "rejected"; STATUS_FAILED = "failed"

@dataclass
class SyncResult:
    source_id: str; total: int = 0
    ingested: int = 0; updated: int = 0; noop: int = 0; tombstoned: int = 0
    quarantined: int = 0; rejected: int = 0; failed: int = 0
    watermark: str = ""; errors: list[str] = field(default_factory=list)

def safe_watermark(committed: list[str], unresolved: list[str], previous: str) -> str

class SlackSyncEngine:
    def __init__(self, store: SlackStore, connector: SlackConnector, *,
                 now: Callable[[], datetime] | None = None) -> None
    def sync(self, source_id: str, *, limit: int = 200) -> SyncResult
    def reconcile(self, source_id: str, *, since: str, until: str = "") -> SyncResult

# config.py
DEFAULT_TOKEN_ENV = "MNEMOSYNE_SLACK_BOT_TOKEN"
REQUIRED_SCOPES: tuple[str, ...]
FORBIDDEN_SCOPES: tuple[str, ...]

class SlackCredentialError(Exception): ...
class SlackScopeError(Exception): ...

@dataclass
class SlackSourceConfig:
    team_id: str; channel_id: str; scope_id: str
    acl_mode: str = "require_snapshot"

@dataclass
class SlackConfig:
    token_env: str = DEFAULT_TOKEN_ENV
    sources: list[SlackSourceConfig] = field(default_factory=list)
    @classmethod
    def load(cls, path: str | Path) -> "SlackConfig"
    def resolve_token(self) -> str                       # 환경변수만. 없으면 SlackCredentialError

def assert_scopes_allowed(granted: Iterable[str]) -> None    # 위반 시 SlackScopeError

# api.py
class SlackApiError(Exception):
    code: str
class SlackLiveBlocked(SlackApiError): ...

class WebApiConnector:                                   # SlackConnector 구현
    def __init__(self, token: str, *, base_url: str = "https://slack.com/api",
                 timeout: int = 30, max_retries: int = 3,
                 live_approved: bool = False) -> None

# mock_api.py
class MockSlackServer:
    def __init__(self, *, port: int = 0, host: str = "127.0.0.1",
                 expected_token: str = "xoxb-test", fixture: dict[str, Any] | None = None,
                 fail_first_n: int = 0, fail_error: str = "ratelimited") -> None
    base_url: str
    def start(self) -> None
    def stop(self) -> None
```

---

## 9. CLI 계약 (`mnemosyne-slack`)

`pyproject.toml`의 `[project.scripts]`에 진입점 한 줄만 추가한다. 모든 하위 명령은 **수동 실행**이며 JSON을 stdout에 출력한다. 모든 출력은 `redact()`를 통과한다.

| 명령 | 필수 인자 | 동작 |
|---|---|---|
| `init` | `--config` (선택) | 테이블 생성 + 설정 파일의 모든 소스 등록. ACL 확인·fetch 없음 |
| `source register` | `--team-id --channel-id --scope-id` | 소스 등록(`registered`). ACL 확인은 하지 않음 |
| `source list` | — | 소스와 상태/워터마크 나열 |
| `source revoke` | `--source-id --reason` | `revoked` 전이. 데이터는 보존 |
| `sync` | `--source-id --connector synthetic\|mock\|live` | §4.1 게이트 후 증분 수집. 삭제 감지 안 함(R22) |
| `reconcile` | `--source-id --since TS [--until TS] --connector …` | 구간 재조정. 유일한 tombstone 생성 경로 |
| `status` | `[--source-id]` | 워터마크·마지막 동기화·상태별 집계·격리 건수 |
| `quarantine list` | `[--resolved]` | 격리 레코드 나열 |
| `quarantine resolve` | `--source-doc-id --source-id --actor --resolution --reason` | 사람에 의한 해소 |
| `query` | `--source-id [--thread-ts] [--grep] [--since] [--limit] [--include-tombstoned]` | 격리된 Slack 내용의 **유일한** 읽기 경로 |
| `purge` | `--source-id --confirm` | 유일한 물리 삭제. `--confirm` 없으면 거부 |

공통 옵션: `--db-path`, `--config`, `--json`(기본 참), `--fixture PATH`(synthetic/mock 전용).

**R34.** 종료 코드

| 코드 | 의미 |
|---|---|
| 0 | 성공 |
| 1 | 예기치 못한 오류 |
| 2 | 정책 거부 (`deny:*`, `slack_isolated`) |
| 3 | 자격증명 문제 (`blocked:credential_missing`, `reject:overbroad_scope`) |
| 4 | 대상 없음 (소스/메시지 미존재) |
| 5 | live 차단 (`blocked:live_not_approved`) |

**R35.** `--connector live`는 v1에서 항상 코드 5로 종료한다. 이는 버그가 아니라 계약이다(§7.4).

---

## 10. 거부 의미론 (전체 코드 목록)

거부는 예외 문자열이 아니라 **고정 코드**다. 코드는 접두사로 계층을 표현한다.

| 코드 | 발생 지점 | 결과 |
|---|---|---|
| `deny:source_unregistered` | `sync`/`reconcile` 진입 | fetch 없음, 코드 4 |
| `deny:source_revoked` | 상태 검사 | fetch·질의 거부, 코드 2 |
| `deny:channel_type` | `acl_denial` | 채널 유형 비허용. **fetch 이전** 격리, 코드 2 |
| `deny:acl_missing` | `acl_denial` | 스냅샷 없음, 격리, 코드 2 |
| `deny:acl_empty` | `acl_denial` | 멤버 목록 비어 있음, 격리, 코드 2 |
| `deny:acl_stale` | `acl_denial` | TTL 24h 초과/파싱 불가, 격리, 코드 2 |
| `deny:scope_mismatch` | `sync` | 소스 `scope_id`와 요청 scope 불일치, 코드 2 |
| `reject:invalid_ts` | `identity` | `ts` 형식 위반, 해당 메시지만 미해소 처리 |
| `reject:identity_mismatch` | `store.upsert_message` | 저장된 `message_key`와 재계산 불일치 |
| `reject:tombstoned_source` | `store.upsert_message` | tombstone된 키의 자동 부활 시도 |
| `reject:contract_version` | `store` 초기화 | `CONTRACT_VERSION` 불일치 |
| `reject:overbroad_scope` | `api` 응답 헤더 검사 | 금지 스코프 포함, 즉시 중단, 코드 3 |
| `blocked:credential_missing` | `config.resolve_token` | 토큰 환경변수 부재, 코드 3 |
| `blocked:live_not_approved` | `WebApiConnector` | 비루프백 URL + 미승인, 코드 5 |
| `quarantine:<deny 코드>` | `store.quarantine` | 격리 레코드의 `reason`. 사람 해소 전까지 재진입 없음 |
| `reconcile:remote_absent` | `reconcile` | tombstone 사유 |
| `slack_isolated` | `KnowledgeGraph.query` | `@channel:work-slack` 명시 요청 거부, 코드 2 |

**R36.** 거부는 모두 **부분 성공을 만들지 않는다.** ACL 거부는 fetch 자체를 막고, 스코프 거부는 첫 응답에서 중단하며, 자격증명 거부는 DB를 열지 않는다.

**R37.** 거부 사유 문자열에 채널명·사용자명·메시지 본문·토큰을 포함하지 않는다. 식별자(ID)와 코드만 담는다.

---

## 11. 합성 인수 테스트 (필수)

모두 `tmp_path` 임시 SQLite와 픽스처만 사용한다. **네트워크 호출 없음**(목 서버는 루프백만). 실제 Slack·Onyx 호출 없음. 새 의존성 없음.

### `tests/integrations/slack/test_identity.py`
- **T-ID-1** `source_id`/`thread_key`/`message_key` 형식과 결정성(동일 입력 → 동일 출력).
- **T-ID-2** `parse_source_id(source_id(t, c)) == (t, c)` 왕복.
- **T-ID-3** 잘못된 `ts`(`"abc"`, `"1712345678"`, `"1712345678.0001"`)는 `is_valid_ts` False.
- **T-ID-4** 검증을 통과한 `ts` 목록의 문자열 정렬 결과가 `float` 정렬 결과와 동일함(R9의 등가성 단언). 검증 실패값이 섞이면 등가성이 깨짐도 함께 단언.
- **T-ID-5** 동일 텍스트 → 동일 `message_hash`, 한 글자 변경 → 다른 해시.

### `tests/integrations/slack/test_acl.py`
- **T-ACL-1** 공개 채널 + 신선한 멤버 스냅샷 → `acl_denial() == ""`.
- **T-ACL-2** `is_private` / `is_im` / `is_mpim` / `is_ext_shared` / `is_org_shared` 각각에 대해 대응하는 `deny:channel_type` 반환(5개 파라미터화).
- **T-ACL-3 (핵심)** 스파이 커넥터로 호출 순서를 기록해, 거부되는 채널에서 `history`/`replies`가 **한 번도** 호출되지 않음을 단언. 허용 채널에서는 `channel_info`가 `history`보다 먼저 호출됨을 단언.
- **T-ACL-4** `captured_at`이 25시간 전 → `deny:acl_stale`. 23시간 전 → 허용.
- **T-ACL-5** 멤버 목록이 비면 `deny:acl_empty`.
- **T-ACL-6** 격리 레코드 `snapshot_json`에 메시지 본문·표시 이름·토큰 문자열이 없음을 단언(R16).

### `tests/integrations/slack/test_store.py`
- **T-ST-1** 생명주기 전이 허용/금지 표를 파라미터화 검증(예: `revoked → active` 금지).
- **T-ST-2** `upsert_message` 3회 호출: `inserted` → `noop` → 텍스트 변경 후 `updated`(+`version==2`).
- **T-ST-3** `tombstone_message` 2회: `tombstoned` → `tombstoned_noop`. 본문은 여전히 DB에 존재(물리 삭제 아님).
- **T-ST-4** tombstone된 키 재삽입 시 `reject:tombstoned_source`.
- **T-ST-5** `init_slack_schema`를 두 번 호출해도 예외 없음(멱등).
- **T-ST-6** `purge_source`만 행을 삭제한다. `revoke_source`는 삭제하지 않는다.
- **T-ST-7** `record_error`가 저장한 문자열에 `xoxb-` 토큰이 남지 않음(R29).

### `tests/integrations/slack/test_sync_synthetic.py`
- **T-SY-1** 픽스처 12개 메시지(루트 3 + 답글 9) 전량 동기화 → `ingested==12`, 워터마크 == 최대 `ts`.
- **T-SY-2** 즉시 재동기화 → 전량 `noop`, 워터마크 불변.
- **T-SY-3** 픽스처의 한 메시지 텍스트 변경 후 동기화 → `updated==1`, `version==2`, `edited_ts` 기록.
- **T-SY-4** `sync`는 원격에서 사라진 메시지를 tombstone하지 **않는다**(R22).
- **T-SY-5** `reconcile --since`로 같은 상황 → `tombstoned==1`, 사유 `reconcile:remote_absent`.
- **T-SY-6 (핵심)** 중간 메시지 하나가 `reject:invalid_ts`로 미해소일 때, 워터마크가 그 `ts`를 **넘지 않음**(R18).
- **T-SY-7** 비공개 채널 픽스처 → `quarantined==1`, `slack_message` 행 수 0.
- **T-SY-8** reconcile 도중 커넥터가 2페이지째에서 예외 → tombstone 0건, 워터마크 불변(R24).
- **T-SY-9** `safe_watermark`가 `previous`보다 되돌아가지 않음(단조성).

### `tests/integrations/slack/test_isolation.py`
- **T-ISO-1 (핵심, INV-1)** 전체 동기화 후 `SELECT COUNT(*) FROM entities WHERE source_channel='work-slack'` == 0, `relations`도 0.
- **T-ISO-2** `source_channel='work-slack'` 엔티티를 **직접 삽입**한 뒤 `kg.query("search:secret")` 결과에 없음.
- **T-ISO-3** `kg.query("entity:note[x]@channel:work-slack")` → `{"error": "slack_isolated", "count": 0}`.
- **T-ISO-4** `kg.query("path:a,b")`가 격리 노드를 경유하지 않음(격리 노드가 유일 경로면 `No path found`).
- **T-ISO-5** `kg.get_stats()`의 `entities`/`by_type`/scope 카운트에 격리 엔티티가 포함되지 않음.
- **T-ISO-6** `get_entities_by_type`, `get_active_entities`, `_find_entity_id_by_name`이 격리 엔티티를 반환하지 않음.
- **T-ISO-7** `mnemosyne-slack query`는 같은 데이터를 정상 반환(격리가 기능을 죽이지 않음을 확인).

### `tests/integrations/slack/test_credentials.py`
- **T-CR-1** 환경변수 미설정 → `SlackCredentialError`, CLI 종료 코드 3.
- **T-CR-2** 설정 YAML에 토큰 *값*을 넣으면 로드가 실패하거나 무시됨(변수 이름만 허용).
- **T-CR-3** `redact("Bearer xoxb-123-abc")`에 `xoxb-123-abc`가 남지 않음. 로그 캡처(`caplog`)에도 남지 않음.
- **T-CR-4** `X-OAuth-Scopes`에 `groups:history` 포함 → `SlackScopeError` / `reject:overbroad_scope`, 코드 3.
- **T-CR-5 (핵심)** `WebApiConnector(base_url="https://slack.com/api", live_approved=False)`의 모든 메서드가 `SlackLiveBlocked`를 던짐. 루프백 URL은 통과.
- **T-CR-6** 예외 메시지·`SyncResult.errors`·CLI stdout 어디에도 토큰이 없음.

### `tests/integrations/slack/test_mock_api.py`
- **T-MK-1** 커서 페이지네이션 2페이지가 합쳐져 전량 반환.
- **T-MK-2** `ratelimited` 1회 후 성공 → 재시도로 복구, 시도 횟수 기록.
- **T-MK-3** `invalid_auth` → `SlackApiError(code="invalid_auth")`, 재시도 없음.
- **T-MK-4** `not_in_channel` / `channel_not_found` → 격리, fetch 중단.
- **T-MK-5** 목 서버 바인드 주소가 `127.0.0.1`임을 단언(외부 노출 방지).

### `tests/integrations/slack/test_cli.py`
- **T-CLI-1** `source register` → `source list` JSON 형태와 상태.
- **T-CLI-2** `sync --connector synthetic --fixture …` 종료 코드 0과 요약 JSON 키 집합.
- **T-CLI-3** `sync --connector live` → 종료 코드 5(R35).
- **T-CLI-4** `purge` `--confirm` 없이 → 거부, 행 삭제 없음.
- **T-CLI-5** `quarantine resolve`에 `--actor` 누락 → 인자 오류, 상태 변화 없음.
- **T-CLI-6** `mnemosyne-query --query "search:x@channel:work-slack"` → 종료 코드 2.

### 게이트 기준

- 위 테스트 전부 통과.
- `python -m py_compile`이 신규/수정 파일 전부에서 통과.
- 테스트 실행 중 루프백 외 소켓 연결 0건.
- `git diff --name-only`가 §8의 파일 집합을 벗어나지 않음.

---

## 12. 명시적 범위 외 (v1에서 만들지 않음)

1. **Onyx 연동 일체.** Slack 내용을 Envelope으로 감싸거나 `onyx_*` 테이블에 넣지 않는다. Onyx 모듈은 읽기 전용 재사용만.
2. **자동 실행.** launchd·cron·watcher·데몬·Claude 훅·스케줄러 없음. Socket Mode·Events API·webhook 수신 없음.
3. **엔티티/관계 승격.** Slack 내용에서 엔티티·관계를 만들지 않는다. `entities`/`relations` 쓰기 0건(INV-1).
4. **LLM 사용.** 요약·추출·임베딩·wiki 생성 없음. 클라우드 제공자 호출 없음.
5. **비공개 표면.** 비공개 채널·DM·MPIM·외부/조직 공유 채널. 유형 판정 후 무조건 거부.
6. **첨부/파일.** 파일·이미지·스니펫 다운로드 없음. `files:read` 스코프 금지.
7. **사용자 프로필 확장.** 표시 이름·이메일·아바타 저장 없음. 사용자 ID만.
8. **아웃바운드.** 메시지 게시·반응 추가·채널 참여 없음. `chat:write` 금지.
9. **실제 워크스페이스 호출.** `gate-real-slack` 해제 전까지 코드 5로 차단.
10. **의존성 추가.** `slack_sdk`·`requests`·`httpx` 금지. 표준 라이브러리 `urllib`만.
11. **MCP/HTTP/wiki 노출.** `mnemosyne/mcp/**`, `mnemosyne/serve/**`, `mnemosyne/wiki/**`, `mnemosyne/retrieval/**` 무변경.
12. **편집 이력 보존.** D5의 의도적 천장. 필요해지면 별도 작업 패키지.
13. **다중 워크스페이스 병합.** `team_id`가 다른 소스는 서로 완전히 독립이며 교차 조회 없음.
14. **FTS5 인덱싱.** `slack_message` 전문 검색은 `LIKE` 기반 `search_messages`로 충분. FTS 가상 테이블 추가 없음.

---

## 13. 계약이 남긴 미결 사항 (조정자 판단 필요)

| # | 사안 | 계약의 기본 선택 | 뒤집으려면 |
|---|---|---|---|
| Q1 | 편집 이력 원문 보존 (D5) | 보존 안 함, 덮어쓰기 | `slack_message_history` 추가를 `wp-slack-core`에 포함 |
| Q2 | `mnemosyne/ingest/ingester.py` 수정 | 무변경(§8.3) | 인제스트 경로 경유가 필요한 이유 제시 |
| Q3 | 격리 술어를 죽은 코드로 둘 것인가 (D2) | 심층 방어로 유지 | 유지 비용이 문제면 삭제 가능하나 INV-1 위반 시 방어선 소실 |
| Q4 | `reconcile` 자동 주기 | 없음(수동 전용, P4) | `gate-real-slack` 이후 별도 패키지 |
| Q5 | 워크스페이스 스모크 테스트 | 차단(R31) | 사람 승인 + 실제 team/channel ID + 토큰 주입 절차 |

---

## 14. 참고

- 저장소 구조: [`ARCHITECTURE.md`](../ARCHITECTURE.md)
- 재사용 대상 계약: [`docs/ONYX_MNEMOSYNE_INTEGRATION_PLAN.ko.md`](ONYX_MNEMOSYNE_INTEGRATION_PLAN.ko.md), [`docs/ONYX_READ_ONLY_EXPORT_CONTRACT.md`](ONYX_READ_ONLY_EXPORT_CONTRACT.md)
- 아웃바운드 강제 설계(경계 참고): [`docs/ONYX_OUTBOUND_ENFORCEMENT_DESIGN.ko.md`](ONYX_OUTBOUND_ENFORCEMENT_DESIGN.ko.md)
- 소스 채널 값 정의: `mnemosyne/schema/base.md:49`. `work-slack`은 기존 `slack`과 구분되는 예약 값이다(`slack` = Onyx 경유 유입, `work-slack` = 이 직접 통합 전용). **v1은 이 파일을 수정하지 않는다** — INV-1에 의해 `work-slack` 엔티티가 애초에 생성되지 않으므로 스키마 문서에 값을 추가할 근거가 아직 없다. 승격 경로가 열릴 때 함께 갱신한다.

> Onyx 계획서 §10은 "Mnemosyne이 Slack 인증과 커넥터를 직접 재구현하는 것"을 초기 배포 제외 항목으로 적고 있다. 이 계약은 그 경계를 깨는 것이 아니라, **Onyx와 무관한 로컬 전용·수동·격리 경로**를 별도로 정의한다. 두 경로는 저장 위치(`entities` vs `slack_message`), 소스 채널(`slack` vs `work-slack`), 실행 방식(자동 export vs 수동 CLI)에서 완전히 분리된다. 이 분리가 무너지면 계약 위반이다.
