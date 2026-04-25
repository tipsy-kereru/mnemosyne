---
id: SPEC-SESSION-002
version: "1.0.0"
status: draft
created: "2026-04-25"
updated: "2026-04-25"
author: Seung Hyun Myung
priority: medium
issue_number: 0
---

# SPEC-SESSION-002: Session Integration Layer

## HISTORY

- 2026-04-25: Initial draft created. Depends on SPEC-SESSION-001 (session hierarchy, ScopeManager, scope-aware query engine).

## Overview

SPEC-SESSION-001이 구현한 세션 계층(Session, Project, Topic)과 범위 인식 쿼리 엔진을 Joplin 플러그인, 추출 파이프라인, 프로젝트 문서에 통합한다. 이 SPEC은 세 가지 통합 경로를 다룬다: (1) Joplin 노트에서 세션 메타데이터 감지 및 범위 인식 엔티티 추출, (2) Tree-sitter/SLM 추출기에 세션 컨텍스트 전달, (3) AGENTS.md/CLAUDE.md에 세션 인식 사용법 문서화.

## Scope

### In Scope

- Joplin 플러그인의 YAML frontmatter에서 세션 메타데이터 감지
- Joplin 플러그인에서 추출된 엔티티에 scope_id 및 source_channel 할당
- `@session:` 및 `@project:` 수식어를 포함하는 범위 인식 위키 링크 구문
- Joplin 플러그인 설정에 scope 계층 지속(persist)
- TreeSitterExtractor 및 SemanticExtractor에 선택적 scope_id/source_channel 파라미터 추가
- 기존 추출 호출의 완전한 하위 호환성 보장
- AGENTS.md 및 CLAUDE.md에 세션 인식 사용 패턴 추가

### Out of Scope

- Joplin 플러그인과 SQLite knowledge.db 간의 실시간 동기화 브릿지
- Joplin 내 세션 관리 UI (그래프 뷰의 scope 그룹화 포함)
- 추출 파이프라인의 자동 세션 분류 (scope_id 자동 추론)
- 위키 링크 렌더링에서 scope 기반 접근 제어
- Joplin 플러그인을 위한 별도 npm 패키지 배포

---

## Requirements

### REQ-001: Joplin Plugin Session Metadata Detection

**When** 노트 콘텐츠에 YAML frontmatter(`---` 마커 사이)가 포함되어 있고, **the system shall** 해당 frontmatter에서 `session_id`, `project`, `topic`, `channel` 필드를 파싱하여 세션 컨텍스트를 감지한다.

EARS: **When** `extractEntitiesFromNote()` 메서드가 노트 콘텐츠를 수신하면, 플러그인은 **shall** YAML `---` 구분자 사이의 frontmatter를 파싱하여 다음 필드를 추출한다:
- `session_id` (string, optional) — 세션 식별자
- `project` (string, optional) — 프로젝트 이름
- `topic` (string, optional) — 토픽 이름
- `channel` (string, optional) — 소스 채널 (기본값: `'joplin'`)

frontmatter가 없는 경우, 플러그인은 **shall** 콘텐츠 패턴에서 도메인을 감지하는 기존 `detectDomain()` 동작으로 폴백한다.

frontmatter 파싱은 **shall** 기존 `detectDomain()` 호출 전에 실행되어, 세션 메타데이터가 도메인 감지를 보강한다.

### REQ-002: Joplin Plugin Scope-Aware Entity Extraction

**When** 세션 메타데이터가 감지되면, **the system shall** 추출된 모든 엔티티에 해당 scope_id와 source_channel을 할당한다.

EARS: **When** 세션 메타데이터가 노트 frontmatter에서 성공적으로 파싱되면, `extractBasedOnDomain()` 메서드는 **shall** 추출된 각 엔티티의 `scope_id` 필드를 파싱된 `session_id`(또는 `project` > `topic` > `session_id` 우선순위에 따른 첫 번째 사용 가능한 식별자)로 설정하고, `source_channel` 필드를 파싱된 `channel` 값(기본값: `'joplin'`)으로 설정한다.

