# Onyx Outbound 강제 설계 (Outbound Enforcement Design)

**문서 지위:** 구현 계약 (implementation contract). `wp-implementation-v3`는 이 문서에 정의된 범위만 구현한다.
**작성:** `wp-design-synthesis-v3` / `task_31177f4c8ff3`
**기준:** 작업 트리 `main @ ed8c332` + 현재 dirty 변경분 (미커밋)
**입력 보고서**

| 입력 | 출처 | 상태 |
|---|---|---|
| 보안 아키텍처 리뷰 (S1–S12, I1–I13, R1–R31) | `task_718fa9a5906c`, `scratchpad/SECURITY_ARCH_REVIEW_ONYX.md` | 완료 |
| 라이프사이클 리뷰 (L1–L4) | `task_9ef0cfd0b5e0` 본문 (`msg_21120bc97f9e`, `msg_eef34eef6bef`) — worker_done은 `dispatch_capability_invalid`로 거부되었으나 본문은 보존됨 | 내용 완료 / 전달 실패 |
| 재확인 dispatch | `task_c7c6e3853a89` | 본 문서 작성 시점 미반환 |

> **입력 조정 근거:** `task_c7c6e3853a89`는 `task_9ef0cfd0b5e0`의 재시도이며 동일 범위·동일 코드 기준이다. 원 보고서 본문 전체가 오케스트레이션 inbox에 보존되어 있고, 본 문서는 그 4개 결함(L1–L4)을 **현재 dirty 코드에 대해 직접 재검증**했다(§1). 따라서 재시도 보고서 없이도 설계 입력은 완결되어 있으며, 재시도 보고서가 도착하면 §1 표만 갱신하면 된다.

**검증 방법:** 읽기 전용. 구현 코드 미수정. 비밀·개인 노트 미열람. 의존성 미설치. Onyx 미접속.
**현재 테스트 기준선:** `python3 -m pytest tests/integrations/onyx/ -q` → **108 passed** (3.39s).

---

## 0. 이 문서가 답하는 것

1. 두 리뷰의 결함 중 **dirty 코드에서 이미 닫힌 것**과 **아직 열린 것**의 확정 (§1, §2)
2. 강제해야 할 **불변식** (§3)
3. 구현할 **최소 API** (§4)
4. **상태 전이** 정의 (§5)
5. **deny 사유 코드** 정본 (§6)
6. **preflight 및 credential 경계** (§7)
7. **집중 테스트 매트릭스** (§8)
8. 구현 순서·파일 범위·비범위 (§9, §10)

---

## 1. 현재 dirty 코드와의 재조정

두 리뷰는 `ed8c332`(당시 `mnemosyne/integrations/onyx/` clean) 기준이다. 이후 dirty 작업 트리에 392 insertions / 128 deletions이 이미 반영되어 있어, 리뷰 결과를 그대로 구현 지시로 쓰면 **중복 구현**이 발생한다. 아래는 현재 코드를 직접 읽어 판정한 결과다.

### 1.1 보안 리뷰 결함 (S1–S12)

| ID | 원 결함 | 현재 상태 | 근거 (현재 파일:라인) |
|---|---|---|---|
| S1 | outbound classification/ACL gate 부재 | **닫힘** | `mapper.py:100-102` → `_outbound_policy_error()` `mapper.py:134-168` |
| S2 | tombstone 엔티티가 발행 대상으로 선택됨 | **부분 닫힘** — 선택은 차단, **철회는 미구현** | `exporter.py:177-178` (SQL 술어), `mapper.py:138-139` (매퍼 deny). 철회 경로 없음 → **D1** |
| S3 | `Additional Attributes` 속성 덤프 | **닫힘** | `_build_sections`에서 제거됨, `mapper.py:172-199`는 타입별 allowlist만 렌더 |
| S4 | 미검증 `source_type` → outbound 재발행 | **열림** | `worker.py:385` 여전히 `envelope.source_type or _DEFAULT_ENTITY_TYPE`; `mapper.py:91-97` loop guard는 `sync_origin == "mnemosyne"`만 차단하고 인바운드 엔티티는 `sync_origin="onyx"`(`worker.py:465`) → **D2** |
| S5 | scope별 destination 바인딩 부재 | **부분 닫힘** — 능력(capability) 모델은 생김, **scope 바인딩은 없음** | `DestinationPolicy` `mapper.py:33-38`; 그러나 `cli.py:1136-1146`이 전역 `cfg.onyx` 하나로 모든 scope에 동일 정책 적용 → **D3** |
| S6 | `can_access` caller 측 fail-open | **닫힘** | `permissions.py:47-57` 양측 미지값 모두 `False` |
| S7 | outbound에 Envelope 계약 미적용 | **부분 닫힘** — 메타데이터는 채워짐, **검증은 없음** | `mapper.py:113-116` (`classification`/`visibility`/`sync_origin`/`do_not_reimport`); `validate_envelope` 호출 없음 → **D8** |
| S8 | 자기신고 `scope_id` 신뢰 | **닫힘** | `acl.py:80-85` scope mismatch quarantine; `worker.py:252-266` `_apply_mapping_policy` classification floor |
| S9 | transport/destination 검증 없음 | **부분 닫힘** | `client.py:85-95` https 강제 + host allowlist. 단 `cli.py:1133`의 `set(...) or None`이 빈 목록에서 allowlist를 무력화 → **D4-b** |
| S10 | `owner_only`/`open`이 스냅샷 검사 우회 | **부분 닫힘** — scope 바인딩은 선행하나 owner 식별은 여전히 없음 | `acl.py:86-90` → **D9** |
| S11 | CLI push 무게이트 | **부분 닫힘** — `--dry-run`도 config를 로드하도록 수정됨, **검토된 dry-run 기록 게이트는 없음** | `cli.py:1123` (`cfg` 로드가 분기 밖으로 이동) → **D4-a** |
| S12 | credential 처리 (PASS) | **유지** | `config.py:46-51` 환경변수 *이름*만 저장; `client.py` 헤더 전용 |

### 1.2 라이프사이클 리뷰 결함 (L1–L4)

