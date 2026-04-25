/*
 * Joplin Knowledge Graph Plugin
 *
 * Provides:
 * - [[wiki-link]] syntax support
 * - AI agent knowledge memory integration
 * - Temporal knowledge graph visualization
 * - Cross-domain entity linking
 * - Session/scope support (SPEC-SESSION-002)
 */

import { JoplinViewType } from 'joplin-api';
import { ContentScriptType } from 'joplin/plugins';

interface WikiLink {
  raw: string;
  path: string;
  alias?: string;
  type: 'note' | 'entity' | 'graph';
}

// @MX:ANCHOR: [AUTO] Session metadata extracted from note frontmatter
// @MX:REASON: Used by extractEntitiesFromNote, extractBasedOnDomain, and tests — core scope contract
interface SessionMetadata {
  session_id?: string;
  project?: string;
  topic?: string;
  channel?: string;
}

// @MX:ANCHOR: [AUTO] Scope info for knowledge graph scoping
// @MX:REASON: Persisted via save/load cycle and referenced by scope hierarchy queries
interface ScopeInfo {
  id: string;
  name: string;
  scope_type: 'project' | 'topic' | 'session';
  parent_id?: string;
}

interface KnowledgeGraphEntity {
  id: string;
  type: string;
  name: string;
  properties: Record<string, any>;
  version: number;
  scope_id?: string;
  source_channel?: string;
}

interface KnowledgeGraphRelation {
  id: string;
  source: string;
  target: string;
  relationType: string;
  properties: Record<string, any>;
  scope_id?: string;
  source_channel?: string;
}

// Main plugin class
class KnowledgeGraphPlugin {
  private plugin: any;
  private graphDB: Map<string, KnowledgeGraphEntity> = new Map();
  private relationIndex: Map<string, KnowledgeGraphRelation[]> = new Map();
  private scopeIndex: Map<string, ScopeInfo> = new Map();

  constructor(plugin: any) {
    this.plugin = plugin;
  }

  // Initialize plugin
  async initialize() {
    // Register commands
    await this.registerCommands();

    // Register event handlers
    await this.registerEventHandlers();

    // Load existing knowledge graph
    await this.loadKnowledgeGraph();

    console.log('Knowledge Graph Plugin initialized');
  }

  // Register custom commands
  private async registerCommands() {
    // Command: Search knowledge graph
    await this.plugin.registry.register({
      name: 'knowledge-graph.search',
      label: 'Search Knowledge Graph',
      iconName: 'fa fa-search',
      accelerator: 'CmdOrCtrl+Shift+K',
      execute: async () => {
        await this.showSearchDialog();
      },
    });

    // Command: Insert wiki link
    await this.plugin.registry.register({
      name: 'knowledge-graph.insertLink',
      label: 'Insert Wiki Link',
      iconName: 'fa fa-link',
      accelerator: 'CmdOrCtrl+L',
      execute: async () => {
        await this.insertWikiLink();
      },
    });

    // Command: Show graph view
    await this.plugin.registry.register({
      name: 'knowledge-graph.showGraph',
      label: 'Show Knowledge Graph',
      iconName: 'fa fa-project-diagram',
      accelerator: 'CmdOrCtrl+Shift+G',
      execute: async () => {
        await this.showGraphView();
      },
    });

    // Command: Extract entities from note
    await this.plugin.registry.register({
      name: 'knowledge-graph.extractEntities',
      label: 'Extract Entities to Knowledge Graph',
      iconName: 'fa fa-magic',
      execute: async () => {
        await this.extractAndLink();
      },
    });
  }

  // Register event handlers
  private async registerEventHandlers() {
    // Handle note save - extract entities
    this.plugin.onNoteSave(async (note: any) => {
      await this.extractEntitiesFromNote(note);
    });

    // Handle markdown rendering - process wiki links
    this.plugin.onCalculateSyntaxHighlight((text: string) => {
      return this.processWikiLinks(text);
    });
  }