`KnowledgeGraphEntity` 인터페이스는 **shall** 두 개의 선택적 필드를 포함하도록 확장된다: `scope_id?: string` 및 `source_channel?: string`.

세션 메타데이터가 감지되지 않은 경우, 엔티티는 **shall** 기존 동작대로 `scope_id` 및 `source_channel` 없이 생성된다.

### REQ-003: Joplin Plugin Scope-Aware Wiki Links

**The system shall** scope 수식어를 포함하는 확장된 위키 링크 구문을 지원한다.

EARS: `processWikiLinks()` 메서드는 **shall** 기존 위키 링크 패턴에 더해 다음 확장 구문을 파싱한다:
- `[[entity:type:name@session:my-session]]` — 특정 세션 scope의 엔티티
- `[[entity:type:name@project:my-project]]` — 특정 프로젝트 scope의 엔티티
- `[[entity:type:name@channel:code]]` — 특정 채널의 엔티티
- 복합: `[[entity:type:name@session:my-session@channel:discord]]`

확장 구문 파싱은 **shall** `@` 문자 뒤의 `key:value` 쌍을 추출하여, 렌더링된 HTML에 `data-scope-session`, `data-scope-project`, `data-scope-channel` 데이터 속성으로 반영한다.

기존 위키 링크 패턴(`[[note]]`, `[[entity:type:name]]`, `[[graph:query]]`)은 **shall** 변경 없이 계속 작동한다. `@` 수식어가 없는 링크는 기존 렌더링 동작을 유지한다.

### REQ-004: Joplin Plugin Scope Persistence

**The system shall** scope 계층 데이터를 플러그인 설정에 지속(persist)하여 플러그인 재시작 후에도 유지한다.

EARS: `saveKnowledgeGraph()` 메서드는 **shall** 기존 `entities` 및 `relations` 배열과 함께 `scopes` 배열을 JSON 데이터에 포함시킨다. `loadKnowledgeGraph()` 메서드는 **shall** 저장된 scope 데이터를 역직렬화하여 인메모리 `scopeIndex: Map<string, ScopeInfo>`를 복원한다.

`ScopeInfo` 인터페이스는 **shall** 다음 필드를 포함한다: `id`, `name`, `scope_type` (`'project'` | `'topic'` | `'session'`), `parent_id` (optional).

저장된 데이터에 `scopes` 배열이 없는 경우(기존 데이터), `loadKnowledgeGraph()`는 **shall** 오류 없이 빈 `scopeIndex`로 초기화한다.

### REQ-005: Extraction Pipeline Session Parameters

**The system shall** TreeSitterExtractor 및 SemanticExtractor가 선택적 scope_id 및 source_channel 파라미터를 수락하도록 확장한다.

EARS: `TreeSitterExtractor` 클래스는 **shall** `extract_file()` 및 `extract_directory()` 메서드에 선택적 `scope_id: Optional[str] = None` 및 `source_channel: Optional[str] = None` 파라미터를 추가한다. `SemanticExtractor` 클래스는 **shall** `extract()` 메서드에 동일한 선택적 파라미터를 추가한다.

**When** `scope_id` 및 `source_channel`이 제공되면, 추출기는 **shall**:
- `CodeEntity` dataclass에 `scope_id` 및 `source_channel` 필드를 추가하고, 추출된 모든 엔티티에 전달받은 값을 설정
- `ExtractedEntity` 및 `ExtractedRelation` dataclass에 `scope_id` 및 `source_channel` 필드를 추가하고, 추출된 모든 결과에 전달받은 값을 설정

`to_wiki_format()` 메서드는 **shall** `scope_id`가 있는 엔티티의 경우 위키 출력에 scope 정보를 포함한다.

