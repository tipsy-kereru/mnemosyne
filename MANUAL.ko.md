# Mnemosyne Knowledge Graph - 매뉴얼

---

## 1. 시스템 개요

### 1.1 이것은 무엇인가?

**AI 에이전트를 위한 로컬 지식 메모리 시스템**. Google Gemini의 Universal Temporal Knowledge Graph 연구를 기반으로, 일상 생활, 코딩, 법률 도메인에서 사용 가능한 **지속적 지식 복합 시스템**을 제공합니다.

**핵심 철학** (Andrej Karpathy):
> *"Obsidian은 IDE이고, 언어 모델은 프로그래머이며, 위키는 코드베이스입니다."*

### 1.2 핵심 기능

| 기능 | 설명 |
|---------|-------------|
| **제로 API 비용** | Tree-sitter AST + 로컬 SLM — 외부 API 의존성 없음 |
| **지식 복합** | 처음부터 관계를 다시 탐색하는 대신 지식이 누적됨 |
| **시간적 추적** | 버전별 엔티티 변경 기록 관리 |
| **세션 범위 지정** | 계층적 범위 관리: 프로젝트 / 주제 / 세션 |
| **FTS5 퍼지 검색** | SQLite FTS5 BM25를 통한 순위 엔티티 검색 |
| **Obsidian 경험** | [[wiki-links]] 지원 Joplin 플러그인 |
| **프로덕션 등급** | 626 테스트, mypy 0 에러, 81%+ 커버리지 |

### 1.3 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    RAW SOURCE (불변)                        │
│              mnemosyne/raw/{daily,coding,legal}/             │
│        원본 문서는 수정되지 않음 - 재컴파일 가능             │
└────────────────────────────┬────────────────────────────────┘
                             │ 추출 파이프라인
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                 WIKI LAYER (지식 바이너리)                    │
│              mnemosyne/wiki/{daily,coding,legal}/             │
│        Markdown + [[wiki-links]] - 인간이 읽기 가능           │
└────────────────────────────┬────────────────────────────────┘
                             │ 스키마 거버넌스
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                 SCHEMA LAYER (CLAUDE.md)                     │
│              mnemosyne/schema/{domain}.md                    │
│        텍스트 파일 편집을 통한 그래프 구조 변경               │
└────────────────────────────┬────────────────────────────────┘
                             │ 그래프 데이터베이스
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              KNOWLEDGE GRAPH (SQLite + NetworkX)             │
│              mnemosyne/graph/knowledge.db                    │
│        시간적 추적, 경로 찾기, 관계 분석                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 설치 및 설정

Mnemosyne은 두 가지 형태로 배포됩니다. Python 없이 실행 가능한 자체 완결형 단일 바이너리와, pip로 설치하는 패키지(Python 3.11+)입니다. 대부분의 최종 사용자는 바이너리를, 기여자와 pip 기반 사용자는 패키지 형태를 사용합니다.

### 2.1 바이너리 설치 (Python 불필요)