| ID | 원 결함 | 현재 상태 | 근거 |
|---|---|---|---|
| L1 | ACL 재검증이 same-hash no-op **뒤**에 옴 | **닫힘** | `worker.py:174-201`이 ACL/quarantine을 먼저 수행하고, idempotency 판정은 `worker.py:217-230`으로 이동 |
| L2 | checkpoint가 quarantined/rejected/failed를 넘어 전진 | **부분 닫힘** | `worker.py:306-309`가 `INGESTED`/`NOOP`만 watermark 후보로 인정하고 `worker.py:321-324`가 미해결 오류를 기록. 그러나 **미해결 항목보다 뒤(신규)인 성공 항목이 watermark를 올려 미해결 항목을 영구히 추월**함 → **D6** |
| L3 | quarantine에 resolve/replay 전이 없음 | **열림** | `worker.py:490-512` 저장만, `cli.py:906-914` / `cli.py:1180-1200` 목록 조회만. resolve/replay 함수·명령 없음 → **D5** |
| L4 | 삭제가 scope-unsafe / 비멱등 / 사후 update가 tombstone 무효화 | **부분 닫힘** | scope 바인딩 `worker.py:347-351`; 멱등 tombstone `worker.py:535-536`; 사후 update 차단 `worker.py:203-216`. 그러나 **복권(reinstatement) 경로가 없어** tombstone 이후 해당 source는 영구 차단(막다른 상태) → **D5/§5.3** |

---

## 2. 남은 결함 (구현 대상)

우선순위: **P0 = 발행 차단 사유** (닫히기 전에는 외부 발행 불가), **P1 = 실운영 정합성**, **P2 = 견고성**.

### D1 — P0 — outbound 철회(withdrawal)가 존재하지 않음

발행 후 tombstone된 문서는 `exporter.py:177-178`의 SQL 술어에 의해 **다음 push에서 아예 조회되지 않는다.** 그 결과 Onyx 쪽 문서는 영구히 살아있다. 계약 §6.5(후속 발행에서의 suppression)는 미충족이며, `OnyxClient`에는 삭제/철회 메서드 자체가 없다(`client.py`의 유일한 발행 API는 `ingest`, `client.py:132`).
`sync_state.onyx_push_state`(`sync_state.py:72-86`)에 과거 발행 문서가 남아 있으므로 철회 대상 집합은 **이미 계산 가능**하다.

### D2 — P0 — Onyx 출처 엔티티가 재발행 가능

`worker.py:385`는 `source_type`을 allowlist 없이 엔티티 타입으로 사용한다. `source_type: "decision"` 인바운드 → `decision ∈ PUBLISHABLE_ENTITY_TYPES` → `mapper.py:91-97` loop guard는 `sync_origin == "mnemosyne"`만 차단하는데 인바운드 엔티티는 `sync_origin="onyx"`(`worker.py:465`)이므로 통과.
S3 수정으로 본문 덤프는 막혔지만 다음 경로는 여전히 유출된다: 엔티티 이름(= `envelope.title`, `worker.py:411`)이 `semantic_identifier`/섹션 제목으로 나가고(`mapper.py:181`), `external_uri`가 섹션 `link`(`mapper.py:193-196`)와 메타데이터(`mapper.py:120-123`)로 나간다.

### D3 — P0 — scope별 destination 바인딩 부재

`config.py:44-51`에는 `OnyxEndpoint` 하나만 있고 `cli.py:1136-1146`이 전역값으로 단일 `DestinationPolicy`를 만든다. 모든 scope가 같은 `cc_pair_id`, 같은 ceiling으로 발행된다. 불변식 I5(“destination은 라우팅되는 모든 문서보다 같거나 더 제한적”)를 scope 단위로 강제할 지점이 없다.

### D4 — P0 — preflight 게이트 없음 (a) / host allowlist fail-open (b)

(a) `cli.py:1111-1155`는 검토된 dry-run 기록 여부를 확인하지 않고 라이브 push를 수행한다. 계약 §7의 “신규 scope 최초 export 전 dry-run 검토 필수”를 강제하는 상태가 어디에도 없다.
(b) `cli.py:1133` `allowed_hosts=set(cfg.onyx.approved_hosts) or None` — `approved_hosts`가 비면 `set()` → falsy → `None` → `client.py:93-96`의 allowlist 검사 **전체가 비활성화**된다. 설정 누락이 곧 무제한 허용이다.

### D5 — P1 — quarantine resolve/replay 및 tombstone 복권 경로 없음

`worker.py:490-512`는 quarantine을 저장만 하고, `resolved_at`/`resolved_by` 컬럼(`worker.py:150-152`)을 쓰는 전이가 없다. CLI는 목록만 제공(`cli.py:906-914`, `cli.py:1180-1200`).
동시에 `worker.py:203-216`이 tombstone된 source의 재유입을 `rejected`로 막지만 **복권 API가 없어** 정당한 재게시도 영구 차단된다. 두 문제는 같은 “권한 있는 명시적 전이” 부재이므로 한 묶음으로 구현한다.

### D6 — P1 — checkpoint watermark가 미해결 항목을 추월

`worker.py:300-309`: 배치 `[E1 quarantined @10:00, E2 ingested @11:00]`에서 watermark는 `11:00`이 된다. E1은 재전달 범위 밖으로 빠져 영구 손실된다. 성공 항목만 후보로 삼는 것으로는 부족하며 **미해결 항목의 최소 시각(floor)** 이 필요하다.

### D7 — P1 — `map_entity`의 `KeyError` 경로

`mapper.py:113-114`는 게이트 통과 후 `properties["classification"]` / `properties["visibility"]`에 **직접 인덱싱**한다. 그러나 게이트(`mapper.py:141`, `mapper.py:159`)는 키 부재 시 `"private"` 기본값으로 판정한다. destination ceiling이 `private`이고 `supports_acl=True`이며 ACL이 신선한 구성에서는 **키가 없어도 게이트를 통과**하고 이후 `KeyError`가 발생한다. `push_scope`(`exporter.py:78-161`)에 예외 처리가 없어 scope 전체 push가 중단된다.

### D8 — P1 — outbound 문서가 Envelope 검증을 거치지 않음

`validate_envelope`(`contract.py:344-410`)는 인바운드에만 적용된다. outbound `MapResult`는 어떤 검증자도 통과하지 않으므로 §8이 요구하는 메타데이터 완전성이 구조적으로 보장되지 않는다.

### D9 — P2 — `owner_only` / `open` 모드의 소유자 미식별

`acl.py:86-90`은 scope 바인딩 후 두 모드를 즉시 통과시킨다. `owner_only` docstring이 약속한 “소유자 식별 불가 시 quarantine”은 구현되지 않았다.

### D10 — P2 — `exporter.py`에서 `SyncStateStore` 임포트 유실

diff에서 `from ...sync_state import SyncStateStore`가 제거되었고, `exporter.py:68`의 어노테이션으로만 남아 있다. `from __future__ import annotations`(`exporter.py:14`) 덕에 런타임은 무사하지만 `typing.get_type_hints` 및 린터(F821) 기준으로는 미정의 이름이다.

### D11 — P2 — tombstone SQL 술어가 문자열 `LIKE`

`exporter.py:177-178`은 `properties NOT LIKE '%"valid_to"%'`를 쓴다. 방향은 fail-closed(살아있는 행을 과하게 배제)이므로 안전하지만, 값 안에 해당 문자열이 있는 무관한 속성도 배제한다. `json_extract`가 정확하다.