  // Parse YAML frontmatter from content
  // @MX:NOTE: [AUTO] Returns null for missing/empty/malformed frontmatter (EC-001)
  parseFrontmatter(content: string): SessionMetadata | null {
    // Frontmatter must start at the very beginning of content
    if (!content.startsWith('---')) {
      return null;
    }

    // The content starts with ---\n, so we search after the first delimiter
    const afterFirstDelimiter = content.indexOf('\n', 0);
    if (afterFirstDelimiter === -1) {
      return null;
    }

    const rest = content.substring(afterFirstDelimiter + 1);
    const closingIndex = rest.indexOf('\n---');

    if (closingIndex === -1) {
      // No closing delimiter found — treat as no frontmatter (EC-001)
      return null;
    }

    const frontmatterText = rest.substring(0, closingIndex).trim();

    // Empty frontmatter returns null (EC-001)
    if (frontmatterText.length === 0) {
      return null;
    }

    const metadata: SessionMetadata = {};
    let hasValidField = false;

    const lines = frontmatterText.split('\n');
    for (const line of lines) {
      const colonIndex = line.indexOf(':');
      if (colonIndex === -1) {
        // No colon — invalid line, skip (EC-001)
        continue;
      }

      const key = line.substring(0, colonIndex).trim();
      const value = line.substring(colonIndex + 1).trim();

      // Skip empty keys (e.g., ": value_without_key")
      if (key.length === 0) {
        continue;
      }

      // Only parse known fields
      if (key === 'session_id' || key === 'project' || key === 'topic' || key === 'channel') {
        metadata[key as keyof SessionMetadata] = value;
        hasValidField = true;
      }
    }

    return hasValidField ? metadata : null;
  }

  // Process wiki links in markdown
  // @MX:NOTE: [AUTO] Supports @session:, @project:, @channel: modifiers (SPEC-SESSION-002 T5)
  processWikiLinks(text: string): string {
    // Pattern: [[link]] or [[link|alias]] or [[type:entity]]
    const wikiLinkPattern = /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g;

    return text.replace(wikiLinkPattern, (match, path, alias) => {
      const linkType = this.determineLinkType(path);

      // Parse scope modifiers from the path
      const { cleanPath, scopeAttrs } = this.parseScopeModifiers(path);

      // Build scope attributes string
      const scopeAttrString = Object.entries(scopeAttrs)
        .map(([key, value]) => ` data-scope-${key}="${value}"`)
        .join('');

      // Create styled link based on type
      if (linkType === 'entity') {
        return `<span class="kg-entity-link" data-entity="${cleanPath}"${scopeAttrString}>${alias || cleanPath}</span>`;
      } else if (linkType === 'graph') {
        return `<span class="kg-graph-link" data-graph-query="${cleanPath}"${scopeAttrString}>${alias || cleanPath}</span>`;
      }

      return `<span class="kg-note-link" data-note-path="${cleanPath}"${scopeAttrString}>${alias || cleanPath}</span>`;
    });
  }

  // Parse @key:value scope modifiers from a wiki link path
  // @MX:NOTE: [AUTO] Only recognizes @session:, @project:, @channel: as modifiers (EC-002)
  private parseScopeModifiers(path: string): { cleanPath: string; scopeAttrs: Record<string, string> } {
    const knownModifiers = ['session', 'project', 'channel'];
    const scopeAttrs: Record<string, string> = {};

    // Split on @ to separate entity path from modifiers
    const parts = path.split('@');

    if (parts.length === 1) {
      // No @ at all
      return { cleanPath: path, scopeAttrs };
    }

    let cleanPath = parts[0];
    const remainingParts = parts.slice(1);

    for (const part of remainingParts) {
      // Check if this part looks like a modifier (contains colon)
      const colonIndex = part.indexOf(':');
      if (colonIndex !== -1) {
        // This looks like a @key:value modifier pattern
        // Check if it's a known modifier
        for (const modifier of knownModifiers) {
          const prefix = modifier + ':';
          if (part.startsWith(prefix)) {
            const value = part.substring(prefix.length);
            if (value.length > 0) {
              scopeAttrs[modifier] = value;
            }
            break;
          }
        }
        // Whether known or unknown, @key:value patterns are consumed (removed from path)
      } else {
        // No colon — this @ is part of the entity name, not a modifier
        cleanPath += '@' + part;
      }
    }

    return { cleanPath, scopeAttrs };
  }

