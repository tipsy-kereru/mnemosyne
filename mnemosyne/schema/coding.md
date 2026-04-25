# Coding Domain Schema

## Entity Types

```yaml
function:
  description: "Code function or method"
  properties:
    - name
    - signature
    - language: [python, javascript, rust, go, typescript, java]
    - parameters: [{name, type, default}]
    - return_type: string
    - file_path: string
    - lines: {start, end}
    - complexity: [low, medium, high, critical]
    - test_coverage: float

class:
  description: "Object-oriented class or struct"
  properties:
    - name
    - language: string
    - file_path: string
    - methods: [function_id]
    - attributes: [{name, type}]
    - inherits: [class_id]

module:
  description: "Code module, package, or namespace"
  properties:
    - name
    - type: [package, namespace, crate, gem]
    - path: string
    - exports: [function_id, class_id]
    - imports: [module_id]

api:
  description: "API endpoint or interface"
  properties:
    - name
    - type: [rest, graphql, grpc, websocket]
    - endpoint: string
    - method: [GET, POST, PUT, DELETE, PATCH]
    - request_schema: string
    - response_schema: string
    - auth_required: boolean

bug:
  description: "Bug report or issue"
  properties:
    - id
    - title
    - severity: [critical, high, medium, low]
    - status: [open, in_progress, resolved, wontfix]
    - affected_functions: [function_id]
    - introduced_in: commit_hash
    - related_tests: [test_id]

feature:
  description: "Feature request or enhancement"
  properties:
    - id
    - title
    - status: [planned, in_progress, completed]
    - implements: api_id | function_id
    - priority: [must_have, should_have, could_have, wont_have]

test:
  description: "Test case or suite"
  properties:
    - name
    - type: [unit, integration, e2e]
    - covers: [function_id, class_id]
    - status: [passing, failing, skipped]
    - file_path: string

dependency:
  description: "External dependency or library"
  properties:
    - name
    - version: string
    - type: [runtime, dev, peer, optional]
    - repository: string
    - vulnerabilities: [string]
    - used_by: [module_id, function_id]
```

## Relationship Types

```yaml
function.imports: module
function.calls: function
function.defined_in: class | module
function.tested_by: test
function.caught_by: bug

class.contains: function
class.imports: module
class.inherits: class

module.exports: function | class | api
module.imports: module

bug.affected: function | class
bug.resolved_by: commit

feature.implements: api | function
feature.requires: dependency

test.covers: function | class | api
test.triggers: bug
```

## Extraction Rules

1. **Source files**: Tree-sitter AST parsing (zero-LLM)
2. **README/docs**: GLiNER2 NER for entity extraction
3. **Issue trackers**: Structured extraction of bug/feature
4. **Dependency files**: Lockfile parsing (package.json, Cargo.toml, etc.)