### D12 — P2 — dry-run 출력이 문서 제목을 노출

`exporter.py:122-128`이 `title=mapped.title`을 `details`에 넣고 `cli.py`가 그대로 출력한다. 개인 노트 제목이 stdout/로그로 나간다.

### D13 — P2 — `onyx_source_index`가 scope-bound가 아님

`_lookup_source`(`worker.py:368-372`)는 `source_doc_id` 단독 조회이고 해당 컬럼이 PK다(`worker.py` 테이블 정의). 서로 다른 scope로 매핑된 두 커넥터가 같은 `source_doc_id`를 내면 인덱스 행이 덮어써져 앞선 scope의 provenance가 유실된다.

---

## 3. 불변식 (Invariants)

보안 리뷰의 I1–I13을 현재 코드 기준으로 재작성하고 라이프사이클 항목(I14–I18)을 추가한다. **Status**는 이 설계 구현 *전* 상태다.

| # | 불변식 | 강제 지점 | 현재 |
|---|---|---|---|
| I1 | `classification ∈ {private, confidential}` 또는 `visibility ≠ public`인 엔티티는 destination이 그 수준을 표현할 수 없으면 publishable이 되지 않는다. | `mapper._outbound_policy_error` | 충족 |
| I2 | `tombstoned_at`/`valid_to`가 있는 엔티티는 발행 대상으로 선택되지 않는다. | `exporter._query_scope_entities` + `map_entity` | 충족 |
| I3 | outbound 섹션 텍스트는 **명시적 publish allowlist**로만 구성된다. | `mapper._build_sections` | 충족 |
| I4 | `content_hash`는 allowlist 텍스트에 대해서만 계산되며 ACL·tombstone 필드는 해시 밖이다. | `compute_content_hash` 입력 | 충족 |
| I5 | destination은 **scope별로** 선택되며 그 ceiling은 라우팅되는 모든 문서보다 같거나 더 제한적이다. scope에 바인딩된 destination이 없으면 deny한다(전역 fallback 금지). | `DestinationRegistry.for_scope` | **미충족 (D3)** |
| I6 | publish base URL은 `https`(로컬 루프백 예외)이고 host는 **비어 있지 않은** approved 목록에 있어야 한다. 목록이 비면 라이브 push는 deny된다. | `OnyxClient.__init__` + `cli` | **부분 (D4-b)** |
| I7 | 모든 outbound 문서는 전송 전에 계약 형태로 검증되며 `sync_origin=mnemosyne`, `do_not_reimport=true`를 갖는다. | `mapper.map_entity` → `validate_outbound_document` | **부분 (D8)** |
| I8 | clearance 비교는 전역적이다. 어느 쪽이든 미지값이면 deny. | `permissions.can_access` | 충족 |
| I9 | `envelope.scope_id == mapping.scope_id`. 불일치는 추론이 아니라 quarantine. `mapping.default_classification`은 floor이며 완화될 수 없다. | `acl.should_quarantine` + `worker._apply_mapping_policy` | 충족 |
| I10 | `source_type`은 allowlist로 검증되며, 그 자체로 엔티티를 `PUBLISHABLE_ENTITY_TYPES`에 넣을 수 없다. **Onyx 출처 엔티티는 재발행 불가다.** | `worker._resolve_entity_type` + `mapper` origin guard | **미충족 (D2)** |
| I11 | `owner_only`/`open`도 검증된 scope↔connector 바인딩을 요구하며, `owner_only`는 식별된 소유자를 요구한다. | `acl.should_quarantine` | **부분 (D9)** |
| I12 | 신규 scope에 대한 라이브 push는 **동일 destination 지문에 대해 검토 기록된 dry-run**을 전제로 한다. dry-run은 resolved destination을 표시해야 한다. | `preflight` 저장소 + `_run_sync_onyx_push` | **미충족 (D4-a)** |
| I13 | credential은 env 해석 헤더에만 존재하며 payload·state·fixture·로그·지문(fingerprint)에 나타나지 않는다. | `OnyxClient` / `SyncConfig` / `PreflightStore` | 충족 (유지 필요) |
| I14 | 발행된 적 있는 문서가 tombstone되면 **다음 push에서 철회 또는 명시적 차단**이 발생한다. 조용한 방치는 금지다. | `exporter.push_scope` 철회 단계 | **미충족 (D1)** |
| I15 | durable watermark는 **미해결(quarantined/rejected/failed) 항목의 최소 시각을 절대 넘지 않는다.** | `worker._safe_watermark` | **미충족 (D6)** |
| I16 | quarantine 해제는 명시적·권한 있는 전이이며, replay는 validate와 ACL을 **다시** 수행한다. | `worker.resolve_quarantine` / `replay_quarantine` | **미충족 (D5)** |
| I17 | tombstone은 멱등이며, 복권은 actor·사유를 담은 명시적 전이로만 가능하다. | `worker._tombstone_entity` / `worker.reinstate` | **부분 (D5)** |
| I18 | 정책 판단은 예외를 던지지 않는다. 판단 불가는 예외가 아니라 deny다. | `mapper.map_entity` | **미충족 (D7)** |

---

## 4. 최소 API

새 파일은 **1개**(`destinations.py`)만 추가한다. 나머지는 기존 모듈에 함수/메서드를 더한다.

### 4.1 `mnemosyne/integrations/onyx/destinations.py` (신규)

```python
@dataclass(frozen=True)
class Destination:
    """하나의 승인된 발행 대상."""
    destination_id: str
    base_url: str                       # 해석된 값 (secret 아님)
    api_key_env: str                    # 이름만
    cc_pair_id_env: str                 # 이름만
    classification_ceiling: str = "public"    # 기본값은 가장 제한적인 공개 대상; 더 넓은 분류는 명시적으로 허용
    supports_acl: bool = False
    supports_withdrawal: bool = False
    acl_ttl_hours: int = 24
    approved_hosts: tuple[str, ...] = ()

    def policy(self) -> DestinationPolicy: ...
    def fingerprint(self) -> str:
        """secret 값을 제외한 destination 설정의 sha256 지문."""


class DestinationNotBound(ValueError): ...


class DestinationRegistry:
    @classmethod
    def from_config(cls, cfg: SyncConfig) -> "DestinationRegistry": ...
    def for_scope(self, scope_id: str) -> Destination:
        """바인딩이 없으면 DestinationNotBound. 전역 fallback 없음."""
```

설정 스키마 (`sync.yaml` 확장, 하위호환: 기존 단일 `onyx:` 블록은 `destination_id="default"`로 승격하되 **scope 바인딩이 없으면 라이브 push는 deny**):

