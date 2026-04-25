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

# SPEC-SESSION-002: Acceptance Criteria

## Test Scenarios

### Scenario 1: Python Extraction Pipeline Scope Parameters

**Given** TreeSitterExtractor가 scope_id="session-1" 및 source_channel="discord" 파라미터로 초기화됨
**When** `extract_file("example.py", scope_id="session-1", source_channel="discord")` 호출
**Then** 반환된 모든 CodeEntity의 scope_id가 "session-1"이고 source_channel이 "discord"임

**Given** SemanticExtractor가 scope_id="proj-alpha" 및 source_channel="slack" 파라미터로 초기화됨
**When** `extract(text, entity_types, scope_id="proj-alpha", source_channel="slack")` 호출
**Then** 반환된 모든 ExtractedEntity 및 ExtractedRelation의 scope_id가 "proj-alpha"이고 source_channel이 "slack"임

### Scenario 2: Backward Compatibility

**Given** 기존 호출 코드가 scope 파라미터 없이 extract_file()을 호출함
**When** `extractor.extract_file(Path("example.py"))` 호출
**Then** 반환된 CodeEntity의 scope_id가 None이고 source_channel이 None임
**And** 반환된 결과가 SPEC-SESSION-001 구현 전과 동일함 (필드 수 제외)

**Given** 기존 호출 코드가 scope 파라미터 없이 SemanticExtractor.extract()를 호출함
**When** `extractor.extract(text, types)` 호출
**Then** 반환된 결과의 entities 및 relations에 scope_id=None, source_channel=None 포함
**And** 기존 필드(type, text, confidence 등)가 변경 없이 유지됨

### Scenario 3: Joplin Frontmatter Parsing

**Given** 노트 콘텐츠가 YAML frontmatter를 포함함:
```
---
session_id: impl-session
project: snake-game
channel: joplin
---
# Note content...
```
**When** `parseFrontmatter(content)` 호출
**Then** SessionMetadata { session_id: "impl-session", project: "snake-game", topic: null, channel: "joplin" } 반환

**Given** 노트 콘텐츠에 YAML frontmatter가 없음
**When** `parseFrontmatter(content)` 호출
**Then** null 반환
**And** extractEntitiesFromNote()가 기존 detectDomain() 동작으로 진행

### Scenario 4: Scope-Aware Entity Extraction in Plugin

**Given** frontmatter에서 session_id="debug-session"이 파싱됨
**When** extractBasedOnDomain()이 엔티티를 추출함
**Then** 각 엔티티의 scope_id가 "debug-session"이고 source_channel이 "joplin"(frontmatter channel 기본값)임

### Scenario 5: Scope-Aware Wiki Link Parsing

**Given** 텍스트에 `[[entity:function:parse@session:my-session]]` 위키 링크가 포함됨
**When** `processWikiLinks(text)` 호출
**Then** 렌더링된 HTML에 `data-scope-session="my-session"` 속성이 포함됨

**Given** 텍스트에 `[[entity:function:parse@session:s1@channel:code]]` 위키 링크가 포함됨
**When** `processWikiLinks(text)` 호출
**Then** 렌더링된 HTML에 `data-scope-session="s1"` 및 `data-scope-channel="code"` 속성이 포함됨

**Given** 텍스트에 기존 형식의 `[[entity:function:parse]]` 위키 링크가 포함됨
**When** `processWikiLinks(text)` 호출
**Then** 기존 렌더링과 동일하게 data-scope-* 속성 없이 렌더링됨

### Scenario 6: Scope Persistence Roundtrip

**Given** scopeIndex에 3개의 scope가 저장됨 (project > topic > session 계층)
**When** `saveKnowledgeGraph()` 이후 `loadKnowledgeGraph()` 호출
**Then** 복원된 scopeIndex가 저장 전과 동일한 3개의 scope를 포함함
**And** 각 scope의 id, name, scope_type, parent_id가 정확히 복원됨

**Given** 기존 플러그인 데이터에 scopes 배열이 없음 (마이그레이션 시나리오)
**When** `loadKnowledgeGraph()` 호출
**Then** scopeIndex가 빈 Map으로 초기화됨
**And** entities 및 relations는 정상적으로 로드됨

## Edge Cases

### EC-001: Malformed Frontmatter

- `---` 구분자가 열리기만 하고 닫히지 않은 경우: frontmatter 없음으로 처리
- `key: value` 형식이 아닌 라인이 포함된 경우: 유효한 라인만 파싱, 나머지 무시
- 빈 frontmatter (`---\n---`): null 반환, 기존 동작으로 폴백

### EC-002: Wiki Link Edge Cases

- `@` 문자가 엔티티 이름에 포함된 경우: `@session:`, `@project:`, `@channel:` 패턴만 수식어로 인식
- 수식어만 있고 값이 없는 경우 (`@session:`): 해당 수식어 무시
- 알 수 없는 수식어 키 (`@unknown:value`): 무시, 오류 없음

### EC-003: Scope Parameter Propagation

- extract_directory()에 scope 파라미터가 제공되면 모든 하위 파일 추출에 동일 파라미터 적용
- SemanticExtractor.extract()에서 NER은 scope를 받지만 REBEL은 받지 않는 경우: 둘 다 받아야 함
- GLiNER2 모델이 로드되지 않은 폴백 모드에서도 scope_id/source_channel이 전파됨

### EC-004: JSON Serialization Compatibility

- 기존 asdict() 직렬화에 새 필드가 포함되어도 기존 JSON 소비자가 break되지 않음
- scope_id=None인 엔티티의 JSON에서 null 값 처리

## Quality Gate Criteria

### Definition of Done

- [ ] 모든 6개 시나리오의 Given-When-Then 조건 충족
- [ ] 4개 엣지 케이스에 대한 테스트 케이스 작성 및 통과
- [ ] 기존 추출 파이프라인 테스트 회귀 없음 (SPEC-SESSION-001의 75개 테스트 포함)
- [ ] CodeEntity, ExtractedEntity, ExtractedRelation dataclass에 scope_id/source_channel 필드 존재
- [ ] Joplin 플러그인 TypeScript 컴파일 오류 없음
- [ ] AGENTS.md에 Session-Aware Extraction 및 Session-Aware Queries 섹션 존재
- [ ] CLAUDE.md Usage Commands에 scope 파라미터 예제 포함
- [ ] 테스트 커버리지 85% 이상 (변경된 모듈 기준)

### Test Coverage Requirements

| Module | Minimum Coverage | Priority |
|--------|-----------------|----------|
| `core/extraction/deterministic/code_parser.py` | 85% | High |
| `core/extraction/semantic/slm_extractor.py` | 85% | High |
| `joplin-plugin/knowledge-graph/src/index.ts` | 80% | Medium |
| `tests/test_integration_session.py` | New file | High |

### Non-Functional Requirements

- **성능**: scope 파라미터 추가로 인한 추출 성능 저하가 5% 미만이어야 함
- **호환성**: 기존 JSON 형식에서 새 필드를 무시할 수 있어야 함 (forward compatibility)
- **견고성**: frontmatter 파싱 실패 시 플러그인이 중단되지 않아야 함
