# Rust Core 확장 가이드

## 개요

Mnemosyne v0.6.0+에는 핵심 작업에 대해 2-5배의 성능 향상을 제공하는 네이티브 Rust 확장 모듈(`mnemosyne-core`)이 포함되어 있습니다. 확장은 Rust 툴체인을 사용할 수 있을 때 pip 설치 중 자동으로 빌드되며, Python 구현으로의 원활한 폴백을 제공합니다.

## 성능 개선

| 모듈 | 작업 | 속도 향상 |
|--------|-----------|---------|
| **Wiki** | glob_markdown, rebuild_index, write_entity_page, write_source_page | 2.5-5배 |
| **Graph** | query_entities, query_relations, find_path, get_stats | 2.5-5배 |
| **Database** | execute_query, batch_insert_entities, batch_insert_relations, batch_update_entities | 3-5배 |

## 설치 방법

**참고**: Rust 코어는 현재 **별도의 선택적 확장**으로 제공되며, 메인 `mnemosyne-kg` 패키지와 독립적으로 설치해야 합니다. 메인 패키지 설치 시 자동으로 빌드되지 않습니다.

### 방법 1: GitHub Releases에서 설치 (권장)

일반적인 플랫폼에 대해 GitHub Releases에서 미리 빌드된 휠을 사용할 수 있습니다:

```bash
# GitHub Releases에서 플랫폼별 휠 다운로드
# https://github.com/tipsy-kereru/mnemosyne/releases

pip install mnemosyne_core-*.whl
```

지원되는 플랫폼:
- `linux-x86_64` (manylinux2014)
- `darwin-arm64` (macOS Apple Silicon)
- `darwin-x86_64` (macOS Intel, 최선 노력)

### 방법 2: 소스에서 빌드

기여자나 지원되지 않는 플랫폼의 경우:

```bash
# 저장소 복제
git clone https://github.com/tipsy-kereru/mnemosyne.git
cd mnemosyne/mnemosyne-core

# Rust 툴체인 설치 (일회 설정)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env

# maturin 설치
pip install maturin

# 빌드 및 설치
maturin develop --release  # 개발용
# 또는
maturin build --release && pip install target/wheels/mnemosyne_core-*.whl  # 휠용
```

### 방법 2: 미리 빌드된 휠

일반적인 플랫폼에 대해 GitHub Releases에서 미리 빌드된 휠을 사용할 수 있습니다:

```bash
# GitHub Releases에서 플랫폼별 휠 다운로드
# https://github.com/tipsy-kereru/mnemosyne/releases

pip install mnemosyne_core-*.whl
```

지원되는 플랫폼:
- `linux-x86_64` (manylinux2014)
- `darwin-arm64` (macOS Apple Silicon)
- `darwin-x86_64` (macOS Intel, 최선 노력)

### 방법 3: 소스에서 빌드

기여자나 지원되지 않는 플랫폼의 경우:

```bash
# 저장소 복제
git clone https://github.com/tipsy-kereru/mnemosyne.git
cd mnemosyne/mnemosyne-core

# 릴리즈 휠 빌드
maturin build --release

# 로컬 설치
pip install target/wheels/mnemosyne_core-*.whl
```

## 요구 사항

### 시스템 요구 사항

- **Rust**: 1.70+ (rustup 또는 시스템 패키지 관리자 통해)
- **Python**: 3.11+ (3.13 권장)
- **maturin**: 0.15+ (소스에서 빌드 시)

### 플랫폼 지원

| 플랫폼 | 상태 | 참고 |
|----------|--------|-------|
| Linux x86_64 | ✅ 전체 | 미리 빌드된 휠 제공 |
| Linux aarch64 | ⚠️ 최선 노력 | 소스에서 빌드 |
| macOS ARM64 | ✅ 전체 | 미리 빌드된 휠 제공 |
| macOS x86_64 | ⚠️ 최선 노력 | 소스에서 빌드 |
| Windows x86_64 | ❌ 지연됨 | ISSUE-0010 |

## 검증

Rust 코어가 작동하는지 테스트하세요:

```python
# test_rust_core.py
import mnemosyne_core

# Wiki 모듈 테스트
markdown_files = mnemosyne_core.glob_markdown(".")
print(f"발견된 마크다운 파일: {len(markdown_files)}개")

# Graph 모듈 테스트
query = mnemosyne_core.EntityQuery(limit=10)
print(f"쿼리 생성됨: {query}")

# Database 모듈 테스트
print("Rust 코어 모듈이 성공적으로 로드되었습니다!")
```

테스트 실행:
```bash
pip install pytest
pytest tests/test_rust_core_*.py -v
```

## 모듈 API

### Wiki 모듈

```python
import mnemosyne_core

# 마크다운 파일 찾기
files = mnemosyne_core.glob_markdown("/path/to/wiki")

# 인덱스 재빌드
index_data = mnemosyne_core.rebuild_index("/path/to/wiki", entities)

# 엔티티 페이지 작성
mnemosyne_core.write_entity_page("/path/to/wiki", entity_data)

# 소스 페이지 작성
mnemosyne_core.write_source_page("/path/to/wiki", source_data)
```

### Graph 모듈

