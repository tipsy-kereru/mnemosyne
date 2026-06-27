# Mnemosyne Knowledge Graph

AI 에이전트를 위한 로컬 우선, API 비용 제로의 지식 메모리 시스템. **일상 생활**, **코딩**, **법률**의 세 가지 도메인에서 지속적이고 복합적인 지식을 제공합니다.

Google의 Gemini Universal Temporal Knowledge Graph 연구를 기반으로 하며, Andrej Karpathy의 통찰을 따릅니다: *"Obsidian은 IDE이고, 언어 모델은 프로그래머이며, 위키는 코드베이스입니다."*

> 영문 문서는 [README.md](README.md)를 참고하세요. · 전체 매뉴얼: [MANUAL.ko.md](MANUAL.ko.md) · 바이너리 설치: [docs/BINARY_INSTALL.md](docs/BINARY_INSTALL.md)

## 이름의 기원

**므네모시네**(그리스어: Μνημοσύνη)는 그리스 신화의 **기억의 여신**으로, 하늘의 신 우라노스와 대지의 여신 가이아 사이에서 태어난 티탄 신족입니다. 제우스와 아홉 날을 보내며 학예의 여신들인 **아홉 무사이(Mousai·Muses)**의 어머니가 되었고, 그녀의 이름은 영단어 *memory*(기억)의 어원이 됩니다. 그리스의 저승에는 망각의 강 레테(Lethe)와 마주한 **므네모시네의 못**이 있어, 그 물을 마신 자는 죽음 너머에서도 모든 것을 기억한다고 전해집니다. 로마 신화에서는 경고와 기억을 관장하는 유노의 별칭 **모네타(Moneta)**와 동일시되었으며, 유노 모네타 신전에서 동전을 주조한 데서 *money*(돈)라는 단어의 어원이 되었습니다.

*Fate/Grand Order*에서 **MNEMOSYNE**(자립관측형 존재증명 시스템・므네모쉬네, 自立観測型存在証明システム・ムネーモシュネー)는 칼데아 보안기구의 하위 시스템으로, 레이시프트 도중 인간 관측자가 마스터의 존재를 관측할 수 없을 때 마스터의 존재를 독립적이고 자동으로 증명하기 위해 설계되었습니다. 마술의 눈(Mystic Eyes)을 장착한 투구를 쓰고 레오나르도 다 빈치의 모습을 취한 이 시스템은, 마스터의 유일한 관측자가 되기를 원합니다. 관측이 대상의 존재를 정하는 세계에서, 관측자가 곧 존재의 증거입니다.

이 프로젝트는 신화를 두 가지 의미로 이어받습니다. 지식 그래프는 잊히지 않고 복리로 쌓이는 에이전트의 **기억**이며, 동시에 에이전트가 수행한 작업과 결정, 그리고 맥락이 실제로 일어났음을 증명하는 **관측적 존재 증명 시스템**입니다.

## 품질 상태

| 메트릭 | 상태 |
|--------|--------|
| 테스트 | 860+ 통과 |
| 타입 안전성 | mypy 0 에러 |
| 린트 | ruff 0 위반 |
| 경고 | 0 pytest 경고 |
| 커버리지 | 81%+ |
| SPEC | 27+ 완료 (LONGDOC·NLQUERY·PACKAGE·FOLLOWUP 반영) |

## 아키텍처

```
Raw Source Layer (불변)
       ↓
Wiki Layer (Markdown + [[wiki-links]])
       ↓
Schema Layer (CLAUDE.md / AGENTS.md)
       ↓
Knowledge Graph (SQLite + NetworkX)
```

**4계층 추출 파이프라인:**

| 계층 | 기술 | 비용 | 하드웨어 |
|-------|-----------|------|----------|
| 결정론적 | Tree-sitter AST, SpaCy | $0 | CPU 전용 |
| 시맨틱 | GLiNER2 NER, REBEL | $0 | CPU / 소형 GPU |
| 합성 | Llama-3-8B / GPT-4o | 선택적 | GPU / 클라우드 |
| Wiki | Markdown + wiki-links | $0 | 모두 |

## 설치

두 가지 설치 경로가 있습니다. **대부분의 사용자는 바이너리를 권장** — Python, pip, 가상환경이 전혀 필요 없습니다.

### 옵션 A: 단일 바이너리 (Python 불필요)

