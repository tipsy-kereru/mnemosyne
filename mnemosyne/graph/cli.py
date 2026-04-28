"""
CLI for the knowledge graph query tool.

Installed as ``mnemosyne-query`` console_scripts entry point.
Also delegated to by ``python -m mnemosyne.graph.knowledge_graph``.
"""

import argparse
import json

QUERY_SYNTAX = """\
Query Syntax:
  search:TERM                      Fuzzy search across all entities
  entity:TYPE[NAME]                Lookup entity by type and name (supports regex)
  entity:TYPE[NAME]@session:SID    Scope query to a specific session
  entity:TYPE[NAME]@project:PID    Scope query to a specific project
  relation:TYPE                    List all relations of a given type
  path:FROM,TO                     Find shortest path between two entities

Entity types: function, class, module, api, bug, feature, test, dependency,
              task, person, place, event, habit, preference, note,
              statute, clause, case, party, obligation, deadline, contract

Examples:
  mnemosyne-query --stats
  mnemosyne-query --query "search:authenticate"
  mnemosyne-query --query "entity:function[parse_config]"
  mnemosyne-query --query "relation:calls"
  mnemosyne-query --query "path:get_user,authenticate"

Output: JSON to stdout.
  --stats: {"entities": N, "relations": N, "by_type": {...}, "density": F}
  --query: {"type": "..., "term": "...", "results": [{id, type, name, properties, ...}]}
"""


def main(argv=None):
    """Knowledge Graph CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mnemosyne-query",
        description="Query the knowledge graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=QUERY_SYNTAX,
    )
    parser.add_argument("--query", help="Query expression (see syntax below)")
    parser.add_argument("--stats", action="store_true", help="Show graph statistics as JSON")
    parser.add_argument(
        "--examples", action="store_true",
        help="Show query syntax and examples",
    )

    args = parser.parse_args(argv)

    if args.examples:
        print(QUERY_SYNTAX.strip())
        return

    from mnemosyne.graph.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph()

    try:
        if args.stats:
            print(json.dumps(kg.get_stats(), indent=2))
        elif args.query:
            result = kg.query(args.query)
            print(json.dumps(result, indent=2, default=str))
        else:
            parser.print_help()
    finally:
        kg.close()


if __name__ == "__main__":
    main()
