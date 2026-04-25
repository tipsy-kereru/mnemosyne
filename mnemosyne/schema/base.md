# Base Schema: Session Memory & Scope System

Defines the foundational entity and relationship types for the hierarchical session memory system.

## Scope Hierarchy

```
project (root)
  └── topic
        └── session
              └── session (infinite depth)
```

## Scope Entity Types

### project

Top-level container for a body of work. Projects are the root of the scope hierarchy.

Properties:
- `name` (string, required): Project name
- `description` (string, optional): Project description
- `status` (string, optional): active, archived, completed

### topic

A sub-area or domain within a project. Topics group related sessions.

Properties:
- `name` (string, required): Topic name
- `description` (string, optional): Topic description
- `tags` (list[string], optional): Topic tags

### session

An individual work context (chat session, coding session, meeting). Sessions can nest infinitely under other sessions.

Properties:
- `name` (string, required): Session name
- `started_at` (string, ISO-8601): Session start time
- `ended_at` (string, ISO-8601, optional): Session end time
- `summary` (string, optional): Session summary

## Base Properties

All entities and relations in the knowledge graph inherit these base properties:

- `_scope_id` (string, nullable): The scope this entity belongs to. NULL means global scope (visible everywhere).
- `_source_channel` (string): The origin channel of this entity. One of: `discord`, `teams`, `slack`, `code`, `manual`, `legacy`.

## Scope Visibility Rules

Entity visibility follows scope hierarchy:

1. **Global scope** (`scope_id = NULL`): Visible from all scopes
2. **Project scope**: Visible from the project and all descendant topics/sessions
3. **Topic scope**: Visible from the topic and all descendant sessions
4. **Session scope**: Visible from the session and any nested sessions

Resolution order: entity's own scope -> parent scope -> ... -> root -> global (NULL).

## Hierarchy Relationship Types

### part_of

Indicates that a scope is a part of its parent scope.

- Source: topic, session
- Target: project, topic, session
- Properties: none

### belongs_to

Indicates that an entity belongs to a scope.

- Source: any entity
- Target: project, topic, session
- Properties: none
