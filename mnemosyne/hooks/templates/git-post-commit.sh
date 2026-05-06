#!/bin/sh
# mnemosyne post-commit hook — auto-sync knowledge graph after commits
# Installed by: mnemosyne hook install git
# Managed by mnemosyne — do not edit manually

# Only run if mnemosyne is available
command -v mnemosyne >/dev/null 2>&1 || exit 0

# Run incremental update — mnemosyne uses hash-based change detection
# so this is fast when nothing has changed
mnemosyne update --quiet 2>/dev/null