```yaml
destinations:
  personal-readonly:
    base_url: "$ONYX_BASE_URL"
    api_key_env: ONYX_API_KEY
    cc_pair_id_env: ONYX_PERSONAL_CC_PAIR_ID
    classification_ceiling: internal
    supports_acl: false
    supports_withdrawal: false      # 대상 API 검증 전까지 false 고정
    approved_hosts: ["onyx.internal.example"]
scope_bindings:
  - scope_id: personal
    destination: personal-readonly
```

### 4.2 `mapper.py`

```python
@dataclass(frozen=True)
class DestinationPolicy:
    destination_id: str = ""
    classification_ceiling: str = "public"    # 기본은 가장 제한적인 public (fail-closed); 더 제한적 sink는 명시
    supports_acl: bool = False
    supports_withdrawal: bool = False
    acl_ttl_hours: int = 24

def outbound_deny_reason(
    entity_type: str,
    properties: Mapping[str, Any],
    policy: DestinationPolicy,
) -> str:
    """deny 코드(§6) 또는 허용 시 빈 문자열. 절대 예외를 던지지 않는다."""

def map_entity(..., destination_policy: DestinationPolicy | None = None) -> MapResult
```

변경점
- `_outbound_policy_error` → `outbound_deny_reason`으로 승격(공개, 테스트 가능), 반환값을 §6 코드로 통일.
- origin guard 확장: `sync_origin`이 `"mnemosyne"`이거나 `"onyx"`이거나 `do_not_reimport`가 참이면 deny (I10).
- `properties.get(...)` 사용으로 `KeyError` 제거 (I18, D7). 게이트가 기본값으로 판정한 값을 메타데이터에도 **같은 값**으로 기록한다(단일 해석 원칙).
- `map_entity`는 반환 직전 `validate_outbound_document(result)`를 호출하고 실패 시 `skipped=True, skip_reason="deny:contract_invalid"` (I7).

### 4.3 `contract.py`

```python
def validate_outbound_document(result: MapResult) -> list[str]:
    """document_id / semantic_identifier / sections / content_hash /
    metadata{source_system, entity_type, scope_id, classification,
    visibility, sync_origin=='mnemosyne', do_not_reimport is True}
    를 검사하고 위반 목록을 반환."""
```

### 4.4 `exporter.py`

```python
@dataclass
class PushOutcome:
    ...                       # 기존 필드 유지
    withdrawn: int = 0
    withdraw_blocked: int = 0

class OnyxPushExporter:
    def __init__(..., destination_policy: DestinationPolicy | None = None): ...

    def push_scope(self, scope_id: str) -> PushOutcome:
        """1단계: 살아있는 엔티티 발행. 2단계: 철회 대상 처리."""

    def _withdraw_pass(self, scope_id: str, outcome: PushOutcome) -> None: ...
    def _withdrawal_candidates(self, scope_id: str) -> list[PushState]:
        """onyx_push_state에서 원격 문서가 존재할 수 있는 상태
        (accepted/indexed/noop/failed/withdraw_pending/withdraw_blocked)를
        대상으로, (a) 엔티티가 tombstoned 이거나 (b) 엔티티가 더 이상
        존재하지 않거나 (c) 현재 정책상 deny되는 문서를 반환한다.
        pending/withdrawn은 대상에서 제외한다."""
```

철회 규칙
- `policy.supports_withdrawal is False` → 문서를 `withdraw_blocked` 상태로 기록하고 `outcome.withdraw_blocked += 1`. CLI는 **비영 종료 코드**로 끝낸다. 조용한 성공 금지 (I14).
- `True` → `client.withdraw(document_id)` 호출 후 `withdrawn` 기록.
- dry-run에서는 두 경우 모두 계수만 하고 client를 만들지 않는다.

`(c)` 항목이 §6의 “정책 변경 후 소급 suppression”을 처리한다. 즉 destination ceiling을 낮추면 다음 push에서 기존 발행분이 철회 대상이 된다.

### 4.5 `client.py`

```python
def withdraw(self, document_id: str) -> IngestResult:
    """대상 destination의 문서 철회. supports_withdrawal 이 참일 때만 호출된다."""
```

> **경계:** 본 프로그램에서는 Onyx에 접속하지 않는다. 따라서 `withdraw`의 실제 엔드포인트 검증은 유보 게이트(§10)이며, `supports_withdrawal`의 기본값과 모든 fixture 값은 **`False`** 다. 테스트는 spy client로만 호출 형태를 검증한다.

### 4.6 `permissions.py`

```python
def require_known(level: str | None) -> str:
    """미지 clearance면 ValueError. 호출부가 deny로 변환한다."""
```
`can_access`는 현행 유지(이미 fail-closed).

### 4.7 `worker.py`

```python
ALLOWED_SOURCE_TYPES: frozenset[str] = frozenset({
    "github", "slack", "gmail", "file", "confluence", "notion", "web", "document",
})

def _resolve_entity_type(envelope: Envelope) -> str:
    """allowlist 밖이면 _DEFAULT_ENTITY_TYPE. PUBLISHABLE_ENTITY_TYPES 와
    겹치는 값은 절대 반환하지 않는다."""

def _safe_watermark(
    committed: list[str], unresolved: list[str], previous: str
) -> str:
    """미해결 최소 시각 미만인 커밋 항목의 최대 시각. 없으면 previous."""

class ExportWorker:
    def resolve_quarantine(
        self, source_doc_id: str, scope_id: str, *, actor: str,
        decision: Literal["replay", "reject"], reason: str = "",
    ) -> str: ...

    def replay_quarantine(
        self, source_doc_id: str, scope_id: str, *, actor: str,
        envelope: Envelope,
    ) -> ProcessResult:
        """validate + ACL + 정책을 처음부터 다시 수행한다. 재검증 생략 금지."""

    def reinstate(
        self, source_doc_id: str, scope_id: str, *, actor: str, reason: str,
    ) -> str:
        """tombstone 해제. entity_history 에 change_type='reinstated' 와
        actor/reason 을 남기고 tombstoned_at/valid_to 를 제거한다."""
```

`onyx_quarantine` 테이블은 `(source_doc_id, scope_id)` 복합 PK와 `resolved_at`, `resolved_by`, `resolution`(`replayed|rejected`), `resolution_reason` 컬럼을 사용한다. 구 스키마는 `_init_tables`에서 보존적 재작성으로 이관한다.
`onyx_source_index`도 PK를 `(source_doc_id, scope_id)`로 이관한다 (D13). 마이그레이션은 `CREATE TABLE IF NOT EXISTS` 뒤에 `PRAGMA table_info` 확인 후 재작성한다.

### 4.8 preflight 저장소 (`sync_state.py` 확장)