`GLiNER2Extractor.extract()` 및 `REBELExtractor.extract()` 메서드는 **shall** 동일한 선택적 파라미터를 수락하고, 반환된 엔티티/관계에 전파한다.

### REQ-006: Backward Compatibility

**The system shall** scope 파라미터 없이 호출되는 모든 기존 추출 호출이 기존 동작대로 계속 작동하도록 보장한다.

EARS: 기존 호출 패턴은 **shall** 수정 없이 작동한다:
- `extractor.extract_file(path)` — `scope_id=None`, `source_channel=None`로 동작
- `extractor.extract_directory(path)` — 동일
- `semantic_extractor.extract(text, types)` — 동일
- `plugin.extractEntitiesFromNote(note)` — frontmatter 없으면 기존 동작

기본값은 **shall** `scope_id=None`(글로벌 scope) 및 `source_channel='unknown'`이다. 기존 `CodeEntity`, `ExtractedEntity`, `ExtractedRelation` 인스턴스는 **shall** 새 필드가 선택적이거나 기본값을 가지므로 역직렬화에 실패하지 않는다.

`dataclasses.asdict()`를 사용하는 기존 JSON 직렬화는 **shall** 추가 필드를 포함하지만, 기존 소비자는 알 수 없는 키를 무시하므로 영향을 받지 않는다.

### REQ-007: Documentation Updates

**The system shall** AGENTS.md 및 CLAUDE.md를 세션 인식 사용 패턴으로 업데이트한다.

EARS: AGENTS.md는 **shall** 다음 섹션을 포함하도록 업데이트된다:
- "Session-Aware Extraction" 섹션: scope_id/source_channel 파라미터가 있는 추출 예제
- "Session-Aware Queries" 섹션: `@session:`, `@project:`, `@channel:` 수식어가 있는 쿼리 예제

CLAUDE.md는 **shall** "Usage Commands" 섹션에 세션 인식 쿼리 예제를 추가하도록 업데이트된다:
- scope 수식어가 있는 `python -m core.extraction.deterministic.code_parser` 예제
- scope 수식어가 있는 `python -m core.extraction.semantic.slm_extractor` 예제
- scope 파라미터가 있는 `python -m core.graph.knowledge_graph` 쿼리 예제

---

## Files to Modify

| File | Change Type | Description |
|------|-------------|-------------|
| `joplin-plugin/knowledge-graph/src/index.ts` | MODIFY | Frontmatter 파싱, scope 인식 추출, scope 위키 링크, scope 지속 |
| `core/extraction/deterministic/code_parser.py` | MODIFY | CodeEntity에 scope_id/source_channel 추가, extract 메서드 파라미터 확장 |
| `core/extraction/semantic/slm_extractor.py` | MODIFY | ExtractedEntity/Relation에 scope_id/source_channel 추가, extract 메서드 파라미터 확장 |
| `AGENTS.md` | MODIFY | 세션 인식 추출 및 쿼리 패턴 추가 |
| `CLAUDE.md` | MODIFY | Usage Commands 섹션에 scope 파라미터 예제 추가 |
| `tests/test_integration_session.py` | NEW | 추출 파이프라인 + Joplin 플러그인 세션 컨텍스트 통합 테스트 |

## Delta Markers

### [DELTA] joplin-plugin/knowledge-graph/src/index.ts

