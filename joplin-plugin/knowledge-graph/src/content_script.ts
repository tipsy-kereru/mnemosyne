/*
 * Content Script for Wiki Link Rendering
 * Handles [[wiki-links]] in Joplin's rich text editor
 */

(function() {
  // Wiki link pattern
  const WIKI_LINK_PATTERN = /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g;

  // Entity link pattern: entity:type:name
  const ENTITY_PATTERN = /^entity:(\w+):(.+)$/;
  
  // Graph query pattern: graph:query
  const GRAPH_PATTERN = /^graph:(.+)$/;

  // Process wiki links in text content
  function processWikiLinks(element: HTMLElement) {
    // Find text nodes
    const walker = document.createTreeWalker(
      element,
      NodeFilter.SHOW_TEXT
    );

    const textNodes: Text[] = [];
    let node: Text | null;
    while ((node = walker.nextNode() as Text)) {
      textNodes.push(node);
    }

    // Process each text node
    for (const textNode of textNodes) {
      const text = textNode.textContent || '';
      
      if (WIKI_LINK_PATTERN.test(text)) {
        WIKI_LINK_PATTERN.lastIndex = 0;
        
        const fragment = document.createDocumentFragment();
        let lastIndex = 0;
        let match;
        
        while ((match = WIKI_LINK_PATTERN.exec(text)) !== null) {
          // Add text before match
          if (match.index > lastIndex) {
            fragment.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
          }
          
          // Create wiki link element
          const link = createWikiLinkElement(match[1], match[2]);
          fragment.appendChild(link);
          
          lastIndex = match.index + match[0].length;
        }
        
        // Add remaining text
        if (lastIndex < text.length) {
          fragment.appendChild(document.createTextNode(text.slice(lastIndex)));
        }
        
        // Replace text node with fragment
        textNode.parentNode?.replaceChild(fragment, textNode);
      }
    }
  }

  // Create wiki link element
  function createWikiLinkElement(path: string, alias?: string): HTMLElement {
    const span = document.createElement('span');
    span.className = 'wiki-link';
    span.setAttribute('data-wiki-link', path);
    
    // Determine link type
    const entityMatch = path.match(ENTITY_PATTERN);
    const graphMatch = path.match(GRAPH_PATTERN);
    
    if (entityMatch) {
      const [, type, name] = entityMatch;
      span.className += ' entity-link';
      span.setAttribute('data-entity-type', type);
      span.setAttribute('data-entity-name', name);
      span.textContent = alias || `${type}:${name}`;
      span.title = `Entity: ${type} - ${name}`;
    } else if (graphMatch) {
      span.className += ' graph-link';
      span.setAttribute('data-graph-query', graphMatch[1]);
      span.textContent = alias || `Graph: ${graphMatch[1]}`;
      span.title = `Graph Query: ${graphMatch[1]}`;
    } else {
      // Note link
      span.className += ' note-link';
      span.setAttribute('data-note-path', path);
      span.textContent = alias || path;
      span.title = `Note: ${path}`;
      
      // Make it clickable
      span.addEventListener('click', () => {
        if ((window as any).joplin) {
          (window as any).joplin.commands.execute('openNote', path);
        }
      });
    }
    
    // Add click handler for entity/graph links
    if (entityMatch || graphMatch) {
      span.style.cursor = 'pointer';
      span.addEventListener('click', () => {
        // Trigger knowledge graph search
        if ((window as any).joplin && (window as any).joplin.plugins) {
          (window as any).joplin.plugins.current.postMessage({
            name: 'wikiLinkClicked',
            args: { path, alias }
          });
        }
      });
    }
    
    return span;
  }

  // Add CSS for wiki links
  function addStyles() {
    const style = document.createElement('style');
    style.textContent = `
      .wiki-link {
        color: #4CAF50;
        text-decoration: none;
        border-bottom: 1px dashed #4CAF50;
        cursor: pointer;
        transition: all 0.2s ease;
      }
      
      .wiki-link:hover {
        color: #81C784;
        border-bottom-color: #81C784;
      }
      
      .wiki-link.entity-link {
        color: #2196F3;
        border-bottom-color: #2196F3;
      }
      
      .wiki-link.entity-link:hover {
        color: #64B5F6;
        border-bottom-color: #64B5F6;
      }
      
      .wiki-link.graph-link {
        color: #FF9800;
        border-bottom-color: #FF9800;
      }
      
      .wiki-link.graph-link:hover {
        color: #FFB74D;
        border-bottom-color: #FFB74D;
      }
      
      .wiki-link.note-link {
        color: #9E9E9E;
        border-bottom-color: #9E9E9E;
      }
      
      .wiki-link.note-link:hover {
        color: #BDBDBD;
        border-bottom-style: solid;
      }
      
      /* Search result highlighting */
      .kg-search-results {
        padding: 10px;
      }
      
      .kg-result-item {
        padding: 8px;
        margin: 4px 0;
        background: #f5f5f5;
        border-radius: 4px;
        cursor: pointer;
      }
      
      .kg-result-item:hover {
        background: #e0e0e0;
      }
      
      .kg-result-type {
        display: inline-block;
        padding: 2px 6px;
        background: #2196F3;
        color: white;
        border-radius: 3px;
        font-size: 11px;
        margin-right: 8px;
      }
      
      .kg-result-name {
        font-weight: 600;
      }
      
      .kg-result-props {
        display: block;
        font-size: 12px;
        color: #666;
        margin-top: 4px;
      }
    `;
    document.head.appendChild(style);
  }

  // Initialize
  function init() {
    // Add styles
    addStyles();
    
    // Process existing content
    if (document.body) {
      processWikiLinks(document.body);
    }
    
    // Watch for new content
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of Array.from(mutation.addedNodes)) {
          if (node instanceof HTMLElement) {
            processWikiLinks(node);
          }
        }
      }
    });
    
    observer.observe(document.body, { childList: true, subtree: true });
  }

  // ============================================================
  // SPEC-JOPLIN-003: Wiki-link Autocomplete
  // ============================================================

  // Autocomplete state
  let autocompleteDropdown: HTMLDivElement | null = null;
  let autocompleteItems: string[] = [];
  let autocompleteSelectedIndex: number = 0;
  let autocompleteTriggerRange: Range | null = null;
  let entityCache: Array<{ id: string; type: string; name: string }> = [];

  // Build the autocomplete dropdown element
  function createAutocompleteDropdown(): HTMLDivElement {
    const dropdown = document.createElement('div');
    dropdown.id = 'kg-autocomplete';
    dropdown.style.cssText = `
      position: fixed;
      z-index: 10000;
      background: #1a1a2e;
      border: 1px solid #0f3460;
      border-radius: 6px;
      max-height: 200px;
      overflow-y: auto;
      font-family: sans-serif;
      font-size: 13px;
      color: #ccc;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      display: none;
      min-width: 250px;
    `;
    document.body.appendChild(dropdown);
    return dropdown;
  }

  // Get the dropdown element (create if needed)
  function getAutocompleteDropdown(): HTMLDivElement {
    if (!autocompleteDropdown) {
      autocompleteDropdown = createAutocompleteDropdown();
    }
    return autocompleteDropdown;
  }

  // Fetch entity list from the plugin via Joplin messaging
  async function fetchEntityList(): Promise<Array<{ id: string; type: string; name: string }>> {
    if (entityCache.length > 0) return entityCache;

    try {
      if ((window as any).joplin && (window as any).joplin.plugins) {
        const response = await (window as any).joplin.plugins.current.sendMessage({
          name: 'getEntityList',
        });
        if (response && Array.isArray(response)) {
          entityCache = response;
          return entityCache;
        }
      }
    } catch {
      // Plugin communication failed
    }
    return [];
  }

  // Clear the dropdown content safely (no innerHTML)
  function clearDropdownContent(dropdown: HTMLDivElement): void {
    while (dropdown.firstChild) {
      dropdown.removeChild(dropdown.firstChild);
    }
  }

  // Show autocomplete dropdown at cursor position
  function showAutocomplete(items: string[], rect: DOMRect | null): void {
    const dropdown = getAutocompleteDropdown();
    clearDropdownContent(dropdown);

    if (items.length === 0 || !rect) {
      dropdown.style.display = 'none';
      return;
    }

    autocompleteItems = items;
    autocompleteSelectedIndex = 0;

    items.forEach((item, index) => {
      const div = document.createElement('div');
      div.style.cssText = `
        padding: 6px 10px;
        cursor: pointer;
        border-bottom: 1px solid #0f3460;
      `;
      if (index === 0) {
        div.style.background = '#0f3460';
      }
      div.textContent = item;
      div.addEventListener('mousedown', (e) => {
        e.preventDefault();
        selectAutocompleteItem(index);
      });
      div.addEventListener('mouseenter', () => {
        highlightAutocompleteItem(index);
      });
      dropdown.appendChild(div);
    });

    // Position dropdown near the cursor
    dropdown.style.left = `${rect.left}px`;
    dropdown.style.top = `${rect.bottom + 4}px`;
    dropdown.style.display = 'block';
  }

  // Highlight a specific item in the dropdown
  function highlightAutocompleteItem(index: number): void {
    const dropdown = getAutocompleteDropdown();
    const children = dropdown.children;
    for (let i = 0; i < children.length; i++) {
      (children[i] as HTMLElement).style.background = i === index ? '#0f3460' : 'transparent';
    }
    autocompleteSelectedIndex = index;
  }

  // Select an autocomplete item and insert into the editor
  function selectAutocompleteItem(index: number): void {
    if (index < 0 || index >= autocompleteItems.length) return;

    const selectedText = autocompleteItems[index];
    const dropdown = getAutocompleteDropdown();
    dropdown.style.display = 'none';

    // Insert the completed link into the active editor
    if (autocompleteTriggerRange) {
      const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT
      );
      let node: Text | null;
      while ((node = walker.nextNode() as Text)) {
        const text = node.textContent || '';
        const openBracket = text.lastIndexOf('[[');
        if (openBracket !== -1) {
          const before = text.substring(0, openBracket);
          const closePos = text.indexOf(']]', openBracket);
          const after = closePos !== -1 ? text.substring(closePos + 2) : text.substring(text.length);
          node.textContent = before + `[[${selectedText}]]` + after;
          break;
        }
      }
    }

    autocompleteTriggerRange = null;
    autocompleteItems = [];
  }

  // Hide autocomplete dropdown
  function hideAutocomplete(): void {
    const dropdown = getAutocompleteDropdown();
    dropdown.style.display = 'none';
    autocompleteItems = [];
    autocompleteTriggerRange = null;
  }

  // Handle keyboard navigation in autocomplete
  function handleAutocompleteKeydown(event: KeyboardEvent): boolean {
    const dropdown = getAutocompleteDropdown();
    if (dropdown.style.display !== 'block' || autocompleteItems.length === 0) {
      return false;
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      const newIndex = Math.min(autocompleteSelectedIndex + 1, autocompleteItems.length - 1);
      highlightAutocompleteItem(newIndex);
      return true;
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      const newIndex = Math.max(autocompleteSelectedIndex - 1, 0);
      highlightAutocompleteItem(newIndex);
      return true;
    } else if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault();
      selectAutocompleteItem(autocompleteSelectedIndex);
      return true;
    } else if (event.key === 'Escape') {
      event.preventDefault();
      hideAutocomplete();
      return true;
    }

    return false;
  }

  // Listen for [[ trigger in contentEditable areas
  function setupAutocompleteListeners(): void {
    document.addEventListener('keydown', (event: KeyboardEvent) => {
      handleAutocompleteKeydown(event);
    }, true);

    document.addEventListener('input', async (event: Event) => {
      const target = event.target as HTMLElement;
      if (!target || !target.isContentEditable) return;

      const selection = window.getSelection();
      if (!selection || selection.rangeCount === 0) return;

      const range = selection.getRangeAt(0);
      const textNode = range.startContainer;
      if (textNode.nodeType !== Node.TEXT_NODE) return;

      const text = textNode.textContent || '';
      const cursorPos = range.startOffset;

      // Look for [[ trigger before cursor
      const beforeCursor = text.substring(0, cursorPos);
      const openBracket = beforeCursor.lastIndexOf('[[');

      if (openBracket === -1) {
        hideAutocomplete();
        return;
      }

      // Check if there's a closing ]] after the [[
      const afterOpen = beforeCursor.substring(openBracket + 2);
      if (afterOpen.includes(']]')) {
        hideAutocomplete();
        return;
      }

      const query = afterOpen.trim();

      // If query is short, wait for more characters
      if (query.length > 0 && query.length < 2) {
        hideAutocomplete();
        return;
      }

      autocompleteTriggerRange = range.cloneRange();

      // Fetch entities and filter
      const entities = await fetchEntityList();
      const queryLower = query.toLowerCase();

      let matches: string[];
      if (query.length === 0) {
        matches = entities.slice(0, 15).map(e => `entity:${e.type}:${e.name}`);
      } else {
        const filtered = entities.filter(e =>
          e.name.toLowerCase().includes(queryLower) ||
          e.type.toLowerCase().includes(queryLower) ||
          e.id.toLowerCase().includes(queryLower)
        );
        matches = filtered.slice(0, 15).map(e => `entity:${e.type}:${e.name}`);
      }

      // Get cursor position for dropdown placement
      const rect = range.getBoundingClientRect();
      showAutocomplete(matches, rect);
    });

    // Hide autocomplete on click outside
    document.addEventListener('click', (event: MouseEvent) => {
      const dropdown = getAutocompleteDropdown();
      if (dropdown && event.target !== dropdown && !dropdown.contains(event.target as Node)) {
        hideAutocomplete();
      }
    });
  }

  // Initialize autocomplete
  function initAutocomplete(): void {
    setupAutocompleteListeners();
  }

  // Start when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      init();
      initAutocomplete();
    });
  } else {
    init();
    initAutocomplete();
  }
})();