`mnemosyne` CLI는 플랫폼별로 단일 PyOxidizer 바이너리로 빌드되어 각 [GitHub Release](https://github.com/tipsy-kereru/mnemosyne/releases)에 첨부됩니다. CPython이 바이너리 안에 내장되어 있어 호스트에 Python, pip, 가상환경이 전혀 필요하지 않습니다.

원라인 설치 스크립트:

```bash
# Linux + macOS (curl | sh)
curl -fsSL https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.sh | sh

# Windows (PowerShell 5.1+)
iwr https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.ps1 -UseBasicParsing | iex
```

기본 설치 경로: `/usr/local/bin/mnemosyne` (Linux/macOS) 또는 `%LOCALAPPDATA%\Programs\mnemosyne\mnemosyne.exe` (Windows). `MNEMOSYNE_INSTALL_DIR`로 재정의할 수 있습니다. 설치 스크립트는 복사 전에 `SHA256SUMS.txt`와 대조하여 SHA256을 검증하며, `--force` / `MNEMOSYNE_FORCE=1`을 지정하지 않으면 기존 설치를 덮어쓰지 않습니다.

| 플랫폼         | 상태        | 비고 |
|----------------|-------------|-------|
| linux-x86_64   | GA          | `ubuntu-latest`에서 빌드. |
| darwin-arm64   | GA          | `macos-14`에서 빌드. 미서명 — 아래 참고. |
| windows-x86_64 | 미제공      | PyOxidizer 0.24 `_socket` DLL 로드 실패 (ISSUE-0010). pip 설치(§2.2) 사용. |
| darwin-x86_64  | 미제공      | 매트릭스에서 제거 (빌드 지연). 안정화 시 재추가. |
| linux-aarch64  | 미제공      | 크로스 컴파일 한계. native arm64 러너 필요. |

**macOS 미서명 바이너리:** 바이너리는 공증(notarization)을 거치지 않았습니다 (Apple Developer 인증서가 아직 없음). 최초 실행 시 Gatekeeper가 *"개발자를 확인할 수 없기 때문에 "mnemosyne"을(를) 열 수 없습니다."* 라고 차단할 수 있습니다. 검역 속성을 한 번 제거하면 됩니다:

```bash
xattr -d com.apple.quarantine /usr/local/bin/mnemosyne
```

**Windows 미서명 바이너리:** SmartScreen이 "인식되지 않은 앱" 경고를 표시할 수 있습니다. *추가 정보 → 실행*을 클릭하세요. 코드 서명(Authenticode)은 macOS 공증과 동일한 인증서 확보에 연계되어 후속으로 진행됩니다.

**바이너리 크기:** linux-x86_64 배포판은 약 146MB입니다 (바이너리 자체와 내장 `lib/` 모듈, 파일시스템으로 함께 배포되는 `jsonschema_specifications` / `referencing` 동반 디렉토리 포함). 이는 100MB 목표를 초과하며, 크기 축소 지렛대는 PyOxidizer 0.4x + CPython 3.12 업그레이드로 후속 작업으로 추적 중입니다. 동반 디렉토리 없이 바이너리만 이동하면 부팅 시 `No module named 'referencing._cores'` 오류가 발생하니 주의하세요.

**선택 확장 (SLM / PDF):** 바이너리에는 결정론적 추출, 위키 레이어, MCP 서버가 포함되어 있습니다. 로컬 SLM 엔티티 추출(GLiNER2)과 PDF 파싱은 베이스 바이너리를 작게 유지하기 위해 필요할 때 사이드카 확장으로 설치합니다:

```bash
mnemosyne extension install slm     # GLiNER2 + torch (로컬 SLM NER)
mnemosyne extension install pdf     # PyMuPDF 긴 문서 인덱싱
mnemosyne extension list
```

확장은 `${MNEMOSYNE_HOME:-~/.mnemosyne}/extensions/<name>/<version>/` 아래에 저장되며, 파일별 SHA256으로 검증되고 시작 시 `sys.path` 주입으로 로드됩니다.

**서명 검증 (cosign keyless):** Linux 및 darwin 바이너리는 태그 푸시 시 cosign keyless (sigstore)로 서명됩니다. 다운로드한 바이너리를 검증하려면:

```bash
cosign verify-blob \
  --certificate-identity-regexp 'https://github.com/tipsy-kereru/mnemosyne/.github/.+' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  --signature mnemosyne-linux-x86_64.sigstore \
  --bundle mnemosyne-linux-x86_64.sigstore \
  mnemosyne-linux-x86_64
```

바이너리 설치 전체 참조(문제 해결 표, man 페이지, 지연 항목): [docs/BINARY_INSTALL.md](docs/BINARY_INSTALL.md).

### 2.2 pip 설치 (Python 3.11+)

이미 Python을 사용 중이거나 에디터블 설치가 필요한 사용자:

```bash
# 코어만
pip install -e .

# 결정론적 추출로 (tree-sitter)
pip install -e ".[deterministic]"

# 시맨틱 추출로 (GLiNER2, torch)
pip install -e ".[semantic]"

# 개발 환경 (린트, 타입 확인, 테스트)
pip install -e ".[dev]"

# 전체 설치
pip install -e ".[all]"
```

### 2.3 Joplin 플러그인 설치

```bash
cd joplin-plugin/knowledge-graph
npm install && npm run build
npm run pack  # → knowledge-graph.jpl 파일 생성

# Joplin에서 설치: 도구 > 옵션 > 플러그인 > "파일에서 설치"
```

### 2.4 제거 (Uninstall)

단일 제거 스크립트는 없습니다. 각 구성 요소를 수동으로 제거하며 순서는 상관없습니다. 전체 참조: [docs/BINARY_INSTALL.md](docs/BINARY_INSTALL.md#uninstall).

```bash
# 바이너리 (Linux/macOS)
sudo rm -f /usr/local/bin/mnemosyne
# 바이너리 (Windows PowerShell)
#   Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Programs\mnemosyne"

# pip 패키지
pip uninstall mnemosyne-kg

# 선택 확장
mnemosyne extension remove slm
mnemosyne extension remove pdf
# 또는 한 번에:
rm -rf "${MNEMOSYNE_HOME:-$HOME/.mnemosyne}/extensions"

# 에이전트 스킬
rm -rf ~/.claude/skills/mnemosyne
rm -rf ~/.agents/skills/mnemosyne

# 데이터 디렉토리 — graph.db / raw / wiki를 재설치 후에도 유지하려면 삭제하지 마세요.
# 완전히 초기화할 때만 제거:
rm -rf "${MNEMOSYNE_HOME:-$HOME/.mnemosyne}"
```

셸 rc에서 `MNEMOSYNE_*` 환경변수도 함께 제거하세요.

---

## 3. CLI 사용법

### 3.1 기본 명령

| 명령 | 설명 |
|---------|-------------|
| `mnemosyne --version` | 버전 표시 |
| `mnemosyne query --stats` | 그래프 통계 |
| `mnemosyne query --query "search:term"` | FTS5 퍼지 검색 (순위 결과) |
| `mnemosyne extract <path>` | 파일/디렉터리에서 엔티티 추출 |
| `mnemosyne add <target>` | 파일, 디렉터리, URL 또는 `--text` 텍스트를 그래프에 수집 |
| `mnemosyne update <path>` | 변경된 파일을 그래프 및 LLM Wiki에 증분 반영 |
| `mnemosyne wiki <subcommand>` | Markdown LLM Wiki 검사 및 관리 |
| `mnemosyne config skill install` | Claude Code 또는 다른 에이전트용 에이전트 스킬 설치 |
| `mnemosyne mcp serve` | AI 에이전트 통합을 위한 MCP 서버 시작 |

### `mnemosyne add` 옵션

| 옵션 | 기본값 | 설명 |
|--------|---------|-------------|
| `--text TEXT` | — | 파일/URL 대신 인라인 텍스트 수집 |
| `--domain {coding,daily,legal}` | `daily` | 수집 도메인 |
| `--scope-id ID` | — | 수집된 엔티티에 범위 ID 할당 |
| `--source-channel CHANNEL` | `cli` | 수집 소스 채널 태그 |
| `--dry-run` | 해제 | 그래프에 쓰기 없이 추출 결과 미리 보기 |
| `--wiki-root PATH` | `~/mnemosyne/wiki` | LLM Wiki 루트 디렉터리 |
| `--no-wiki` | 해제 | 지식 그래프만 업데이트, 위키 페이지 건너뛰기 |
| `--wiki-excerpts` | 해제 | 위키 페이지에 제한된/편집된 소스 발췌 포함 (명시적 옵트인) |

기본 데이터 경로: `~/mnemosyne/raw/`, `~/mnemosyne/wiki/`, `~/mnemosyne/graph/knowledge.db`

### `mnemosyne wiki` 하위 명령

| 하위 명령 | 설명 |
|------------|-------------|
| `status` | 위키 상태 요약 (페이지 수, 부실 수, 모순 합계 등) |
| `lint` | 위키 링크, 메타데이터, 그래프 드리프트 확인; `--strict`로 경고 시 실패 |
| `contradictions` | 안정적인 `conflict_id`가 있는 그래프 기반 충돌 검토 항목 나열 |
| `resolve <id>` | 충돌 증거를 삭제하지 않고 해결 메타데이터만 업데이트 |
| `prune` | 부실 위키/그래프 정리 계획 미리 보기; `--apply-tombstones`로 툼스톤 레코드 생성 |
| `semantic-contradictions` | 로컬 오프라인 시맨틱 모순 감지 (옵트인); `--write`로 결과 저장 |
| `rebuild` | 그래프 데이터에서 생성된 위키 섹션 재생성; `--dry-run`으로 미리 보기 |
| `doctor` | `status` 및 `lint` 함께 실행 |

`rebuild`, `mnemosyne add`, `mnemosyne update` 및 기타 위키 쓰기 명령은 위키 루트당 `.mnemosyne-wiki.lock` 파일을 사용합니다 (기본 타임아웃: 10초).

### 3.2 LLM Wiki + 지식 그래프 수집

`mnemosyne add`와 `mnemosyne update`는 구조화된 지식 그래프와 함께 Karpathy 스타일의 Markdown LLM Wiki를 유지 관리합니다.

```bash
# 기본 위키 위치: ~/mnemosyne/wiki
mnemosyne add ./notes/meeting.md --domain daily --scope-id meeting-demo

# 사용자 정의 위치에 위키 쓰기 (Obsidian/Joplin/git vault 등)
mnemosyne add ./notes/meeting.md --domain daily --wiki-root ./wiki

# 그래프만 업데이트, Markdown 위키 건너뛰기
mnemosyne add ./notes/meeting.md --domain daily --no-wiki

# 기본적으로 소스 발췌는 위키에 복사되지 않음 (안전)
# 신뢰할 수 있는 소스에만 제한된/편집된 발췌 명시적으로 활성화
mnemosyne add ./notes/meeting.md --domain daily --wiki-excerpts

# 위키 상태 확인 / 린트 / 리빌드
mnemosyne wiki status --wiki-root ./wiki --format json
mnemosyne wiki lint --wiki-root ./wiki --format json
mnemosyne wiki rebuild --wiki-root ./wiki --db-path ~/mnemosyne/graph/knowledge.db --dry-run
```

생성/업데이트된 구조:

```text
~/mnemosyne/wiki/
├── index.md              # 콘텐츠 중심 카탈로그
├── log.md                # 추가 전용 수집 로그
├── sources/<domain>/     # 소스별 요약/프로비넌스 페이지
└── entities/<type>/      # 엔티티별 누적 페이지
```

Markdown Wiki는 인간이 읽을 수 있는 LLM 유지 관리 가능한 프레젠테이션 계층이며, SQLite + NetworkX은 경로 순회 및 구조화된 쿼리를 위한 지식 그래프 계층입니다. 생성된 페이지에는 프로비넌스를 위한 컴팩트한 YAML 프론트매터가 포함되며, 업데이트/리빌드 간에 Mnemosyne 생성 마커 외부의 수동 노트가 보존됩니다.

#### 충돌 메타데이터 및 모순 검토

수집 중 동일한 엔티티의 속성 값이 충돌하는 경우, Mnemosyne은 기존 값을 덮어쓰는 대신 `properties["conflicts"]`에 들어오는 값을 보존합니다. Wiki는 해결되지 않은 충돌 메타데이터를 엔티티 페이지의 생성된 `## Potential contradictions` 섹션으로 표면화하여 인간 검토를 수행합니다.

- 이 섹션은 결정론적/오프라인 요약입니다 — LLM 기반 시맨틱 판단이나 "참/거짓" 결정이 아닙니다.
- 충돌하는 값은 소스 발췌와 동일한 편집 정책을 통과한 후 표시됩니다.
- 그래프 DB가 있는 경우 `mnemosyne wiki status --db-path ... --format json`에 모순 합계 및 엔티티당 개수가 포함됩니다.
- `mnemosyne wiki lint --db-path ...`는 해결되지 않은 모순을 경고로 보고합니다. 자동화에서 실패하려면 `--strict`를 사용하세요.
- `mnemosyne wiki contradictions --db-path ... --format json`은 안정적인 `conflict_id`로 검토 항목 목록을 표시합니다.
- `mnemosyne wiki resolve <conflict_id> --resolution accepted_existing`는 충돌 값이나 소스 증거를 삭제하지 않고 검토 메타데이터만 업데이트합니다. 자동화에서 `--dry-run`을 먼저 사용하세요.
- 충돌 레코드는 해결 상태를 지원합니다: `unresolved`, `accepted_existing`, `accepted_incoming`, `superseded`, `ambiguous`.

#### 선택적 시맨틱 모순 발견

시맨틱 모순 발견은 결정론적 충돌 메타데이터와 별개의 옵트인 검토 워크플로우입니다. 결과는 인간 검토를 위한 후보이지 참/거짓 결정입니다.

- `mnemosyne wiki semantic-contradictions --db-path ... --format json`은 로컬 오프라인 휴리스틱 감지기를 실행하지만 검토 파일을 쓰지 않습니다.
- `--write`를 추가하면 `review/semantic-contradictions.*` 아래에 후보를 저장합니다.
- 출력은 별도의 `mnemosyne.semantic_contradiction_candidates.v1` 스키마를 사용하며, `processing_mode: local-offline`을 명시하고 원격 모델 호출이 비활성화되었음을 기록합니다.
- 후보 증거에는 소스 참조, 제한된/편집된 발췌, 신뢰도, 근거, 생성-메타데이터, 불확실성 표현이 포함됩니다. 원본 소스 발췌는 명시적인 `--include-raw-excerpts` 옵트인에서만 포함됩니다.
- `mnemosyne wiki status`와 `mnemosyne wiki lint`는 유지된 시맨틱 검토 후보를 결정론적 속성 충돌과 별도로 표시합니다. 린트는 경고만 발행하며, 자동화에서 실패하려면 `--strict`를 사용하세요.

#### 부실 계획 및 툼스톤

Mnemosyne은 부실 위키/그래프 수명 주기 정리를 검토 작업으로 처리하며 자동 삭제가 아닙니다.

- `mnemosyne wiki prune --db-path ... --format json`은 부실 후보(고 엔티티/소스 페이지, 누락된 원본 소스 경로 등)의 dry-run 계획을 생성합니다.
- 계획에는 후보 ID, 경로/엔티티/소스, 이유, 위험 레이블, 사용 가능한 경우 수동 노트 미리 보기가 포함됩니다.
- `mnemosyne wiki prune --apply-tombstones`는 `tombstones/` 아래에 Markdown 툼스톤 레코드를 쓰지만 여전히 제로 삭제를 수행합니다.
- 툼스톤에는 복구 메타데이터와 수동 노트 미리 보기가 포함되어 사용자가 의도적으로 아카이빙/정리할 수 있습니다.
- `mnemosyne wiki status`와 `mnemosyne wiki lint`는 부실 개수/경고를 표시하지만 기본적으로 실패하지 않습니다.

#### Joplin / Obsidian / 동기화된 폴더에 쓰기

편집기 관리 폴더에 쓸 때는 `--wiki-root`를 지정하세요.

```bash
mnemosyne add ./notes/meeting.md --domain daily --wiki-root ~/Notes/mnemosyne-wiki
mnemosyne wiki lint --wiki-root ~/Notes/mnemosyne-wiki
```

사용 계약:

- 위키 루트는 일반 Markdown 폴더로 열거나 가져올 수 있습니다. CI 또는 기본 사용에 실행 중인 Joplin 인스턴스가 필요하지 않습니다.
- Joplin에서 Markdown/폴더 가져오기 워크플로우를 사용하세요. 이 워크플로우에는 Joplin API 토큰이 필요하지 않습니다. 저장소나 위키에 토큰을 저장하지 마세요.
- Obsidian 스타일 vault의 경우 생성된 `[[...]]` 링크를 그대로 사용할 수 있습니다. 그러나 편집기는 `[[path/to/page|label]]` 링크를 다르게 렌더링할 수 있으므로 중단 링크 감지 권한으로 `mnemosyne wiki lint`를 사용하세요.
- `MNEMOSYNE:GENERATED` 마커 사이의 텍스트는 리빌드 시 교체됩니다. 마커 외부에 수동 노트를 작성하세요. 바람직하게는 `## Notes` 섹션 아래에 작성하세요.
- 원본 소스와 그래프 DB가 권한 있는 데이터입니다. 편집기 페이지는 인간이 읽을 수 있는 보기 + 수동 노트 계층입니다.

#### 위키 작성기 잠금

위키에 쓰는 명령은 생성된 페이지를 업데이트하기 전에 위키 루트당 `<wiki-root>/.mnemosyne-wiki.lock` 파일을 가져옵니다. 이 잠금은 동일한 위키 루트에 대한 `mnemosyne add`, `mnemosyne update`, `mnemosyne wiki rebuild`의 동시 쓰기를 방지합니다.

- 기본 타임아웃은 10초입니다.
- `mnemosyne wiki rebuild`는 대기 시간을 조정하기 위해 `--lock-timeout <seconds>`를 허용합니다.
- `mnemosyne wiki status`와 `mnemosyne wiki lint`는 읽기 전용이며 기본적으로 잠금을 가져오지 않습니다.
- 프로세스가 비정상적으로 종료되고 잠금 파일을 남긴 경우, 수동으로 삭제하기 전에 JSON 메타데이터(`pid`, `hostname`, `created_at`, `action`, `wiki_root`)를 확인하세요. Mnemosyne은 자동으로 부실 잠금을 해제하지 않습니다.
- 이 잠금은 로컬 파일 시스템 기반입니다. 네트워크/분산 파일 시스템의 잠금 의미론은 보장되지 않습니다.

Markdown Wiki는 읽을 수 있는 복합 아티팩트이며, SQLite + NetworkX은 쿼리 가능한 지식 그래프 계층입니다.

### 3.3 추출 파이프라인

```bash
# 전체 파이프라인 실행
python -m mnemosyne.extraction.pipeline \
  --domain coding \
  --source ~/my-project \
  --format json

# 세션 범위 및 증분 추출
python -m mnemosyne.extraction.pipeline \
  --domain coding --source ~/my-project \
  --scope-id impl-session --source-channel vscode \
  --incremental

# 시맨틱 추출 건너뛰기 (결정론적 구문 분석만)
python -m mnemosyne.extraction.pipeline \
  --domain coding --source ~/my-project --no-semantic
```

### 3.4 결정론적 추출 (제로 LLM)

```bash
# 단일 파일
python -m mnemosyne.extraction.deterministic.code_parser ~/project/main.py

# 전체 디렉터리
python -m mnemosyne.extraction.deterministic.code_parser ~/project --format wiki

# 세션 범위로
python -m mnemosyne.extraction.deterministic.code_parser ~/project \
  --scope-id my-session --source-channel code
```

**지원되는 언어**: Python, JavaScript, TypeScript, TSX, Go, Rust

### 3.5 시맨틱 추출 (로컬 SLM)

```bash
# 텍스트에서 엔티티 추출
python -m mnemosyne.extraction.semantic.slm_extractor \
  --text "John Smith works at Google" \
  --entities PERSON ORGANIZATION

# 파일에서 추출
python -m mnemosyne.extraction.semantic.slm_extractor \
  --file ~/documents/meeting-notes.txt \
  --entities PERSON ORGANIZATION DATE
```

### 3.6 그래프 쿼리

```bash
# 통계
python -m mnemosyne.graph.knowledge_graph --stats

# 엔티티 조회
python -m mnemosyne.graph.knowledge_graph --query "entity:function[parse_config]"

# 관계 조회
python -m mnemosyne.graph.knowledge_graph --query "relation:calls"

# 경로 찾기
python -m mnemosyne.graph.knowledge_graph --query "path:get_user,authenticate"

# FTS5 퍼지 검색 (순위 결과)
python -m mnemosyne.graph.knowledge_graph --query "search:authenticate"

# 세션 범위 쿼리
python -m mnemosyne.graph.knowledge_graph --query "entity:function[*]@session:impl-session"
```

### 3.7 MCP 서버

Mnemosyne은 AI 에이전트 통합을 위한 MCP 서버를 제공합니다:

```bash
# MCP 서버 시작
python -m mnemosyne.mcp

# 또는 CLI를 통해
mnemosyne mcp serve

# 설치 도우미 (MCP 클라이언트용 구성 조각 인쇄)
mnemosyne mcp install --client claude-desktop
mnemosyne mcp install --client hermes
mnemosyne mcp install --client openclaw
```

**15개의 MCP 도구**를 사용할 수 있습니다:
- **읽기**: mnemosyne_search, mnemosyne_query, mnemosyne_get_entity, mnemosyne_list_entities, mnemosyne_stats, mnemosyne_wiki_status, mnemosyne_wiki_lint
- **쓰기**: mnemosyne_add, mnemosyne_extract, mnemosyne_update, mnemosyne_create_entity, mnemosyne_update_entity, mnemosyne_create_relation
- **위키 유지 관리**: mnemosyne_wiki_rebuild, mnemosyne_wiki_prune

**삭제 없음 계약**: MCP 서버는 데이터를 삭제하지 않습니다. `mnemosyne_update_entity`는 시간적 버전을 추가(entity_history)하고, `mnemosyne_wiki_prune`은 툼스톤 레코드만 생성합니다.

**전송**: 직접 Python 가져오기(프로세스 내 KnowledgeGraph + Handlers 재사용, 별도의 `mnemosyne serve` 필요 없음).

### 3.8 에이전트 연동 — 훅, 스킬, MCP

Mnemosyne은 AI 코딩 에이전트(Claude Code, Codex, Gemini CLI, Copilot CLI 및 git 기반 워크플로우 전반)와 세 가지 상호 보완적 경로로 연동됩니다. 조합해서 사용할 수 있습니다.

#### 자동 동기화 훅

`mnemosyne config hook install`은 에이전트가 작성하거나 편집한 파일을 다시 수집하여 그래프와 위키를 수동 명령 없이 최신으로 유지하는 PostToolUse 훅을 설치합니다. 에이전트 외 워크플로우용 git post-commit 훅도 있습니다.

```bash
mnemosyne config hook install              # git + claude (기본)
mnemosyne config hook install claude codex # 특정 대상
mnemosyne config hook install --force      # 기존 훅 설정 덮어쓰기
mnemosyne config hook status               # 설치된 대상 표시
mnemosyne config hook remove               # 전체 제거
mnemosyne config hook remove codex         # 단일 대상 제거
```

지원 대상과 훅 위치:

| 대상     | 훅 위치 | 트리거 |
|---------|---------------|---------|
| `git`     | `.git/hooks/post-commit`               | 커밋 후 → `mnemosyne update --quiet` |
| `claude`  | `~/.claude/settings.json` (PostToolUse) | 에이전트 Write/Edit → `mnemosyne add <file>` |
| `codex`   | codex `hooks.json`                      | 에이전트 Write/Edit → `mnemosyne add <file>` |
| `gemini`  | gemini 설정 (AfterTool)                  | 에이전트 Write/Edit → `mnemosyne add <file>` |
| `copilot` | copilot CLI 훅                          | 에이전트 Write/Edit → `mnemosyne add <file>` |

각 에이전트 훅은 60초 타임아웃으로 `mnemosyne add <file> --quiet`를 실행하며, 실패해도 에이전트를 차단하지 않습니다(에러는 캡처 후 무시). 훅 스크립트는 mnemosyne이 관리합니다 — 업그레이드 후 `mnemosyne config hook install`을 다시 실행해 갱신하세요.

참고:
- 훅은 파일 단위로 발화합니다. 대규모 리팩토링이나 브랜치 전환 후에는 `mnemosyne update`를 한 번 실행해 전체 재동기화하세요.
- 훅은 `Write`/`Edit` 도구 호출에만 동작합니다. 읽기와 셸 명령은 수집을 트리거하지 않습니다.
- 수집을 프로젝트로 한정하려면 프로젝트 루트에서 먼저 `mnemosyne add . --domain coding`을 실행하세요. 그래프는 콘텐츠 해시 기준이므로 변경 없는 파일의 재수집은 no-op입니다.

#### 에이전트 스킬 (Claude Code)

`/mnemosyne` 스킬을 통해 Claude Code가 대화 중에 지식 그래프를 수집, 쿼리, 추출, 관리할 수 있습니다.

```bash
mnemosyne config skill install                       # ~/.claude/skills/mnemosyne/
mnemosyne config skill install --target agents       # ~/.agents/skills/ (프레임워크 범용)
mnemosyne config skill install --force               # 동일해도 재설치
mnemosyne config skill install --path ~/my-agent/skills
```

설치 후 Claude Code에서 `/mnemosyne`을 입력하세요. 스킬은 `mnemosyne` CLI의 얇은 래퍼이므로 이 매뉴얼의 모든 명령을 사용할 수 있습니다.

#### MCP 서버

15-도구 MCP 서버는 §3.7을 참고하세요. Claude Desktop / Claude Code MCP 연동:

```bash
mnemosyne mcp install --client claude-desktop   # 추가할 설정 조각 인쇄
```

MCP 경로가 가장 풍부한 질의 표면입니다: `mnemosyne_search`, `mnemosyne_query`, `mnemosyne_ask`(NL Q&A), `mnemosyne_chat`(멀티턴) 및 읽기/쓰기/위키 유지보수 도구. no-delete 계약을 따릅니다.

#### Codex 특이사항

Codex는 자동 동기화 훅으로만 지원됩니다(`mnemosyne config hook install codex`). Codex 전용 스킬이나 MCP 설치 도우미는 없습니다. Codex에서 질의하려면 `mnemosyne` CLI를 직접 호출:

```bash
mnemosyne query --query "search:authenticate"
mnemosyne ask "authenticate를 호출하는 함수는?"
```

또는 `mnemosyne mcp serve` 명령을 Codex의 MCP 설정에 수동으로 추가해 MCP 서버를 가리키세요.

#### 전형적인 엔드투엔드 설정

```bash
cd ~/my-project
mnemosyne add . --domain coding             # 그래프 + 위키 시딩
mnemosyne project register .                # (선택) 스코핑용 프로젝트 등록
mnemosyne config hook install claude               # 에이전트 편집 시 자동 동기화
mnemosyne config skill install                     # Claude Code에서 /mnemosyne
mnemosyne mcp install --client claude-desktop
```

이제: Claude Code가 코드를 편집 → 훅이 재수집 → 위키가 실시간 유지 → MCP나 스킬로 질문. Codex는 `mnemosyne config hook install codex`로 같은 자동 동기화를 얻습니다.

---

## 4. Python API

### 4.1 엔티티 추출

```python
from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor
from pathlib import Path

extractor = TreeSitterExtractor()

# 단일 파일 추출
result = extractor.extract_file_full(Path("main.py"))
print(f"엔티티: {len(result.entities)}")
print(f"가져오기: {len(result.imports)}")
print(f"호출: {len(result.calls)}")

# 디렉터리 추출
entities = extractor.extract_directory(
    Path("src/"),
    scope_id="my-session"
)

# Wiki 형식 변환
print(extractor.to_wiki_format(result.entities, result.imports, result.calls))
```

### 4.2 시맨틱 추출

```python
from mnemosyne.extraction.semantic.slm_extractor import SemanticExtractor

# 컨텍스트 관리자를 통한 자동 정리
with SemanticExtractor() as extractor:
    result = extractor.extract(
        "John Smith at Google Inc",
        ["PERSON", "ORGANIZATION"],
        scope_id="session-1",
        source_channel="cli",
    )
    # result = {entities: [...], relations: [...], token_cost: N}
```

### 4.3 지식 그래프 쿼리

```python
from mnemosyne.graph.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()

# 통계
stats = kg.get_stats()

# FTS5 퍼지 검색 (순위 결과)
results = kg.query("search:authenticate")

# 엔티티 조회
results = kg.query("entity:function[parse_config]")

# 관계 조회
results = kg.query("relation:calls")

# 최단 경로
results = kg.query("path:get_user,authenticate")

# 세션 범위 쿼리
results = kg.query("entity:function[*]@session:impl-session")
```

### 4.4 범위 관리

```python
from mnemosyne.graph.scope_manager import ScopeManager

sm = ScopeManager()

# 계층적 범위 생성
sm.create_scope("project-x", scope_type="project")
sm.create_scope("feature-auth", parent_id="project-x", scope_type="feature")
sm.create_scope("session-1", parent_id="feature-auth", scope_type="session")

# 범위 트리 쿼리
children = sm.get_children("project-x")
lineage = sm.get_lineage("session-1")  # session-1 → feature-auth → project-x
```

---

## 5. 도메인 스키마

### 5.1 일상 생활

| 엔티티 | 설명 | 핵심 속성 |
|--------|-------------|----------------|
| `task` | 할 일 / 작업 항목 | title, deadline, priority, status |
| `person` | 연락처 | name, role, contact, last_interaction |
| `place` | 위치 | name, type, address, visit_frequency |
| `event` | 캘린더 이벤트 / 약속 | title, datetime, duration, participants |
| `habit` | 습관 | name, frequency, time, streak |
| `preference` | 선호도 | category, value, confidence |
| `note` | 일반 노트 | title, content, tags |

### 5.2 코딩

| 엔티티 | 설명 | 핵심 속성 |
|--------|-------------|----------------|
| `function` | 함수 / 메서드 | name, signature, language, complexity |
| `class` | 클래스 / 구조체 | name, methods, attributes, inherits |
| `module` | 모듈 / 패키지 | name, type, exports, imports |
| `api` | API 엔드포인트 | name, type, endpoint, method, auth_required |
| `bug` | 버그 보고서 | id, severity, status, affected_functions |
| `feature` | 기능 요청 | id, status, priority |
| `test` | 테스트 케이스 | name, type, covers, status |
| `dependency` | 외부 의존성 | name, version, vulnerabilities |

### 5.3 법률

| 엔티티 | 설명 | 핵심 속성 |
|--------|-------------|----------------|
| `statute` | 법률 / 규정 | name, jurisdiction, code, effective_date |
| `clause` | 조항 | number, title, content, obligation_type |
| `case` | 법원 사건 | citation, court, date, holding, reasoning |
| `party` | 법률 당사자 | name, type, role, counsel |
| `obligation` | 의무 / 요구 사항 | description, obligated_party, deadline |
| `deadline` | 법률 마감 | date, type, consequence |
| `contract` | 계약 | title, parties, effective_date, status |

---

## 6. Wiki 링크 구문

| 구문 | 의미 | 예제 |
|--------|---------|---------|
| `[[note-name]]` | Joplin 노트 링크 | `[[project-plan]]` |
| `[[entity:function:authenticate]]` | 지식 그래프 엔티티 | `[[entity:function:authenticate]]` |
| `[[entity:function:parse@session:s1]]` | 특정 세션의 엔티티 | `[[entity:function:parse@session:s1]]` |
| `[[entity:function:parse@project:p1@channel:code]]` | 복합 범위 | - |
| `[[graph:query]]` | 그래프 쿼리 결과 | `[[graph:search:security]]` |

---

## 7. 디렉터리 구조

```
mnemosyne-knowledge-graph/
├── mnemosyne/                    # 메인 Python 패키지
│   ├── __init__.py               # 공개 API
│   ├── __main__.py               # python -m 진입점
│   ├── cli.py                    # 메인 CLI (query, extract)
│   ├── graph/                    # 지식 그래프 엔진
│   │   ├── cli.py                # 그래프 쿼리 CLI
│   │   ├── knowledge_graph.py    # SQLite + NetworkX
│   │   └── scope_manager.py      # 계층적 범위
│   ├── extraction/               # 추출 파이프라인
│   │   ├── cli.py                # 추출 CLI
│   │   ├── pipeline.py           # 3계층 오케스트레이션
│   │   ├── pipeline_types.py     # 타입 정의
│   │   ├── deterministic/        # 제로 LLM 계층
│   │   │   ├── code_parser.py    # Tree-sitter 추출
│   │   │   ├── types.py          # ParseResult, ImportEntity, CallRelation
│   │   │   └── languages/        # 언어별 추출기
│   │   │       ├── base.py       # LanguageExtractor 프로토콜
│   │   │       ├── python_extractor.py
│   │   │       ├── javascript_extractor.py
│   │   │       ├── go_extractor.py
│   │   │       └── rust_extractor.py
│   │   ├── semantic/             # 로컬 SLM 계층
│   │   │   └── slm_extractor.py  # GLiNER2 + REBEL
│   │   └── synthesis/            # 선택적 LLM 계층
│   ├── raw/                      # 불변 소스 문서
│   ├── wiki/                     # 추출된 지식
│   └── schema/                   # 도메인 스키마
├── tests/                        # 626 테스트
├── joplin-plugin/                # Joplin 플러그인 (TypeScript)
├── pyproject.toml                # PEP 621 구성
├── CHANGELOG.md                  # 버전 기록
└── CLAUDE.md                     # 시스템 프롬프트
```

---

## 7. 성능 튜닝

대규모 위키 또는 높은 동시 쓰기가 있는 환경의 경우, Mnemosyne은 즉시 사용 가능한 몇 가지 최적화 기능을 제공합니다.

### 7.1 데이터베이스 연결 튜닝
시간적 지식 그래프는 로컬 상태를 위해 SQLite를 사용합니다. 데이터베이스 엔진은 다음과 같이 조정됩니다:
*   **WAL (Write-Ahead Logging) 모드**: 기본적으로 활성화되어 있으며, 동시 읽기 및 쓰기가 잠금 충돌 없이 데이터베이스에 액세스할 수 있습니다.
*   **동기화 모드**: `NORMAL`로 설정됩니다. 이는 모든 쓰기에서 비싼 fsync 플러시를 방지하여 대량 수집 작업 중 데이터베이스 처리량을 향상시킵니다.
*   **타임아웃**: SQLite 연결 타임아웃은 여러 에이전트가 파일을 동시에 편집할 때 잠금 문제를 해결하기 위해 `30s`로 설정됩니다.

### 7.2 메모리 지원 잠금 디렉터리 (잠금 오프로딩)
Mnemosyne의 위키 모듈은 파일 기반 잠금을 통해 쓰기 프로세스를 직렬화합니다. 스토리지 I/O 지연을 방지하기 위해 잠금 파일을 RAM 디스크(예: `/tmp` 또는 다른 `tmpfs` 경로)로 리디렉션할 수 있습니다:
```bash
# 잠금 파일을 RAM 디스크로 리디렉션
export MNEMOSYNE_LOCK_DIR=/tmp
```
구성된 경우, 잠금은 위키 루트에 대한 결정적 해시 이름으로 지정된 빠른 액세스 스토리지 경로 아래에 기록됩니다.

### 7.3 하이브리드 Rust 가속 코어 (`mnemosyne-core`)
코어 패키지에 통합된 선택적 PyO3 기반 Rust 확장:
*   **설치**: `cargo`가 있는 경우 일반 패키지 설치 중에 자동 컴파일됩니다.
*   **오프로딩**: `Rayon`을 사용하는 병렬 실행 풀에 Python 파일 globbing 및 인덱스 페이지 생성을 오프로딩합니다.
*   **폴백**: 컴파일러가 없는 경우 패키지는 100% 기능 패리티를 유지하면서 네이티브 Python 인덱싱 경로로 동적으로 폴백합니다.

---

## 8. 문제 해결

| 문제 | 해결 방법 |
|-------|----------|
| `ModuleNotFoundError: spacy` | `python -m spacy download en_core_web_sm` |
| GLiNER 로드 실패 | `pip install gliner` 후 재시도 |
| 누락된 tree-sitter 문법 | 언어별 패키지 설치 (예: `pip install tree-sitter-python`) |
| Joplin 플러그인 로드 실패 | Joplin 2.14 이상 확인 |
| 빈 그래프 쿼리 결과 | `search:`로 퍼지 검색 시도 |
| `mypy` 에러 | `pip install -e ".[dev]"` 실행 후 `mypy mnemosyne/` |

---

## 9. 품질 메트릭

| 메트릭 | 현재 상태 |
|--------|---------------|
| pytest | 626 통과 |
| mypy | 0 에러 (37+ 소스 파일) |
| ruff | 0 위반 |
| 커버리지 | 81%+ |
| SPEC | 19 완료 |

---

*매뉴얼 버전: 3.1*
*마지막 업데이트: 2026-06-14*
