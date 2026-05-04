#!/usr/bin/env python3
"""Generate large-vault benchmark fixtures.

Creates 500 entity pages and 200 source pages under the wiki root
using naming conventions entity_NNNN.md / source_NNNN.md so they
are distinguishable from real pages and safe to clean up.

REQ-BENCH-001-001 / SPEC-BENCH-001-T1
"""
import argparse
import os
from pathlib import Path

ENTITY_TYPES = ["function", "class", "module", "api", "bug", "feature", "person", "task"]
DOMAINS = ["coding", "daily", "legal"]

ENTITY_TMPL = """\
---
entity_type: {etype}
entity_name: {name}
scope_id: bench
source_channel: benchmark
generated: "2026-05-04"
---

# {name}

<!-- GENERATED BENCHMARK FIXTURE — safe to delete via clean_fixtures.sh -->

Synthetic benchmark entity of type `{etype}`.

Properties: index={i}, type={etype}

[[entity:{etype}:{name}]]
"""

SOURCE_TMPL = """\
---
source: text://bench/{slug}
domain: {domain}
scope_id: bench
source_channel: benchmark
entities_extracted: 3
relations_extracted: 1
generated: "2026-05-04"
---

# {slug}

<!-- GENERATED BENCHMARK FIXTURE — safe to delete via clean_fixtures.sh -->

Synthetic benchmark source document in domain `{domain}`.

Index: {i}
"""


def generate(wiki_root: Path, entity_count: int, source_count: int) -> None:
    entity_written = 0
    for i in range(entity_count):
        etype = ENTITY_TYPES[i % len(ENTITY_TYPES)]
        name = f"entity_{i:04d}"
        path = wiki_root / "entities" / etype / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ENTITY_TMPL.format(etype=etype, name=name, i=i))
        entity_written += 1

    source_written = 0
    for i in range(source_count):
        domain = DOMAINS[i % len(DOMAINS)]
        slug = f"source_{i:04d}"
        path = wiki_root / "sources" / domain / f"{slug}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SOURCE_TMPL.format(slug=slug, domain=domain, i=i))
        source_written += 1

    print(f"Generated {entity_written} entity pages in {wiki_root}/entities/")
    print(f"Generated {source_written} source pages in {wiki_root}/sources/")
    total = entity_written + source_written
    print(f"Total fixture pages: {total}")


def main() -> None:
    default_wiki = Path.home() / "mnemosyne" / "wiki"
    parser = argparse.ArgumentParser(description="Generate large-vault benchmark fixtures")
    parser.add_argument(
        "--wiki-root",
        type=Path,
        default=Path(os.environ.get("MNEMOSYNE_WIKI_ROOT", str(default_wiki))),
        help="Wiki root directory (default: ~/mnemosyne/wiki or $MNEMOSYNE_WIKI_ROOT)",
    )
    parser.add_argument("--entities", type=int, default=500, help="Number of entity pages")
    parser.add_argument("--sources", type=int, default=200, help="Number of source pages")
    args = parser.parse_args()

    generate(args.wiki_root, args.entities, args.sources)


if __name__ == "__main__":
    main()
