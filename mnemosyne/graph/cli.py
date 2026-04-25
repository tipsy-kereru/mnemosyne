"""
CLI for the knowledge graph query tool.

Installed as ``mnemosyne-query`` console_scripts entry point.
Also delegated to by ``python -m mnemosyne.graph.knowledge_graph``.
"""

import argparse
import json
import sys


def main(argv=None):
    """Knowledge Graph CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mnemosyne-query",
        description="Query the knowledge graph",
    )
    parser.add_argument("--query", help="Query expression")
    parser.add_argument("--stats", action="store_true", help="Show graph statistics")

    args = parser.parse_args(argv)

    # Lazy import to avoid circular dependency and heavy init at import time
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
