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

# SPEC-SESSION-002: Implementation Plan

## Dependencies

- **SPEC-SESSION-001** (DONE): ScopeManager, scope_id/source_channel on Entity/Relation, @modifiers in query language. 75 tests passing.

## Technical Approach

### Phase 1: Python Extraction Pipeline (REQ-005, REQ-006)

두 개의 Python 추출 모듈에 scope 파라미터를 추가한다. 기존 메서드 시그니처에 선택적 파라미터를 추가하는 방식으로 하위 호환성을 보장한다.

**code_parser.py 변경 전략:**
- `CodeEntity` dataclass에 `scope_id: Optional[str] = None` 및 `source_channel: Optional[str] = None` 추가
- `extract_file(file_path, scope_id=None, source_channel=None)` 시그니처 변경
- 내부 `_extract_*` 메서드에 scope 컨텍스트를 파라미터로 스레딩
- `to_wiki_format()`에서 scope_id가 있으면 위키 헤더에 scope 정보 표시

**slm_extractor.py 변경 전략:**
- `ExtractedEntity` 및 `ExtractedRelation` dataclass에 동일한 필드 추가
- `GLiNER2Extractor.extract()`, `REBELExtractor.extract()`, `SemanticExtractor.extract()`에 선택적 파라미터 추가
- 모델 기반 추출과 폴백 추출 모두 scope 컨텍스트 전파

### Phase 2: Joplin Plugin Session Detection (REQ-001, REQ-002)

TypeScript 플러그인에 YAML frontmatter 파싱을 추가한다.

**Frontmatter 파싱 전략:**
- `---` 구분자 사이의 텍스트를 간단한 라인 기반 파서로 처리 (완전한 YAML 파서 불필요)
- `key: value` 형식의 라인을 정규식으로 파싱
- 파싱 실패 시 기존 동작으로 조용히 폴백

**Scope 컨텍스트 전달:**
- `parseFrontmatter()`가 `SessionMetadata | null` 반환
- `extractBasedOnDomain()`이 세션 메타데이터를 수신하여 엔티티에 scope_id/source_channel 설정
- `KnowledgeGraphEntity` 인터페이스에 선택적 필드 추가

### Phase 3: Joplin Plugin Wiki Links (REQ-003)

기존 위키 링크 정규식을 확장하여 `@key:value` 수식어를 지원한다.

**정규식 확장 전략:**
- 기존: `/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g`
- 확장: 기본 패턴은 동일, 파싱된 path에서 `@` 수식어를 별도로 추출
- `@session:name`, `@project:name`, `@channel:name` 형식 지원
- 수식어가 없으면 기존 렌더링 유지

### Phase 4: Joplin Plugin Scope Persistence (REQ-004)

플러그인 설정의 JSON 직렬화에 scope 데이터를 추가한다.

**지속 전략:**
- 기존 `{ entities, relations }` JSON 구조에 `scopes` 배열 추가
- `ScopeInfo` 인터페이스 정의: `{ id, name, scope_type, parent_id? }`
- 인메모리 `scopeIndex: Map<string, ScopeInfo>` 추가
- 로드 시 `scopes` 배열이 없으면 빈 Map으로 초기화 (기존 데이터 호환)

### Phase 5: Documentation (REQ-007)

AGENTS.md와 CLAUDE.md에 세션 인식 사용 패턴을 추가한다.

### Phase 6: Integration Tests

추출 파이프라인과 Joplin 플러그인의 세션 컨텍스트 처리를 검증하는 통합 테스트를 작성한다.

## Milestones

### M1: Python Extraction Pipeline — Priority High

- CodeEntity, ExtractedEntity, ExtractedRelation dataclass 확장
- TreeSitterExtractor 메서드 시그니처 변경
- SemanticExtractor 메서드 시그니처 변경
- 기존 테스트 회귀 확인 (기본 파라미터로 호출 시 동일 결과)
- 새 scope 파라미터가 있는 단위 테스트 작성

### M2: Joplin Plugin Frontmatter & Scope — Priority High

- SessionMetadata 및 ScopeInfo 인터페이스 정의
- parseFrontmatter() 메서드 구현
- extractEntitiesFromNote()에 scope 컨텍스트 통합
- KnowledgeGraphEntity/Relation 인터페이스 확장

### M3: Joplin Plugin Wiki Links & Persistence — Priority Medium

- processWikiLinks()에 @ 수식어 파싱 추가
- scopeIndex 인메모리 저장소 추가
- saveKnowledgeGraph()/loadKnowledgeGraph()에 scope 직렬화/역직렬화 추가

### M4: Documentation & Tests — Priority Medium

- AGENTS.md 세션 인식 섹션 추가
- CLAUDE.md Usage Commands 업데이트
- 통합 테스트 (tests/test_integration_session.py) 작성

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Joplin 플러그인과 SQLite knowledge.db 간 데이터 불일치 | Medium | 플러그인은 인메모리 Map 사용, 동기화 브릿지는 out of scope로 명시 |
| YAML frontmatter 파싱 엣지 케이스 (중첩 `---`, 잘못된 형식) | Low | 간단한 라인 기반 파서 사용, 파싱 실패 시 조용히 폴백 |
| 추출 메서드 체인에 scope 파라미터 스레딩 복잡성 | Low | 선택적 파라미터로 기본값 None, 하위 메서드는 kwargs 사용 |
| 기존 JSON 직렬화 소비자가 새 필드를 처리하지 못함 | Low | dataclasses.asdict()에 필드 추가, 소비자는 알 수 없는 키 무시 가능 |

## Acceptance Criteria Summary

1. CodeEntity, ExtractedEntity, ExtractedRelation에 scope_id/source_channel 필드 존재
2. 기존 추출 호출이 파라미터 없이 동일 결과 생성
3. scope 파라미터가 있으면 추출 결과에 scope_id/source_channel 값 포함
4. Joplin 플러그인이 YAML frontmatter에서 session_id/project/topic/channel 파싱
5. 위키 링크 `[[entity:type:name@session:x]]` 구문 파싱 및 렌더링
6. 플러그인 설정에 scope 계층 지속 및 복원
7. AGENTS.md 및 CLAUDE.md에 세션 인식 예제 포함
8. 모든 통합 테스트 통과