  // Determine link type
  private determineLinkType(path: string): 'note' | 'entity' | 'graph' {
    if (path.startsWith('entity:') || path.startsWith('graph:')) {
      return path.startsWith('entity:') ? 'entity' : 'graph';
    }
    return 'note';
  }

  // Show search dialog
  private async showSearchDialog() {
    const searchDialog = await this.plugin.dialogs.create('search');

    searchDialog.setProps({
      title: 'Search Knowledge Graph',
      formItems: [
        {
          name: 'query',
          label: 'Search',
          type: 'text',
          placeholder: 'Enter entity name, type, or relation...',
        },
        {
          name: 'type',
          label: 'Filter by type',
          type: 'select',
          options: [
            { value: '', label: 'All types' },
            { value: 'person', label: 'Person' },
            { value: 'task', label: 'Task' },
            { value: 'event', label: 'Event' },
            { value: 'function', label: 'Function' },
            { value: 'class', label: 'Class' },
            { value: 'statute', label: 'Statute' },
            { value: 'case', label: 'Case' },
          ],
        },
      ],
      onSubmit: async (formValues: any) => {
        const results = await this.searchKnowledgeGraph(formValues.query, formValues.type);
        await this.displaySearchResults(results);
      },
    });

    await searchDialog.open();
  }

  // Search knowledge graph
  private async searchKnowledgeGraph(query: string, typeFilter?: string): Promise<KnowledgeGraphEntity[]> {
    const results: KnowledgeGraphEntity[] = [];
    const queryLower = query.toLowerCase();

    for (const entity of this.graphDB.values()) {
      // Type filter
      if (typeFilter && entity.type !== typeFilter) continue;

      // Name match
      if (entity.name.toLowerCase().includes(queryLower)) {
        results.push(entity);
        continue;
      }

      // Property match
      const propMatch = Object.values(entity.properties).some(
        v => typeof v === 'string' && v.toLowerCase().includes(queryLower)
      );
      if (propMatch) results.push(entity);
    }

    return results.slice(0, 50); // Limit results
  }

  // Display search results
  private async displaySearchResults(results: KnowledgeGraphEntity[]) {
    const resultHtml = results.length === 0
      ? '<p>No results found.</p>'
      : `<div class="kg-search-results">
          ${results.map(e => `
            <div class="kg-result-item" data-entity-id="${e.id}">
              <span class="kg-result-type">${e.type}</span>
              <span class="kg-result-name">${e.name}</span>
              <span class="kg-result-props">${JSON.stringify(e.properties).slice(0, 50)}...</span>
            </div>
          `).join('')}
        </div>`;

    await this.plugin.dialogs.showMessage(resultHtml);
  }

  // Insert wiki link
  private async insertWikiLink() {
    const editor = await this.plugin.editor;
    const selectedText = editor.getSelectedText();

    if (selectedText) {
      // Convert selected text to wiki link
      editor.insertText(`[[${selectedText}]]`);
    } else {
      // Show link picker dialog
      await this.showLinkPickerDialog();
    }
  }