`mnemosyne` CLI는 CPython을 내장한 자체 완결형 바이너리로 플랫폼별로 제공됩니다. [GitHub Releases](https://github.com/tipsy-kereru/mnemosyne/releases)에서 다운로드하거나 원라인 설치 스크립트를 사용하세요:

```bash
# Linux + macOS (curl | sh)
curl -fsSL https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.sh | sh

# Windows (PowerShell 5.1+)
iwr https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.ps1 -UseBasicParsing | iex
```

- 설치 경로: `/usr/local/bin/mnemosyne` (Linux/macOS) 또는 `%LOCALAPPDATA%\Programs\mnemosyne\` (Windows). `MNEMOSYNE_INSTALL_DIR`로 재정의 가능.
- 기존 설치가 있으면 덮어쓰지 않습니다. 강제하려면 **플래그는 curl이 아니라 설치 스크립트용** — `sh -s --`나 환경변수로 전달: `curl ... | sh -s -- --force` 또는 `MNEMOSYNE_FORCE=1 curl ... | sh`. (`curl ... --force | sh`는 `--force`를 설치 스크립트에 전달하지 않습니다.)
- 설치 전 `SHA256SUMS.txt`로 SHA256 검증, 불일치 시 중단.
- GA 플랫폼: **linux-x86_64, darwin-arm64**.
  (darwin-x86_64, linux-aarch64는 베스트에포트; windows-x86_64는 지연 — [docs/BINARY_INSTALL.md](docs/BINARY_INSTALL.md#windows-status-deferred--issue-0010) 참고. Windows 사용자는 아래 pip 설치를 사용하세요.)
- macOS/Windows 바이너리는 **미서명**. macOS Gatekeeper 차단 시 한 번 실행: `xattr -d com.apple.quarantine /usr/local/bin/mnemosyne`. Windows SmartScreen → "추가 정보 → 실행".
- 바이너리 크기 약 146MB (PyOxidizer 0.24 한계, 크기 축소는 후속 작업으로 추적 중).
- SLM(GLiNER2)과 PDF 파싱은 **선택 확장** — 필요 시 설치: `mnemosyne extension install slm` / `mnemosyne extension install pdf`.

전체 세부 사항, cosign 서명 검증, man 페이지, 문제 해결은 [docs/BINARY_INSTALL.md](docs/BINARY_INSTALL.md)를 참고하세요.

### 옵션 B: pip로 GitHub에서 설치 (Python 3.11+, 파워 유저)

**요구 사항:** Python 3.11 이상 (3.13 권장).

```bash
# GitHub에서 최신 버전 설치
pip install "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne.git"

# ingest extras로 (LLM 추출, URL 가져오기)
pip install "mnemosyne-kg[ingest] @ git+https://github.com/tipsy-kereru/mnemosyne.git"

# 결정론적 추출로 (tree-sitter, 제로 LLM)
pip install "mnemosyne-kg[deterministic] @ git+https://github.com/tipsy-kereru/mnemosyne.git"

# 전체
pip install "mnemosyne-kg[all] @ git+https://github.com/tipsy-kereru/mnemosyne.git"
```

설치 후 CLI 명령을 사용할 수 있습니다:

```bash
mnemosyne --version       # 설치 확인
mnemosyne add --help      # 파일, URL 또는 텍스트 수집
mnemosyne query --stats   # 그래프 통계
mnemosyne wiki doctor     # 위키 건강 상태 확인
```

### 업데이트

```bash
# pip
pip install --upgrade "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne.git"

# uv
uv pip install --upgrade "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne.git"
```

### 에이전트 연동 (Claude Code / Codex / 기타)

Mnemosyne은 세 가지 상호 보완적 경로로 AI 코딩 에이전트와 연동됩니다. 워크플로우에 맞는 것을 설치하세요.

**1. 자동 동기화 훅** — 에이전트가 코드를 고치면 위키가 자동으로 따라갑니다.

`mnemosyne hook install`은 PostToolUse 훅을 설치하여, 에이전트의 모든 `Write`/`Edit`이 `mnemosyne add <file>`을 트리거하고 그래프 + 위키를 갱신합니다. 지원 대상: `git`(post-commit), `claude`(Claude Code `settings.json`), `codex`, `gemini`, `copilot`.

```bash
mnemosyne hook install              # git + claude (기본)
mnemosyne hook install claude codex # 대상 지정
mnemosyne hook status               # 설치된 훅 확인
mnemosyne hook remove claude        # 특정 대상 제거
```

**2. 에이전트 스킬** — Claude Code에서 `/mnemosyne`으로 명시적 수집/쿼리/추출.

```bash
mnemosyne skill install                       # ~/.claude/skills/mnemosyne/ (Claude Code)
mnemosyne skill install --target agents       # ~/.agents/skills/ (프레임워크 범용)
mnemosyne skill install --force               # 재설치
mnemosyne skill install --path ~/my-agent/skills
```

**3. MCP 서버** — 대화 중 호출 가능한 15+ 도구 (읽기, 쓰기, 위키 유지보수, NL ask/chat).

```bash
mnemosyne mcp serve                            # 서버 시작
mnemosyne mcp install --client claude-desktop  # 설정 조각 인쇄
mnemosyne mcp install --client hermes
mnemosyne mcp install --client openclaw
```

**개발 중인 프로젝트의 전형적 설정:**

```bash
cd ~/my-project
mnemosyne add . --domain coding     # 현재 코드에서 그래프 + 위키 시딩
mnemosyne hook install claude       # 에이전트 편집 시 자동 동기화
mnemosyne mcp install --client claude-desktop
```

이후 Claude Code가 프로젝트를 편집하면 위키가 실시간으로 유지되고, MCP 도구나 `/mnemosyne` 스킬로 *"authenticate를 호출하는 함수는?"* 같은 질문을 할 수 있습니다. Codex는 `mnemosyne hook install codex`로 같은 자동 동기화를 얻습니다 (훅 전용; Codex에서 질의하려면 `mnemosyne` CLI를 직접 호출).

전체 참조는 [MANUAL.ko.md §3.8](MANUAL.ko.md#38-에이전트-연동--훅-스킬-mcp)을 보세요.

### 소스에서 (기여자용)

```bash
git clone https://github.com/tipsy-kereru/mnemosyne.git
cd mnemosyne

# 코어만
pip install -e .

# 결정론적 추출로 (tree-sitter)
pip install -e ".[deterministic]"

# 시맨틱 추출로 (GLiNER2, torch)
pip install -e ".[semantic]"

# 개발 (린트, 타입 확인, 테스트)
pip install -e ".[dev]"

# 전체
pip install -e ".[all]"
```

### Extras

| Extra | 포함 항목 | 사용 사례 |
|-------|----------|----------|
| `deterministic` | tree-sitter, SpaCy | 제로-LLM 코드 추출 |
| `semantic` | GLiNER2, torch, transformers | 로컬 SLM 엔티티 추출 |
| `ingest` | requests, anthropic, httpx | URL 가져오기, LLM 기반 추출 |
| `all` | deterministic + semantic | 전체 로컬 추출 |
| `dev` (dependency-group) | pytest, ruff, tree-sitter, all ingest deps | 기여 |

## 빠른 시작

```bash
# 1. GitHub에서 설치
pip install "mnemosyne-kg[all] @ git+https://github.com/tipsy-kereru/mnemosyne.git"
# 또는 로컬 클론에서:
# pip install -e ".[all]"

# 2. 지식 그래프 및 LLM Wiki에 소스 추가
mnemosyne add ./notes/meeting.md --domain daily
# graph  → ~/mnemosyne/graph/knowledge.db
# wiki   → ~/mnemosyne/wiki/{index.md,log.md,sources/,entities/}

# 3. 지식 그래프 쿼리
mnemosyne query --stats
mnemosyne query --query "search:authenticate"
mnemosyne query --query "entity:function[parse_config]"

# 4. 프로젝트에서 코드 엔티티 추출
mnemosyne extract src/ --domain coding --format json

# 5. 위키 건강 상태 확인
mnemosyne wiki doctor
```

## CLI 참조

### 최상위 명령

| 명령 | 설명 |
|---------|-------------|
| `mnemosyne --version` | 패키지 버전 표시 |
| `mnemosyne query --stats` | 그래프 통계 |
| `mnemosyne query --query "search:term"` | FTS5 퍼지 검색 (순위 결과) |
| `mnemosyne extract <path>` | 파일 또는 디렉터리에서 엔티티 추출 |
| `mnemosyne add <target>` | 파일, 디렉터리, URL 또는 `--text` 조각 수집 |
| `mnemosyne update <path>` | 변경된 파일에서 그래프 및 LLM Wiki 증분 새로 고침 |
| `mnemosyne wiki <subcommand>` | Markdown LLM Wiki 검사 및 유지 관리 |
| `mnemosyne mcp serve` | AI 에이전트 통합을 위한 MCP 서버 시작 |

### `mnemosyne add` 옵션

| 옵션 | 기본값 | 설명 |
|--------|---------|-------------|
| `--text TEXT` | — | 파일/URL 대신 인라인 텍스트 조각 수집 |
| `--domain {coding,daily,legal}` | `daily` | 수집 도메인 |
| `--scope-id ID` | — | 수집된 엔티티에 명명된 범위 연결 |
| `--source-channel CHANNEL` | `cli` | 수집 소스 태그 |
| `--dry-run` | 해제 | 그래프에 쓰기 없이 추출 미리 보기 |
| `--wiki-root PATH` | `~/mnemosyne/wiki` | LLM Wiki 루트 디렉터리 |
| `--no-wiki` | 해제 | 지식 그래프만 업데이트, 위키 페이지 건너뛰기 |
| `--wiki-excerpts` | 해제 | 위키 페이지에 제한된/편집된 소스 발췌 포함 (명시적 옵트인) |

기본 데이터 경로: `~/mnemosyne/raw/`, `~/mnemosyne/wiki/`, `~/mnemosyne/graph/knowledge.db`

## MCP 서버

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

## 성능 튜닝

Mnemosyne는 지식 베이스 확장을 위한 네이티브 쓰기 성능 최적화를 제공합니다.

### 1. SQLite WAL(Write-Ahead Logging) 및 Normal 동기화
SQLite 데이터베이스는 WAL 저널링과 완화된 동기화를 사용하여 원본 소스 수집 중 데이터베이스 삽입/업데이트 속도를 높입니다.
*   읽기와 쓰기가 동시에 서로를 차단하지 않습니다.
*   기본 SQLite 연결 `timeout`은 잠금 시간 초과 실패를 방지하기 위해 `30s`로 상향되었습니다.

### 2. 잠금 오프로딩(MNEMOSYNE_LOCK_DIR)
순차 쓰기 잠금은 안전하게 처리됩니다. 디스크 잠금 지연(특히 느린 HDD 또는 네트워크 볼륨)을 방지하려면 잠금 경로를 `/tmp`(메모리 기반 `tmpfs` RAM 디스크)로 리디렉션하십시오:
```bash
export MNEMOSYNE_LOCK_DIR=/tmp
```

### 3. 네이티브 Rust 가속기 코어(mnemosyne-core)
Mnemosyne는 디렉터리 글로빙 및 인덱스 페이지 생성 속도를 높이기 위해 PyO3/Rayon 기반 Rust 확장 모듈을 통합합니다:
*   **자동 빌드**: `cargo`가 있으면 패키지 설치 시 자동으로 빌드됩니다.
*   **정상 폴백**: Rust 컴파일러가 없으면 오류 없이 네이티브 Python 로직으로 전환됩니다.

새 컴퓨터에서 가속기를 활성화하려면 Rust 툴체인(`cargo` 제공)을 설치하십시오:
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```
그런 다음 빌드가 `cargo`를 인식하도록 패키지를 재설치하십시오:
```bash
pip install --force-reinstall --no-deps "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne.git"
```

## 핵심 기능

- **제로 API 비용**: Tree-sitter AST 구문 분석(6개 언어), NLP용 로컬 SLM
- **지식 복합**: Wiki 레이어가 추출 간 지식을 누적
- **시간적 추적**: 타임스탬프가 있는 엔티티 버전 기록
- **세션 범위**: 계층적 프로젝트/주제/세션 범위 지정
- **FTS5 퍼지 검색**: SQLite FTS5 BM25를 통한 순위 엔티티 검색
- **증분 추출**: SHA-256 콘텐츠 해시 추적
- **다중 도메인**: 코딩, 일상 생활, 법률 스키마
- **프로토콜 기반**: 확장 가능한 언어 지원을 위한 `LanguageExtractor` 프로토콜
- **프로덕션 준비 완료**: mypy strict, ruff clean, 860+ 테스트, 81%+ 커버리지