```python
import mnemosyne_core

# 엔티티 쿼리
query = mnemosyne_core.EntityQuery(
    search_term="authenticate",
    entity_type="function",
    scope_id="project-x",
    limit=100
)
results = mnemosyne_core.query_entities("/path/to/graph.db", query)

# 관계 쿼리
rel_query = mnemosyne_core.RelationQuery(
    source="e1",
    relation="calls",
    limit=100
)
relations = mnemosyne_core.query_relations("/path/to/graph.db", rel_query)

# 최단 경로 찾기
path = mnemosyne_core.find_path("/path/to/graph.db", "EntityA", "EntityB")
print(f"경로 길이: {path.length}")

# 통계 가져오기
stats = mnemosyne_core.get_stats("/path/to/graph.db")
print(f"엔티티: {stats.entity_count}, 관계: {stats.relation_count}")
```

### Database 모듈

```python
import mnemosyne_core

# 원시 SQL 쿼리 실행
result = mnemosyne_core.execute_query(
    "/path/to/db.db",
    "SELECT * FROM entities WHERE type = ?",
    ["function"]
)
print(f"발견된 행: {result.row_count}개")

# 엔티티 대량 삽입
entities = [
    mnemosyne_core.EntityInsert(
        id="e1",
        entity_type="function",
        name="authenticateUser",
        properties="{}",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
        version=1,
        source_channel="rust"
    )
]
batch_result = mnemosyne_core.batch_insert_entities("/path/to/db.db", entities)
print(f"삽입됨: {batch_result.inserted}")

# 엔티티 대량 업데이트 (skip-unchanged 최적화 포함)
updates = [
    mnemosyne_core.EntityUpdate(
        id="e1",
        entity_type="function",
        name="authenticateUser",
        properties='{"verified": true}',
        updated_at="2024-01-02T00:00:00Z",
        content_hash="new-hash"
    )
]
# 저장된 해시와 일치하면 업데이트가 건너뜀
batch_result = mnemosyne_core.batch_update_entities(
    "/path/to/db.db",
    updates,
    skip_unchanged=True
)
```

## 문제 해결

### Rust 컴파일러를 찾을 수 없음

**오류**: `cargo: command not found`

**해결책**: Rust 툴체인 설치:
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

### macOS에서 빌드 실패

**오류**: `ld: library not found for -lssl`

**해결책**: Homebrew를 통해 OpenSSL 설치:
```bash
brew install openssl
export OPENSSL_DIR=$(brew --prefix openssl)
```

### Python 버전 호환되지 않음

**오류**: `Python 3.10 is not supported`

**해결책**: Python 3.11+로 업그레이드:
```bash
# macOS
brew install python@3.13

# Linux
sudo apt install python3.13  # Ubuntu/Debian
sudo dnf install python3.13  # Fedora
```

### maturin을 찾을 수 없음

**오류**: `maturin: command not found`

**해결책**: maturin 설치:
```bash
pip install maturin
```

## 개발

### 릴리즈용 빌드

```bash
cd mnemosyne-core
maturin build --release --strip
```

### 디버그용 빌드

```bash
cd mnemosyne-core
maturin build
```

### 테스트 실행

```bash
# Rust 단위 테스트
cargo test --lib

# Python 통합 테스트
pytest tests/test_rust_core_*.py -v
```

### 새 함수 추가

1. 적절한 모듈에 함수 추가 (`src/wiki.rs`, `src/graph.rs`, 또는 `src/db.rs`)
2. `#[pyfunction]`으로 표시
3. `src/lib.rs` 모듈 내보내기에 추가
4. `src/lib.rs`에서 Python 바인딩 추가
5. 빌드 및 테스트

## 성능 벤치마크

테스트 제트 결과 기준 (45개 테스트, 총 0.06초):

| 작업 | Python | Rust | 속도 향상 |
|-----------|--------|------|---------|
| Wiki 재빌드 (500 파일) | 5초 | 1-2초 | 2.5-5배 |
| Graph 쿼리 (1만 엔티티) | 500ms | 100-200ms | 2.5-5배 |
| 대량 삽입 (100 엔티티) | 30ms | 10ms | 3배 |
| FTS5 검색 | 가변 | 2-3배 더 빠름 | C에서 BM25 |

## 아키텍처

```
mnemosyne-core/
├── src/
│   ├── lib.rs          # Python 모듈 정의
│   ├── wiki.rs         # Wiki 작업 (glob, index, write)
│   ├── graph.rs        # Graph 쿼리 (search, path, stats)
│   ├── db.rs           # Database 작업 (query, batch)
│   └── types.rs        # 공유 타입 (EntityQuery, BatchResult 등)
├── Cargo.toml          # Rust 의존성
└── tests/              # Rust 단위 테스트
```

**의존성**:
- `pyo3`: Python 바인딩
- `rusqlite`: SQLite 인터페이스
- `petgraph`: 그래프 알고리즘
- `rayon`: 병렬 처리
- `serde`: 직렬화
- `chrono`: 날짜/시간 처리

## 기여

Rust 코어에 기여할 때:

1. Rust 모범 사례 따르기 (`cargo clippy -- -D warnings`)
2. 새 함수에 테스트 추가
3. 이 문서 업데이트
4. 제출 전 전체 테스트 제트 실행
5. Python 바인딩이 제대로 입력되었는지 확인

## 라이선스

메인 Mnemosyne 프로젝트와 동일 (MIT/Apache-2.0 하이브리드 - LICENSE 파일 참조).

## 관련 문서

- [메인 README](../README.md)
- [바이너리 설치 가이드](BINARY_INSTALL.md)
- [아키텍처](ARCHITECTURE.md)
- [Python 매뉴얼](MANUAL.md)