- [NEW] `SessionMetadata` interface — session_id, project, topic, channel 필드
- [NEW] `ScopeInfo` interface — id, name, scope_type, parent_id
- [NEW] `scopeIndex: Map<string, ScopeInfo>` — 인메모리 scope 계층
- [MODIFY] `KnowledgeGraphEntity` interface — scope_id, source_channel 선택적 필드 추가
- [MODIFY] `KnowledgeGraphRelation` interface — scope_id, source_channel 선택적 필드 추가
- [NEW] `parseFrontmatter(content)` — YAML frontmatter 파싱 메서드
- [MODIFY] `extractEntitiesFromNote()` — frontmatter 파싱 호출, scope 컨텍스트 전달
- [MODIFY] `detectDomain()` — 세션 메타데이터를 도메인 감지에 통합
- [MODIFY] `extractBasedOnDomain()` — scope_id, source_channel을 추출 엔티티에 할당
- [MODIFY] `processWikiLinks()` — `@session:`, `@project:`, `@channel:` 수식어 파싱
- [MODIFY] `loadKnowledgeGraph()` — scopes 배열 역직렬화, scopeIndex 복원
- [MODIFY] `saveKnowledgeGraph()` — scopeIndex를 scopes 배열로 직렬화

### [DELTA] core/extraction/deterministic/code_parser.py

- [MODIFY] `CodeEntity` dataclass — scope_id: Optional[str], source_channel: Optional[str] 필드 추가
- [MODIFY] `TreeSitterExtractor.extract_file()` — scope_id, source_channel 선택적 파라미터 추가
- [MODIFY] `TreeSitterExtractor.extract_directory()` — scope_id, source_channel 선택적 파라미터 추가
- [MODIFY] `TreeSitterExtractor._extract_python()` — scope 컨텍스트를 CodeEntity에 전달
- [MODIFY] `TreeSitterExtractor._extract_js_ts()` — scope 컨텍스트를 CodeEntity에 전달
- [MODIFY] `TreeSitterExtractor._extract_go()` — scope 컨텍스트를 CodeEntity에 전달
- [MODIFY] `TreeSitterExtractor._extract_rust()` — scope 컨텍스트를 CodeEntity에 전달
- [MODIFY] `to_wiki_format()` — scope_id가 있으면 위키 출력에 scope 정보 포함

### [DELTA] core/extraction/semantic/slm_extractor.py

- [MODIFY] `ExtractedEntity` dataclass — scope_id: Optional[str], source_channel: Optional[str] 필드 추가
- [MODIFY] `ExtractedRelation` dataclass — scope_id: Optional[str], source_channel: Optional[str] 필드 추가
- [MODIFY] `GLiNER2Extractor.extract()` — scope_id, source_channel 선택적 파라미터 추가
- [MODIFY] `GLiNER2Extractor._extract_with_model()` — scope 컨텍스트를 엔티티에 전달
- [MODIFY] `GLiNER2Extractor._extract_fallback()` — scope 컨텍스트를 엔티티에 전달
- [MODIFY] `REBELExtractor.extract()` — scope_id, source_channel 선택적 파라미터 추가
- [MODIFY] `REBELExtractor._extract_with_model()` — scope 컨텍스트를 관계에 전달
- [MODIFY] `REBELExtractor._extract_fallback()` — scope 컨텍스트를 관계에 전달
- [MODIFY] `SemanticExtractor.extract()` — scope_id, source_channel 선택적 파라미터 추가, 하위 추출기에 전파

### [DELTA] AGENTS.md

- [NEW] "Session-Aware Extraction" 섹션 — scope 파라미터가 있는 추출 예제
- [NEW] "Session-Aware Queries" 섹션 — scope 수식어가 있는 쿼리 예제

### [DELTA] CLAUDE.md

- [MODIFY] "Usage Commands" > "Extraction" 섹션 — scope_id/source_channel 파라미터가 있는 CLI 예제
- [MODIFY] "Usage Commands" > "Knowledge Graph Query" 섹션 — scope 수식어가 있는 쿼리 예제

### [NEW] tests/test_integration_session.py

- [NEW] 추출 파이프라인 + 세션 컨텍스트 통합 테스트
- [NEW] Joplin 플러그인 scope 감지 단위 테스트
- [NEW] 위키 링크 scope 수식어 파싱 테스트
- [NEW] scope 지속(persistence) 라운드트립 테스트
