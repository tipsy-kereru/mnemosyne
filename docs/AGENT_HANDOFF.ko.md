# Mnemosyne 작업 인수인계

**기준일:** 2026-08-06  
**대상 저장소:** `/Users/kereru/Development/mnemosyne`  
**현재 상태:** 개인 Obsidian 기반 CLI 경계와 Onyx outbound enforcement는 문서화·구현·synthetic 검증 완료. 실제 개인 문서 ingest와 외부 Onyx export는 운영 승인 전까지 차단됨.

이 문서는 다른 코딩 에이전트가 별도 설명 없이 작업을 이어가기 위한 기준 문서다. “확인된 사실”과 “계획”을 섞어 해석하지 말 것.

## 1. 최종 목표

```text
Obsidian 개인 Markdown -> Mnemosyne 개인 SQLite graph + 생성 Wiki -> Onyx 읽기 전용 색인/검색
```

- Obsidian Markdown은 사람이 관리하는 원본이다.
- Mnemosyne SQLite와 raw 저장소는 iCloud/OneDrive Vault 밖에 둔다.
- 생성 Wiki는 원본 Markdown과 별도 폴더에 둔다.
- 개인·회사·프로젝트 데이터의 scope와 저장 경계를 분리한다.
- Onyx 연동은 우선 읽기 전용 export로 한정한다.
- provider, 보존 정책, 개인정보 전송 승인이 끝나기 전에는 개인 문서를 LLM이나 외부 Onyx로 보내지 않는다.
- ACL과 tombstone은 `scope_id`만으로 처리하지 않는다. 허용되지 않은 문서는 outbound에서 deny 또는 quarantine한다.

## 2. 지금까지 실제로 완료된 작업

### CLI 및 로컬 경계

- `mnemosyne ingest add/update`에 `--db-path`, `--raw-root` 추가
- `mnemosyne ingest update`에 `--source-channel` 추가
- add/update에 `--quiet` 추가
- `mnemosyne graph query`와 standalone `mnemosyne-query`에 `--db-path` 연결
- 관련 CLI routing 회귀 테스트 추가

개인 runtime을 기본 전역 DB와 분리해 실행할 수 있다. 실제 개인 경로를 사용할 때도 DB와 raw root는 동기화 Vault 밖의 명시적 경로를 사용해야 한다.

### Onyx 계약 및 통합 계획

- [ONYX_MNEMOSYNE_INTEGRATION_PLAN.ko.md](./ONYX_MNEMOSYNE_INTEGRATION_PLAN.ko.md)에 실행 단계와 현재 검증 상태를 반영했다.
- [ONYX_READ_ONLY_EXPORT_CONTRACT.md](./ONYX_READ_ONLY_EXPORT_CONTRACT.md)에 stable ID, content hash, provenance, ACL, tombstone, provider/privacy gate를 기록했다.
- Onyx → Mnemosyne inbound worker에 ACL-before-noop, scope binding, checkpoint safety, tombstone idempotency/reinstatement guard를 반영했다.
- Mnemosyne → Onyx outbound에 classification/visibility/ACL freshness/tombstone deny, explicit section allowlist, live-row suppression, destination URL validation을 반영했다.
- 외부 destination capability/ACL 승인, withdrawal 검증, provider/privacy 승인, reviewed dry-run gate는 아직 남아 있다.

### 개인정보 경계

- private vault의 실제 노트 내용을 ingest하지 않았다.
- API key, bearer token, Onyx connector ID 값을 읽거나 저장하지 않았다.
- 실제 외부 provider 호출과 Onyx export를 실행하지 않았다.
- 기존 Joplin/Obsidian migration 결과를 자동으로 재분류하거나 회사 노트를 추가하지 않았다.

## 3. 검증 결과

권한 확장 환경에서 확보한 결과:

```text
Onyx + CLI scoped suite: 216 passed, 5 deselected
CLI 중심 suite: 100 passed, 0 failed
독립 reviewer suite: 195 passed, 2 deselected
```

버전 표기는 Obsidian 연동 및 대규모 마이너 변경사항을 반영하여 `0.10.0`으로 갱신되었으며, 기존 하드코딩된 `0.1.0` CLI 버전 테스트도 동적 `__version__` 및 `sys.executable` 검증으로 보정하여 테스트 suite가 전수 통과(100% pass)하도록 정돈되었다.

Sandbox에서의 일부 실패는 홈 디렉터리 SQLite 생성, localhost bind, pytest cache 쓰기 권한 제한으로 발생한 환경 오류였다. 권한 확장 재실행 결과를 기준으로 판단한다.

## 4. 현재 차단된 게이트

### 필수 차단: external destination and approval gates