```python
@dataclass
class PreflightRecord:
    scope_id: str
    destination_id: str
    destination_fingerprint: str
    reviewed_at: str
    actor: str
    candidate_count: int
    deny_count: int

class SyncStateStore:
    def record_preflight(self, record: PreflightRecord) -> None: ...
    def get_preflight(self, scope_id: str) -> Optional[PreflightRecord]: ...
```

테이블 `onyx_preflight(scope_id PRIMARY KEY, destination_id, destination_fingerprint, reviewed_at, actor, candidate_count, deny_count)`.
**지문에는 secret 값이 들어가지 않는다** — `base_url` 호스트, `cc_pair_id_env`/`api_key_env`의 *이름*, ceiling, `supports_acl`, `supports_withdrawal`, 정렬된 `approved_hosts`만 해시한다 (I13).

### 4.9 CLI

```
mnemosyne sync onyx preflight  --scope-id S [--config C] [--actor A]
mnemosyne sync onyx push       --scope-id S [--dry-run] [--config C]
mnemosyne sync onyx quarantine --scope-id S [--all]
mnemosyne sync onyx quarantine-resolve --scope-id S --source-doc-id D
                               --decision replay|reject --actor A [--reason R]
mnemosyne sync onyx reinstate  --scope-id S --source-doc-id D --actor A --reason R
```

- `preflight`는 항상 client를 만들지 않는다. destination_id, base_url **호스트**, cc_pair_id 환경변수 **이름**, 후보 수, deny 코드별 집계를 출력하고 `record_preflight`를 남긴다. 문서 제목·본문은 출력하지 않는다 (D12).
- `push`(라이브)는 다음을 모두 만족해야 진행한다: preflight 기록 존재 · `destination_fingerprint` 일치 · `reviewed_at` 이 `sync.preflight_ttl_hours`(기본 24) 이내 · `deny_count`가 기록 이후 증가하지 않음. 하나라도 어긋나면 **client 생성 전에** 비영 종료 (I12).
- `push --dry-run`은 preflight 기록을 요구하지 않는다(그것이 preflight의 입력이므로).

---

## 5. 상태 전이

### 5.1 Outbound 문서 (`onyx_push_state.status`)

```
        ┌──────────── deny (정책) ────────────┐
        │  push_state 행을 만들지 않는다;      │
        │  PushOutcome.skipped 로만 계수       │
        ▼
   (없음) ──record_push──▶ pending ──accepted──▶ accepted ──indexed──▶ indexed
                             │                                  │
                             └──── failed ──▶ failed ──재시도──▶ pending
                                                                 │
   accepted | indexed | noop | failed | withdraw_pending | withdraw_blocked
       ── 엔티티 tombstone 또는 정책 deny ───────────────────────────────┘
                              │
                              ▼
                       withdraw_pending
                       │             │
        supports_withdrawal=True    False
                       │             │
                       ▼             ▼
                   withdrawn   withdraw_blocked   (CLI 비영 종료)
```

규칙
- `withdraw_blocked`는 **종료 상태가 아니다.** 매 push마다 재평가되어 능력이 생기면 `withdrawn`으로 진행한다.
- `withdrawn` 문서는 엔티티가 복권(§5.3)되기 전에는 다시 `pending`이 되지 않는다.
- deny된 엔티티는 push_state를 만들지 않는다 → **client가 호출되지 않았음을 상태로 증명**할 수 있다.

### 5.2 Inbound envelope

```
received
   ├─ validate 실패 ─────────────────▶ rejected      (reject:contract_violation)
   ├─ mapping 없음/scope 불일치/ACL ─▶ quarantined
   │        └─ resolve(reject) ──────▶ quarantine_rejected  (기록 보존)
   │        └─ resolve(replay) ──────▶ received (전체 재검증)
   ├─ 대상 source 가 tombstoned ─────▶ rejected      (reject:tombstoned_source)
   ├─ 동일 content_hash ─────────────▶ noop          (ACL 재검증 이후에만)
   └─ 그 외 ────────────────────────▶ ingested
```

**순서 불변식 (I1/L1):** `validate → mapping/ACL/scope → tombstone 검사 → idempotency → ingest`. idempotency는 반드시 ACL 뒤에 온다. 현재 코드가 이 순서다(`worker.py:174-229`); 회귀 방지를 위해 테스트로 고정한다.

### 5.3 엔티티 철회/복권

```
Live ──handle_deletion(source_doc_id, scope_id)──▶ TombstoneWritten ──▶ HistoricalOnly
                                                        │
                              같은 인자로 재호출 ────────┘  (멱등: 새 history 행 없음,
                                                              반환값 'tombstoned_noop')
HistoricalOnly ──reinstate(actor, reason)──▶ Live
      │                                        └─ entity_history: change_type='reinstated',
      │                                           properties.reinstated_by / reinstated_reason
      └─ 인바운드 update 도착 시 ──▶ rejected (reject:tombstoned_source)
```

- `handle_deletion`은 `(source_doc_id, scope_id)` 쌍으로만 동작한다. scope 불일치는 `not_found`이며 tombstone하지 않는다.
- 복권은 tombstone을 지우고 **`onyx_push_state`의 `withdrawn` 문서를 `pending`으로 되돌린다**(다음 push에서 재발행되도록). 재발행 여부는 §5.1의 정책 게이트를 다시 통과해야 한다.

### 5.4 Checkpoint

```
batch 처리 후:
  unresolved = { ts(e) | e.status ∈ {quarantined, rejected, failed} }
  committed  = { ts(e) | e.status ∈ {ingested, noop} }
  floor      = min(unresolved)  (없으면 +∞)
  watermark' = max({ t ∈ committed | t < floor } ∪ {watermark})
```

- `watermark'`는 절대 감소하지 않는다.
- `unresolved`가 비었을 때만 `save()`가 `last_error`를 비운다. 그렇지 않으면 `record_error`가 미해결 사유를 남긴다.
- `documents_processed`는 `ingested`만 센다(현행 유지).

---

## 6. Deny / quarantine / reject 사유 코드

문자열은 **테스트가 의존하는 정본**이다. 사람이 읽는 상세는 `": "` 뒤에 덧붙인다(예: `deny:classification_exceeds_destination: source=confidential ceiling=public`). 테스트는 콜론 앞 코드만 단언한다.

### Outbound deny (`MapResult.skip_reason`)

