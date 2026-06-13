# Mnemosyne Knowledge Graph

AI 에이전트를 위한 로컬 우선, API 비용 제로의 지식 메모리 시스템. **일상 생활**, **코딩**, **법률**의 세 가지 도메인에서 지속적이고 복합적인 지식을 제공합니다.

Google의 Gemini Universal Temporal Knowledge Graph 연구를 기반으로 하며, Andrej Karpathy의 통찰을 따릅니다: *"Obsidian은 IDE이고, 언어 모델은 프로그래머이며, 위키는 코드베이스입니다."*

## 품질 상태

| 메트릭 | 상태 |
|--------|--------|
| 테스트 | 626 통과 |
| 타입 안전성 | mypy 0 에러 |
| 린트 | ruff 0 위반 |
| 경고 | 0 pytest 경고 |
| 커버리지 | 81%+ |
| SPEC | 19 완료, 0 진행 중 |

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

**요구 사항:** Python 3.11 이상 (3.13 권장).

### GitHub에서 (사용자 권장)

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

### 에이전트 스킬 설치

AI 에이전트(Claude Code 등)가 지식 그래프 명령을 직접 사용할 수 있도록 `/mnemosyne` 스킬을 설치하세요:

```bash
# 기본: ~/.claude/skills/mnemosyne/에 설치
mnemosyne skill install

# 다른 에이전트 프레임워크 (전역 ~/.agents/skills/)
mnemosyne skill install --target agents

# 강제 재설치 (동일하더라도)
mnemosyne skill install --force

# 사용자 정의 경로
mnemosyne skill install --path ~/my-agent/skills
```

설치 후 Claude Code에서 `/mnemosyne`을 입력하여 지식 그래프를 수집, 쿼리, 추출 및 관리할 수 있습니다.

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

## 핵심 기능

- **제로 API 비용**: Tree-sitter AST 구문 분석(6개 언어), NLP용 로컬 SLM
- **지식 복합**: Wiki 레이어가 추출 간 지식을 누적
- **시간적 추적**: 타임스탬프가 있는 엔티티 버전 기록
- **세션 범위**: 계층적 프로젝트/주제/세션 범위 지정
- **FTS5 퍼지 검색**: SQLite FTS5 BM25를 통한 순위 엔티티 검색
- **증분 추출**: SHA-256 콘텐츠 해시 추적
- **다중 도메인**: 코딩, 일상 생활, 법률 스키마
- **프로토콜 기반**: 확장 가능한 언어 지원을 위한 `LanguageExtractor` 프로토콜
- **프로덕션 준비 완료**: mypy strict, ruff clean, 626 테스트, 81%+ 커버리지