outbound mapper/exporter의 synthetic private/restricted/tombstoned 차단, ACL-before-noop,
scope-bound quarantine, withdrawal/suppression, reinstatement history, 그리고
scope-bound operational approval gate는 구현되었고 `tests/integrations/onyx/` 169개
테스트로 고정했다.

실제 Onyx export는 다음이 확인되기 전까지 차단한다.

- scope별 destination ACL/classification capability 승인
- target Onyx API의 withdrawal 또는 후속 suppression 동작 검증
- provider/privacy/retention 승인 기록
- reviewed dry-run과 live-export preflight 기록
- credential environment/secret 주입 방식 확인

## 5. 작업 트리와 보존해야 할 파일

현재 작업 트리는 의도적으로 dirty하다. 기존 변경을 reset, checkout, clean으로 삭제하지 말 것.

- `mnemosyne/cli.py`
- `mnemosyne/graph/cli.py`
- `mnemosyne/ingest/cli.py`
- `mnemosyne/obsidian.py`
- `mnemosyne/ingest/update.py`
- `tests/test_obsidian_sync.py`
- `tests/test_cli.py`
- `tests/test_cli_groups.py`
- `obsidian-plugin/mnemosyne-sync/main.ts`
- `obsidian-plugin/mnemosyne-sync/sync_queue.ts`
- `obsidian-plugin/mnemosyne-sync/sync_queue.test.ts`
- `obsidian-plugin/mnemosyne-sync/manifest.json`
- `obsidian-plugin/mnemosyne-sync/package.json`
- `docs/ONYX_MNEMOSYNE_INTEGRATION_PLAN.ko.md`
- `docs/ONYX_READ_ONLY_EXPORT_CONTRACT.md`
Orca/orchestration 기록:

- `.orch-coordinator/manifest.json`
- `.orch-coordinator/state.json`
- `.orca-orchestrator/config.json`
- `.orca-orchestrator/state.json`
- `.wiki-mnemosyne/NOTES.md`
- `.orch-coordinator/archive/tier2-hardening-2026-08-02.md`

마지막 archive 파일은 이전 실행의 stale 기록이다. 현재 목표와 혼동하지 말 것.

## 6. 다음 에이전트의 시작 절차

```bash
cd /Users/kereru/Development/mnemosyne
git status --short --untracked-files=all
git diff --check
sed -n '1,260p' docs/AGENT_HANDOFF.ko.md
sed -n '1,260p' docs/NEXT_WORK_ITEMS.ko.md
python3 -m pytest -q tests/test_obsidian_sync.py
python3 -m mnemosyne.cli sync obsidian /tmp/synthetic-vault \
  --db-path /tmp/mnemosyne-personal-test/graph/knowledge.db \
  --raw-root /tmp/mnemosyne-personal-test/raw \
  --wiki-root /tmp/synthetic-vault/_MnemosyneWiki \
  --dry-run
```

실제 iCloud Vault나 개인 문서를 위 명령에 넣지 말 것. `sync obsidian`은
DB와 raw root가 vault 안에 있으면 거부하고 `.obsidian`, `.trash`,
`_MnemosyneWiki`를 수집하지 않는다.

Obsidian 플러그인 검증:

```bash
cd /Users/kereru/Development/mnemosyne/obsidian-plugin/mnemosyne-sync
npm exec tsc -- --noEmit
npm run build
./node_modules/.bin/esbuild sync_queue.test.ts --bundle --platform=node --format=esm --outfile=/tmp/mnemosyne-sync-queue.test.mjs
node --test /tmp/mnemosyne-sync-queue.test.mjs
```

위 명령은 TypeScript 정적 검증, 번들 생성, debounce/coalescing 및 sync 중 변경 후속 실행 합성 테스트 2건을 검증한다. 자동 sync는 로컬 vault 저장 이벤트 경로이며, iCloud 동기화 완료나 실제 개인 Vault ingest를 승인하지 않는다.

로컬 `sync obsidian` 경계와 합성 dry-run은 **구현·검증 완료**이며, 실제 개인 Vault 실행은 사용자 검토 대기다.

## 7. 완료 조건

- outbound mapper/exporter가 private/restricted/tombstoned entity를 안전하게 처리한다. **완료**
- 허용·차단·quarantine·withdrawal 케이스가 테스트로 고정된다. **완료**
- scoped Onyx suite가 169 passed로 통과한다. **완료**
- provider/privacy 승인이 기록된다. **운영 승인 대기**
- 실제 개인 ingest 전 dry-run 결과를 사용자가 확인한다. **사용자 실행 대기**
- 실제 export 전 destination ACL, credential 주입, retention 정책이 확인된다. **운영 승인 대기**

현재 올바른 상태는 **“enforcement 완료 / 외부 export 차단”**이다.