| 코드 | 조건 | 불변식 |
|---|---|---|
| `deny:type_not_publishable` | `entity_type ∉ PUBLISHABLE_ENTITY_TYPES` | — |
| `deny:origin_not_republishable` | `sync_origin ∈ {mnemosyne, onyx}` 또는 `do_not_reimport` 참 | I10 |
| `deny:tombstoned` | `tombstoned_at` 또는 `valid_to` 존재 | I2 |
| `deny:classification_unknown` | classification이 4개 값 밖 (부재는 `private`로 간주 후 아래 규칙 적용) | I1 |
| `deny:classification_exceeds_destination` | `rank(ceiling) > rank(source)` | I1/I5 |
| `deny:visibility_unknown` | visibility가 허용 집합 밖 | I1 |
| `deny:destination_cannot_represent_acl` | `visibility ≠ public` 이고 `supports_acl` 거짓 | I5 |
| `deny:acl_snapshot_missing_or_stale` | ACL 스냅샷 부재/만료 | I5 |
| `deny:destination_ceiling_invalid` | 설정된 ceiling이 미지값 | I5 |
| `deny:contract_invalid` | `validate_outbound_document` 실패 | I7 |

### Destination / preflight deny (CLI, client 생성 전)

| 코드 | 조건 | 불변식 |
|---|---|---|
| `deny:destination_unbound` | scope에 바인딩된 destination 없음 | I5 |
| `deny:approved_hosts_empty` | 라이브 push인데 approved_hosts가 빔 | I6 |
| `deny:host_not_approved` | host가 목록 밖 | I6 |
| `deny:insecure_transport` | https 아님(로컬 루프백 제외) | I6 |
| `deny:preflight_missing` | preflight 기록 없음 | I12 |
| `deny:preflight_stale` | TTL 초과 | I12 |
| `deny:preflight_destination_changed` | 지문 불일치 | I12 |

### Quarantine (`ProcessResult.error`)

`quarantine:no_mapping` · `quarantine:scope_mismatch` · `quarantine:acl_snapshot_empty` · `quarantine:acl_snapshot_stale` · `quarantine:owner_unidentified`

### Reject

`reject:contract_violation` · `reject:tombstoned_source` · `reject:replay_unauthorized`

### Withdrawal

`withdraw:tombstoned` · `withdraw:entity_missing` · `withdraw:policy_denied` · `withdraw:blocked_no_capability`

---

## 7. Preflight 및 credential 경계

### 7.1 Preflight (I12)

| 단계 | 동작 | 금지 |
|---|---|---|
| 1 | `DestinationRegistry.for_scope(scope)` 해석 | 전역 fallback |
| 2 | 후보 엔티티 조회 + `outbound_deny_reason` 집계 | client 생성, 네트워크 |
| 3 | destination_id, base_url **호스트**, cc_pair_id **환경변수 이름**, 후보 수, deny 코드별 건수 출력 | 문서 제목·본문·URI 출력 |
| 4 | `record_preflight(fingerprint, actor, counts)` | secret 값 저장 |
| 5 | 라이브 push가 기록·지문·TTL·deny_count를 검사 | 검사 실패 시 진행 |

`deny_count` 증가 검사: preflight 이후 새로 deny되는 문서가 생겼다면(정책·데이터 변화) 재검토가 필요하다는 신호이므로 push를 중단한다. 반대로 감소는 허용한다.

### 7.2 Credential 경계 (I13, 현행 유지 + 확장)

| 규칙 | 강제 지점 |
|---|---|
| 설정은 환경변수 **이름**만 보관 | `config.py:46-51`, `destinations.Destination` |
| 값은 호출 시점 해석, 미설정 시 예외 | `config.py:55-61` |
| key는 `Authorization` 헤더에만 등장 | `client.py:200-206` |
| payload·state·fixture·로그에 key 없음 | `client._build_payload`, `sync_state`, 테스트 fixture |
| **preflight 지문에 key 값 없음** | `Destination.fingerprint` (신규) |
| 로그·CLI 출력에 문서 제목/본문/URI 없음 | `exporter.outcome.details`, `cli` (D12) |
| 테스트는 합성 값만 사용 | `tests/integrations/onyx/` |

---

## 8. 집중 테스트 매트릭스

기존 108 tests는 유지되어야 한다(회귀 기준선). 아래는 **신규**이며, 파일별로 배치한다.
표기: `T*` = 테스트 ID, `INV` = 검증 불변식, `D` = 닫는 결함.

### 8.1 `tests/integrations/onyx/test_outbound_policy.py` (확장)

| T | 케이스 | 단언 | INV | D |
|---|---|---|---|---|
| T01 | `classification=private`, ceiling `public` | `skipped`, 코드 `deny:classification_exceeds_destination` | I1 | — |
| T02 | `classification` 키 부재, ceiling `private`, `supports_acl=True`, 신선 ACL | **예외 없이** `MapResult` 반환, 메타데이터 `classification == "private"` | I18 | D7 |
| T03 | `visibility` 키 부재, 위와 동일 구성 | 예외 없음, 메타데이터 `visibility == "private"` | I18 | D7 |
| T04 | `classification="Public"` (대소문자) | `deny:classification_unknown` | I1 | — |
| T05 | `tombstoned_at` 존재 | `deny:tombstoned` | I2 | — |
| T06 | `valid_to`만 존재 | `deny:tombstoned` | I2 | — |
| T07 | `sync_origin="onyx"` 인 publishable 타입 | `deny:origin_not_republishable` | I10 | D2 |
| T08 | `sync_origin="mnemosyne"` | `deny:origin_not_republishable` | I10 | — |
| T09 | 임의 속성 (`api_token`, `note_body`, `access_snapshot`) 포함 | 섹션 텍스트에 미등장 | I3 | — |
| T10 | 속성 사전 퍼즈(무작위 키 100건) | allowlist 밖 키가 섹션에 절대 등장하지 않음 | I3 | — |
| T11 | `classification`/`acl_snapshot`만 변경 전후 `content_hash` | 동일 | I4 | — |
| T12 | 허용된 문서의 `MapResult` | `validate_outbound_document(result) == []`, `metadata["do_not_reimport"] is True`, `metadata["sync_origin"] == "mnemosyne"` | I7 | D8 |
| T13 | `ceiling="bogus"` | `deny:destination_ceiling_invalid` | I5 | — |
| T14 | `visibility="project"`, `supports_acl=False` | `deny:destination_cannot_represent_acl` | I5 | — |
| T15 | `visibility="project"`, `supports_acl=True`, `captured_at`가 TTL 초과 | `deny:acl_snapshot_missing_or_stale` | I5 | — |

### 8.2 `tests/integrations/onyx/test_destinations.py` (신규)

| T | 케이스 | 단언 | INV | D |
|---|---|---|---|---|
| T16 | 바인딩 없는 scope | `DestinationNotBound`; 전역값으로 대체되지 않음 | I5 | D3 |
| T17 | scope A/B가 서로 다른 destination에 바인딩 | 각기 다른 `cc_pair_id_env`·ceiling 사용 | I5 | D3 |
| T18 | `fingerprint()` | `api_key_env` 값(실제 키)이 지문 입력에 없음; 환경변수 값이 바뀌어도 지문 불변 | I13 | — |
| T19 | ceiling 기본값 | `"public"` (fail-closed; private/confidential/internal은 명시 설정 필요) | I1 | — |

