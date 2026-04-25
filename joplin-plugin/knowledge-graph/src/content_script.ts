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
      NodeFilter.SHOW_TEXT,
      null,
      false
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
        if (window.joplin) {
          window.joplin.commands.execute('openNote', path);
        }
      });
    }
    
    // Add click handler for entity/graph links
    if (entityMatch || graphMatch) {
      span.style.cursor = 'pointer';
      span.addEventListener('click', () => {
        // Trigger knowledge graph search
        if (window.joplin && window.joplin.plugins) {
          window.joplin.plugins.current.postMessage({
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
        for (const node of mutation.addedNodes) {
          if (node instanceof HTMLElement) {
            processWikiLinks(node);
          }
        }
      }
    });
    
    observer.observe(document.body, { childList: true, subtree: true });
  }

  // Start when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();