  // Show link picker dialog
  private async showLinkPickerDialog() {
    const linkDialog = await this.plugin.dialogs.create('select');

    const entities = Array.from(this.graphDB.values()).slice(0, 100);

    linkDialog.setProps({
      title: 'Insert Link',
      items: entities.map(e => ({
        value: e.id,
        label: `${e.type}: ${e.name}`,
      })),
      onSelect: async (selectedValue: string) => {
        const entity = this.graphDB.get(selectedValue);
        if (entity) {
          const editor = await this.plugin.editor;
          editor.insertText(`[[entity:${entity.type}:${entity.name}]]`);
        }
      },
    });

    await linkDialog.open();
  }

  // Show graph view (webview)
  private async showGraphView() {
    const panel = await this.plugin.views.createPanel('knowledgeGraph');

    panel.setHtml(`
      <!DOCTYPE html>
      <html>
      <head>
        <style>
          body { margin: 0; padding: 20px; font-family: sans-serif; background: #1e1e1e; color: #ddd; }
          #graph { width: 100%; height: 500px; border: 1px solid #444; }
          #legend { margin-top: 10px; font-size: 12px; }
          .legend-item { margin: 5px 10px; display: inline-block; }
          .legend-color { width: 12px; height: 12px; display: inline-block; margin-right: 5px; vertical-align: middle; }
        </style>
      </head>
      <body>
        <h3>Knowledge Graph</h3>
        <canvas id="graph"></canvas>
        <div id="legend">
          <span class="legend-item"><span class="legend-color" style="background:#4CAF50"></span>Daily</span>
          <span class="legend-item"><span class="legend-color" style="background:#2196F3"></span>Coding</span>
          <span class="legend-item"><span class="legend-color" style="background:#FF9800"></span>Legal</span>
        </div>
        <script>
          // Minimal graph visualization
          const canvas = document.getElementById('graph');
          const ctx = canvas.getContext('2d');
          canvas.width = canvas.offsetWidth;
          canvas.height = canvas.offsetHeight;

          // Send message to Joplin for graph data
          if (window.joplin) {
            window.joplin.plugin.run()
          }
        </script>
      </body>
      </html>
    `);

    await panel.show();
  }

  // Extract entities from current note
  private async extractAndLink() {
    const note = await this.plugin.currentNote();
    if (!note) return;

    await this.extractEntitiesFromNote(note);
  }

  // Extract entities from note content
  // @MX:NOTE: [AUTO] Parses frontmatter before domain detection for scope-aware extraction (T4)
  private async extractEntitiesFromNote(note: any) {
    const content = note.body || '';

    // Parse frontmatter BEFORE domain detection (T4)
    const sessionMetadata = this.parseFrontmatter(content);

    // Detect domain based on content patterns
    const domain = this.detectDomain(content);

    // Extract entities based on domain, passing session metadata
    const entities = this.extractBasedOnDomain(content, domain, sessionMetadata || undefined);

    // Add to knowledge graph
    for (const entity of entities) {
      const id = `${entity.type}:${entity.name}`;
      this.graphDB.set(id, {
        id,
        type: entity.type,
        name: entity.name,
        properties: entity.properties,
        version: 1,
        scope_id: entity.scope_id,
        source_channel: entity.source_channel,
      });

      // Create wiki link in note
      if (!content.includes(`[[entity:${entity.type}:${entity.name}]]`)) {
        // Link new entities (simplified - real impl would find proper context)
      }
    }

    console.log(`Extracted ${entities.length} entities from note: ${note.id}`);
  }

  // Detect content domain
  private detectDomain(content: string): 'daily' | 'coding' | 'legal' {
    const patterns = {
      daily: /\b(task|meeting|appointment|reminder|habit|person|contact)\b/i,
      coding: /\b(function|class|module|api|bug|feature|test|dependency)\b/i,
      legal: /\b(statute|clause|case|party|obligation|contract|plaintiff|defendant)\b/i,
    };

    const scores = {
      daily: (content.match(patterns.daily) || []).length,
      coding: (content.match(patterns.coding) || []).length,
      legal: (content.match(patterns.legal) || []).length,
    };

    return Object.entries(scores).sort((a, b) => b[1] - a[1])[0][0] as 'daily' | 'coding' | 'legal';
  }

