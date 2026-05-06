# Joplin Knowledge Graph Plugin

Wiki-links and knowledge graph integration for [Joplin](https://joplinapp.org/), powered by [Mnemosyne](https://github.com/tipsy-kereru/mnemosyne).

## Features

- **Wiki-links** — `[[note-name]]`, `[[entity:type:name]]`, `[[graph:query]]` syntax rendered inline
- **Knowledge Graph search** — search entities across all domains (daily, coding, legal)
- **Graph visualization** — interactive canvas view of entities and relations
- **Entity extraction** — extract entities from notes into the knowledge graph
- **Session scoping** — `@session:`, `@project:`, `@channel:` modifiers on wiki-links
- **Domain detection** — auto-detect daily / coding / legal from note content

## Prerequisites

- Joplin desktop **2.14** or later
- Node.js 18+ and npm

## Build and Install

```bash
cd joplin-plugin/knowledge-graph

# Install dependencies
npm install

# Build for production
npm run build

# Package as .jpl
npm run pack
```

This produces `knowledge-graph.jpl` one directory up.

### Install in Joplin

1. Open Joplin
2. **Tools > Options > Plugins**
3. Click **Install from file**
4. Select `knowledge-graph.jpl`
5. Restart Joplin

## Commands

| Command | Shortcut | Description |
|---------|----------|-------------|
| Search Knowledge Graph | `Cmd/Ctrl+Shift+K` | Search entities by name, type, or relation |
| Insert Wiki Link | `Cmd/Ctrl+L` | Insert `[[...]]` link for selected text or pick from entity list |
| Show Knowledge Graph | `Cmd/Ctrl+Shift+G` | Open graph visualization panel |
| Extract Entities | — | Extract entities from current note into the knowledge graph |

## Wiki-link Syntax

| Syntax | Meaning | Example |
|--------|---------|---------|
| `[[page]]` | Link to a Joplin note | `[[meeting-notes]]` |
| `[[page\|alias]]` | Link with display text | `[[meeting-notes\|Meeting]]` |
| `[[entity:type:name]]` | Knowledge graph entity | `[[entity:function:authenticate]]` |
| `[[entity:type:name@session:s1]]` | Entity scoped to session | `[[entity:function:parse@session:s1]]` |
| `[[graph:query]]` | Embedded graph query | `[[graph:search:security]]` |

## Link Colors

| Link Type | Color |
|-----------|-------|
| Note link | Gray |
| Entity link | Blue |
| Graph query | Orange |

## Domain Detection

The plugin auto-detects the domain based on keywords in note content:

- **Daily** — task, meeting, appointment, reminder, habit, person, contact
- **Coding** — function, class, module, api, bug, feature, test, dependency
- **Legal** — statute, clause, case, party, obligation, contract, plaintiff, defendant

## Session Scoping

Add YAML frontmatter to notes for scope-aware extraction:

```yaml
---
session_id: impl-session
project: my-project
channel: joplin
---
```

Scope modifiers in wiki-links are preserved as `data-scope-*` attributes in the rendered HTML.

## Data Storage

The knowledge graph is stored in Joplin's plugin settings as JSON. Use the Mnemosyne CLI to sync with the SQLite + NetworkX backend:

```bash
# Export from Mnemosyne graph DB
mnemosyne query --stats

# Ingest a note into the graph
mnemosyne add path/to/note.md --domain daily
```

## Development

```bash
# Development build with sourcemaps
npm run dev

# Run tests
npm test

# Lint
npm run lint
```

## Architecture

```
src/
├── index.ts            # Plugin registration, commands, entity extraction
└── content_script.ts   # Wiki-link rendering, DOM mutation observer
```

- `index.ts` — registers commands, handles note-save events, manages in-memory graph, detects domains, extracts entities
- `content_script.ts` — runs in the note editor context, observes DOM mutations, renders `[[wiki-links]]` as styled `<span>` elements

## License

MIT