### 8.3 `tests/integrations/onyx/test_withdrawal.py` (신규)

| T | 케이스 | 단언 | INV | D |
|---|---|---|---|---|
| T20 | 발행 성공 → 엔티티 tombstone → 재 push, `supports_withdrawal=True` | spy client의 `withdraw(document_id)` 1회 호출, `ingest` 미호출, 상태 `withdrawn` | I14 | D1 |
| T21 | 동일 시나리오, `supports_withdrawal=False` | 상태 `withdraw_blocked`, `outcome.withdraw_blocked == 1`, client 전혀 미호출 | I14 | D1 |
| T22 | T21 이후 능력을 켜고 재 push | `withdraw_blocked → withdrawn` 전이 | I14 | D1 |
| T23 | 철회 후 재 push | 중복 `withdraw` 호출 없음 (멱등) | I14 | D1 |
| T24 | ceiling을 낮춰 기존 발행분이 deny되는 경우 | `withdraw:policy_denied` 대상이 됨 | I5/I14 | D1 |
| T25 | dry-run에서 철회 대상 존재 | 계수만, client 미생성 | I14 | D1 |
| T26 | 복권 후 재 push | `withdrawn → pending → accepted` | I17 | D5 |

### 8.4 `tests/integrations/onyx/test_push.py` (확장)

| T | 케이스 | 단언 | INV | D |
|---|---|---|---|---|
| T27 | {public-live, private-live, public-tombstoned, private-tombstoned} 고정물 | `pushed=1`, `skipped=1`, tombstoned 행은 SQL에서 제외되고 private 행은 deny되며, spy client에 나머지 3개 document_id가 **한 번도** 전달되지 않음 | I1/I2 | — |
| T28 | deny된 엔티티 | `onyx_push_state`에 행이 생기지 않음 | §5.1 | — |
| T29 | `properties` 값 안에 `"valid_to"` 문자열이 든 살아있는 엔티티 | `json_extract` 기반 술어에서 발행됨(오배제 없음) | I2 | D11 |
| T30 | dry-run 출력 | `details`에 `title`이 없음; `document_id`와 코드만 | I13 | D12 |

### 8.5 `tests/integrations/onyx/test_client_boundary.py` (신규)

| T | 케이스 | 단언 | INV | D |
|---|---|---|---|---|
| T31 | `base_url="http://example.invalid"` | `ValueError`; 소켓 생성 전 실패 | I6 | — |
| T32 | allowlist 밖 host | `ValueError` | I6 | — |
| T33 | `approved_hosts=()` 로 라이브 push | `deny:approved_hosts_empty`, client 미생성 | I6 | D4-b |
| T34 | `http://127.0.0.1:8080` | 허용 (로컬 예외) | I6 | — |
| T35 | 전송 payload / 로그 레코드 | `api_key` 값이 어디에도 없음 | I13 | — |

### 8.6 `tests/integrations/onyx/test_preflight.py` (신규)

| T | 케이스 | 단언 | INV | D |
|---|---|---|---|---|
| T36 | preflight 기록 없이 라이브 push | 비영 종료, `deny:preflight_missing`, client 미생성, 문서 0건 전송 | I12 | D4-a |
| T37 | TTL 초과 기록 | `deny:preflight_stale` | I12 | D4-a |
| T38 | 지문 변경(ceiling 변경) 후 push | `deny:preflight_destination_changed` | I12 | D4-a |
| T39 | `preflight` 명령 출력 | destination_id·host·cc_pair_id **환경변수 이름**·deny 집계 포함; 제목/본문/URI 미포함 | I13 | D12 |
| T40 | preflight 이후 deny_count 증가 | push 중단 | I12 | D4-a |

### 8.7 `tests/integrations/onyx/test_worker.py` (확장)

| T | 케이스 | 단언 | INV | D |
|---|---|---|---|---|
| T41 | 최초 신선 ACL 수용 → 동일 hash 재전달, ACL이 만료/철회됨 | `quarantined` (noop 아님) | I1/L1 | — |
| T42 | 배치 `[quarantined@10:00, ingested@11:00]` | watermark ≤ `10:00`, 즉 `11:00`으로 전진하지 않음 | I15 | D6 |
| T43 | 배치 전원 실패 | watermark 불변, `last_error` 기록 | I15 | — |
| T44 | 실패 배치 후 전원 성공 배치 | `last_error` 비워짐, watermark 전진 | I15 | — |
| T45 | `source_type="decision"` 인바운드 | 엔티티 타입이 `PUBLISHABLE_ENTITY_TYPES` 밖 (`document`) | I10 | D2 |
| T46 | `source_type` ∈ {`""`, `"../../etc"`, `"Decision"`} | `_DEFAULT_ENTITY_TYPE`으로 강등, 예외 없음 | I10 | D2 |
| T47 | T45 이후 `push_scope` | 발행되지 않음(`deny:origin_not_republishable`), 제목·`external_uri` 모두 미전송 | I10 | D2 |
| T48 | quarantine → `resolve_quarantine(decision="replay")` | validate와 ACL이 **다시** 실행됨(spy), ACL이 여전히 불량이면 재-quarantine | I16 | D5 |
| T49 | quarantine → `resolve_quarantine(decision="reject")` | 기록은 보존되고 `resolution="rejected"`, 엔티티 미생성 | I16 | D5 |
| T50 | `actor=""` 로 resolve | `reject:replay_unauthorized` | I16 | D5 |
| T51 | 잘못된 scope로 `handle_deletion` | `not_found`, tombstone 없음 | I17 | — |
| T52 | 동일 인자로 `handle_deletion` 2회 | `entity_history`의 `deleted` 행 1건 유지, 두 번째 반환 `tombstoned_noop` | I17 | — |
| T53 | tombstone 후 내용 변경 인바운드 | `reject:tombstoned_source`, tombstone 유지 | I17 | — |
| T54 | `reinstate(actor, reason)` | `tombstoned_at`/`valid_to` 제거, `entity_history`에 `reinstated` 행 + actor/reason | I17 | D5 |
| T55 | 두 커넥터가 같은 `source_doc_id`를 서로 다른 scope로 전달 | 두 인덱스 행이 공존, 상호 덮어쓰기 없음 | I9 | D13 |

### 8.8 `tests/integrations/onyx/test_acl.py` / `test_permissions.py` (확장)