  // Extract entities based on domain
  // @MX:NOTE: [AUTO] Accepts optional SessionMetadata for scope-aware entity extraction (T4)
  extractBasedOnDomain(content: string, domain: string, metadata?: SessionMetadata): any[] {
    const entities: any[] = [];

    // Domain-specific extraction patterns
    const patterns: Record<string, Record<string, RegExp>> = {
      daily: {
        task: /\btask:?\s*([^\n]+)/gi,
        person: /\b(?:contact|person|call|email)\s*:?\s*([A-Z][a-z]+ [A-Z][a-z]+)/gi,
        event: /\b(?:meeting|appointment|event)\s*:?\s*([^\n]+)/gi,
      },
      coding: {
        function: /\b(?:def|function|fn)\s+(\w+)\s*\(/gi,
        class: /\bclass\s+(\w+)/gi,
        api: /\b(?:GET|POST|PUT|DELETE)\s+(\/[^\s]+)/gi,
        bug: /\bbug:?\s*([^\n]+)/gi,
      },
      legal: {
        statute: /\b(\d+\s+[A-Z]\.?\s*[A-Z]\.?\s*§\s*\d+)/gi,
        case: /\b(\d+\s+[A-Z]\.?\s*\d+[a-z]?\.?\s*\d+)/gi,
        party: /\b(?:plaintiff|defendant|petitioner|respondent)\s*:?\s*([A-Z][a-z]+ [A-Z][a-z]+)/gi,
      },
    };

    const domainPatterns = patterns[domain] || patterns.daily;

    // Determine scope_id from metadata (priority: session_id > project > topic)
    let scopeId: string | undefined;
    if (metadata) {
      scopeId = metadata.session_id || metadata.project || metadata.topic;
    }

    for (const [type, pattern] of Object.entries(domainPatterns)) {
      let match;
      while ((match = pattern.exec(content)) !== null) {
        const entity: any = {
          type,
          name: match[1].trim(),
          properties: { source: 'note_extraction', matched: match[0] },
        };

        // Set scope fields when metadata exists
        if (metadata) {
          entity.scope_id = scopeId;
          entity.source_channel = metadata.channel || 'joplin';
        }

        entities.push(entity);
      }
    }

    return entities;
  }

  // Load knowledge graph from storage
  // @MX:NOTE: [AUTO] Deserializes scopes array with backward compat for legacy data (T6)
  private async loadKnowledgeGraph() {
    try {
      // Load from plugin settings
      const stored = await this.plugin.settings.get('knowledgeGraph');
      if (stored) {
        const data = JSON.parse(stored);
        for (const entity of data.entities || []) {
          this.graphDB.set(entity.id, entity);
        }
        for (const rel of data.relations || []) {
          const key = `${rel.source}:${rel.relationType}:${rel.target}`;
          this.relationIndex.set(key, [...(this.relationIndex.get(key) || []), rel]);
        }
        // Load scopes (T6) — backward compat: missing scopes => empty map
        if (data.scopes && Array.isArray(data.scopes)) {
          for (const scope of data.scopes) {
            this.scopeIndex.set(scope.id, scope);
          }
        }
      }
    } catch (e) {
      console.error('Failed to load knowledge graph:', e);
    }
  }

  // Save knowledge graph
  // @MX:NOTE: [AUTO] Includes scopes array in persisted JSON (T6)
  async saveKnowledgeGraph() {
    const data = {
      entities: Array.from(this.graphDB.values()),
      relations: Array.from(this.relationIndex.values()).flat(),
      scopes: Array.from(this.scopeIndex.values()),
    };

    await this.plugin.settings.set('knowledgeGraph', JSON.stringify(data));
  }
}

export default KnowledgeGraphPlugin;
