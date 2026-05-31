/*
 * Graph View Bundle -- runs inside Joplin panel webview
 *
 * SPEC-JOPLIN-003
 * Self-contained script that listens for graphData messages from the plugin
 * and initializes the D3.js force-directed graph visualization.
 */

(function() {
  // Wait for the graph container to be ready
  const containerId = 'kg-graph-container';

  function initGraphView() {
    const container = document.getElementById(containerId);
    if (!container) {
      setTimeout(initGraphView, 100);
      return;
    }

    // Listen for graph data from the plugin
    window.addEventListener('message', (event: MessageEvent) => {
      const data = event.data;
      if (data && data.type === 'graphData') {
        renderGraph(container, data);
      }
    });

    // Also check if data was already posted before listener was ready
    if ((window as any).__kgPendingData) {
      renderGraph(container, (window as any).__kgPendingData);
      delete (window as any).__kgPendingData;
    }
  }

  // Clear all child elements safely (no innerHTML)
  function clearChildren(el: HTMLElement): void {
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
  }

  function renderGraph(container: HTMLElement, data: any): void {
    clearChildren(container);

    const entities = data.entities || [];
    const relations = data.relations || [];

    if (entities.length === 0) {
      const emptyMsg = document.createElement('div');
      emptyMsg.style.cssText = 'display:flex;align-items:center;justify-content:center;height:100%;color:#666;font-family:sans-serif;font-size:16px;';
      emptyMsg.textContent = 'No entities in knowledge graph. Extract entities from notes or connect to mnemosyne serve.';
      container.appendChild(emptyMsg);
      return;
    }

    // Use the full D3-based GraphView if available, otherwise canvas fallback
    if (typeof (window as any).GraphView !== 'undefined') {
      const gv = new (window as any).GraphView(container);
      gv.setData({ entities, relations });
    } else {
      renderCanvasFallback(container, entities, relations);
    }
  }

  function renderCanvasFallback(
    container: HTMLElement,
    entities: Array<{ id: string; type: string; name: string }>,
    relations: Array<{ source: string; target: string; relationType: string }>,
  ): void {
    const canvas = document.createElement('canvas');
    canvas.style.cssText = 'width:100%;height:100%;background:#1a1a2e;';
    container.appendChild(canvas);

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    canvas.width = width;
    canvas.height = height;

    // Color mapping
    const colors: Record<string, string> = {
      task: '#4CAF50', person: '#8BC34A', place: '#CDDC39', event: '#FFEB3B',
      habit: '#FFC107', preference: '#FF9800', note: '#9E9E9E',
      function: '#2196F3', class: '#3F51B5', module: '#673AB7', api: '#9C27B0',
      bug: '#F44336', feature: '#E91E63', test: '#00BCD4', dependency: '#009688',
      statute: '#FF5722', clause: '#795548', case: '#607D8B', party: '#FF6F00',
      contract: '#A1887F',
    };

    // Place nodes in a circle
    const nodes = entities.map((e, i) => ({
      ...e,
      x: width / 2 + Math.cos((2 * Math.PI * i) / entities.length) * Math.min(width, height) * 0.35,
      y: height / 2 + Math.sin((2 * Math.PI * i) / entities.length) * Math.min(width, height) * 0.35,
    }));

    const nodeMap = new Map(nodes.map(n => [n.id, n]));

    // Draw links
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 1;
    for (const rel of relations) {
      const src = nodeMap.get(rel.source);
      const tgt = nodeMap.get(rel.target);
      if (src && tgt) {
        ctx.beginPath();
        ctx.moveTo(src.x, src.y);
        ctx.lineTo(tgt.x, tgt.y);
        ctx.stroke();
      }
    }

    // Draw nodes
    for (const node of nodes) {
      const color = colors[node.type] || '#78909C';

      ctx.beginPath();
      ctx.arc(node.x, node.y, 6, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = '#222';
      ctx.lineWidth = 1;
      ctx.stroke();

      ctx.fillStyle = '#bbb';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      const label = node.name.length > 14 ? node.name.slice(0, 13) + '…' : node.name;
      ctx.fillText(label, node.x, node.y - 10);
    }

    // Stats
    ctx.fillStyle = '#666';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(`${entities.length} entities, ${relations.length} relations`, 10, height - 10);
  }

  // Start when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initGraphView);
  } else {
    initGraphView();
  }
})();