| T | 케이스 | 단언 | INV | D |
|---|---|---|---|---|
| T56 | `acl_mode="owner_only"`, 소유자 식별 불가 | `quarantine:owner_unidentified` | I11 | D9 |
| T57 | `acl_mode="open"`, scope 불일치 | `quarantine:scope_mismatch` (모드 분기보다 선행) | I9/I11 | — |
| T58 | `can_access(x, None)` / `""` / `"guest"` | 모두 `False` | I8 | — |
| T59 | `mapping.default_classification="confidential"`, envelope `"public"` | 저장값 `confidential` | I9 | — |

### 8.9 정적 경계

| T | 케이스 | 단언 | D |
|---|---|---|---|
| T60 | `exporter.py` 임포트 검사 | `typing.get_type_hints(OnyxPushExporter.__init__)`가 성공 | D10 |

**총 신규 60건.** 기존 108건과 합쳐 **168건**이 §9 완료 기준의 측정 단위다.

---

## 9. 구현 순서와 파일 범위

| 순서 | 항목 | 결함 | 파일 | 신규 테스트 |
|---|---|---|---|---|
| 1 | `map_entity` 예외 제거 + deny 코드 정본화 + origin guard | D2(매퍼측), D7 | `mapper.py` | T01–T11, T13–T15 |
| 2 | 인바운드 `source_type` allowlist | D2(워커측) | `worker.py` | T45–T47 |
| 3 | `validate_outbound_document` | D8 | `contract.py`, `mapper.py` | T12 |
| 4 | `destinations.py` + scope 바인딩 + config 스키마 | D3 | `destinations.py`(신규), `config.py`, `cli.py` | T16–T19 |
| 5 | host allowlist fail-closed | D4-b | `cli.py`, `client.py` | T31–T35 |
| 6 | preflight 저장소 + CLI 게이트 | D4-a, D12 | `sync_state.py`, `cli.py`, `exporter.py` | T36–T40, T30 |
| 7 | 철회 경로 | D1 | `exporter.py`, `client.py`, `sync_state.py` | T20–T26, T27–T28 |
| 8 | checkpoint 안전 watermark | D6 | `worker.py`, `checkpoint.py` | T42–T44 |
| 9 | quarantine resolve/replay + reinstate + CLI | D5 | `worker.py`, `cli.py` | T48–T50, T54, T26 |
| 10 | `json_extract` 술어, source_index PK, 임포트 복구 | D11, D13, D10 | `exporter.py`, `worker.py` | T29, T55, T60 |
| 11 | `owner_only` 소유자 식별 | D9 | `acl.py`, `config.py` | T56–T57 |

**허용 편집 경로:** `mnemosyne/integrations/onyx/`, `mnemosyne/cli.py`, `tests/integrations/onyx/`, `docs/ONYX_READ_ONLY_EXPORT_CONTRACT.md`, 본 문서.
**금지:** 기존 dirty 변경분의 되돌림, 개인 노트·비밀 파일 접근, 의존성 설치, Onyx 접속, git push/PR.

### 완료 기준 (gate-outbound-enforcement-v3)

1. `python3 -m pytest tests/integrations/onyx/ -q` → 168 passed (회귀 0).
2. 합성 부정 케이스에서 **client가 단 한 번도 호출되지 않음**을 spy로 증명 (T27, T28, T33, T36).
3. deny·quarantine·reject·withdraw 코드가 §6과 문자열 단위로 일치.
4. `git diff`에 secret 값, 개인 경로, 실제 호스트명이 없음.

---

## 10. 비범위 및 유보 게이트

이 설계는 **외부 발행을 활성화하지 않는다.** 다음은 명시적으로 범위 밖이며 별도 승인이 필요하다.

| 유보 항목 | 사유 |
|---|---|
| 실제 개인 Markdown ingest | provider·개인정보·보존 정책 승인 미완 |
| Onyx 철회/삭제 API의 실제 엔드포인트 검증 | 본 프로그램은 Onyx 미접속. `supports_withdrawal` 기본값은 `False` 고정 |
| scope별 destination의 실제 ACL·capability 승인 | 운영 승인 필요 |
| 검토된 실 dry-run 증적 | preflight 기록 *메커니즘*만 구현; 실제 검토는 사람이 수행 |
| macOS Keychain / 비밀 관리자 주입 | 현재는 환경변수 이름 참조까지만 |
| watcher/launchd 자동화 | 발행 게이트가 열린 뒤 별도 작업 |

또한 `docs/ONYX_READ_ONLY_EXPORT_CONTRACT.md` §9는 갱신이 필요하다. 현재 “outbound 미강제” 서술이 classification/tombstone만 언급하는데, 실제로는 destination 바인딩(D3), preflight(D4), 철회(D1), 재발행 금지(D2)가 함께 열려 있다. §5의 “`permissions.py`가 검색 시점 classification 필터를 구현한다”는 서술도 사실과 다르다(해당 함수들은 `mnemosyne/mcp/tools.py:265`의 `requires_review` 외에 생산 호출자가 없다).

---

## 부록 A — 참조 좌표

| 주제 | 위치 |
|---|---|
| outbound 정책 게이트 | `mnemosyne/integrations/onyx/mapper.py:134-168` |
| 섹션 allowlist | `mnemosyne/integrations/onyx/mapper.py:172-251` |
| tombstone SQL 술어 | `mnemosyne/integrations/onyx/exporter.py:170-183` |
| push 루프 | `mnemosyne/integrations/onyx/exporter.py:78-161` |
| ACL-before-noop 순서 | `mnemosyne/integrations/onyx/worker.py:174-230` |
| mapping classification floor | `mnemosyne/integrations/onyx/worker.py:252-266` |
| batch checkpoint | `mnemosyne/integrations/onyx/worker.py:269-328` |
| scope-bound 삭제 | `mnemosyne/integrations/onyx/worker.py:335-364` |
| 멱등 tombstone | `mnemosyne/integrations/onyx/worker.py:525-556` |
| quarantine 저장 | `mnemosyne/integrations/onyx/worker.py:490-512` |
| scope mismatch quarantine | `mnemosyne/integrations/onyx/acl.py:80-85` |
| clearance 비교 | `mnemosyne/integrations/onyx/permissions.py:47-57` |
| transport 검증 | `mnemosyne/integrations/onyx/client.py:85-95` |
| destination 설정 | `mnemosyne/integrations/onyx/config.py:44-51`, `config.py:138-152` |
| push CLI | `mnemosyne/cli.py:1111-1155` |
| quarantine CLI | `mnemosyne/cli.py:906-914`, `cli.py:1180-1200` |
| push state 스키마 | `mnemosyne/integrations/onyx/sync_state.py:72-86` |
| checkpoint 스키마 | `mnemosyne/integrations/onyx/checkpoint.py:69-78` |
