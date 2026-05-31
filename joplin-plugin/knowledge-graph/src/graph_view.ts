/*
 * D3.js Force-Directed Graph Visualization
 *
 * SPEC-JOPLIN-003
 * Real-time graph visualization using d3-force and d3-selection (NOT full d3).
 * SVG-based rendering with zoom/pan, node selection, search filtering,
 * backlinks panel, and domain color coding.
 */

import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  Simulation,
  SimulationNodeDatum,
  SimulationLinkDatum,
} from 'd3-force';
import {
  select,
  Selection,
} from 'd3-selection';
import {
  zoom,
  zoomIdentity,
  ZoomBehavior,
} from 'd3-zoom';
// d3-transition augments d3-selection's Selection prototype with .transition()
// Must be imported for side effects even though not used directly
import 'd3-transition';

// ============================================================
// Types
// ============================================================

export interface GraphEntity {
  id: string;
  type: string;
  name: string;
  properties: Record<string, any>;
  version?: number;
  scope_id?: string;
  source_channel?: string;
}

export interface GraphRelation {
  id: string;
  source: string;
  target: string;
  relationType: string;
  properties?: Record<string, any>;
}

// Internal node type used by d3-force simulation
interface SimNode extends SimulationNodeDatum {
  id: string;
  type: string;
  name: string;
  properties: Record<string, any>;
  scope_id?: string;
  source_channel?: string;
}

// Internal link type used by d3-force simulation
interface SimLink extends SimulationLinkDatum<SimNode> {
  relationType: string;
}

// Data supplied to the graph view
export interface GraphData {
  entities: GraphEntity[];
  relations: GraphRelation[];
}

// Callback when an entity is selected
export type EntitySelectCallback = (entity: GraphEntity | null) => void;

// Callback to fetch backlinks for an entity
export type BacklinksFetcher = (entityId: string) => Promise<GraphRelation[]>;

// ============================================================
// Color Palette -- domain-specific entity type colors
// ============================================================

const DOMAIN_COLORS: Record<string, string> = {
  // Daily life
  task: '#4CAF50',
  person: '#8BC34A',
  place: '#CDDC39',
  event: '#FFEB3B',
  habit: '#FFC107',
  preference: '#FF9800',
  note: '#9E9E9E',

  // Coding
  function: '#2196F3',
  class: '#3F51B5',
  module: '#673AB7',
  api: '#9C27B0',
  bug: '#F44336',
  feature: '#E91E63',
  test: '#00BCD4',
  dependency: '#009688',

  // Legal
  statute: '#FF5722',
  clause: '#795548',
  case: '#607D8B',
  party: '#FF6F00',
  obligation: '#F4511E',
  deadline: '#FF8A65',
  contract: '#A1887F',
};

const DEFAULT_COLOR = '#78909C';

function getColorForType(type: string): string {
  return DOMAIN_COLORS[type] || DEFAULT_COLOR;
}

// Helper to safely set text content (avoiding innerHTML)
function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.textContent || '';
}

// ============================================================
// GraphView Class
// ============================================================

export class GraphView {
  private container: HTMLElement;
  private svg: Selection<SVGSVGElement, unknown, null, undefined>;
  private g: Selection<SVGGElement, unknown, null, undefined>;
  private simulation: Simulation<SimNode, SimLink> | null = null;
  private zoomBehavior: ZoomBehavior<SVGSVGElement, unknown> | null = null;
  private nodes: SimNode[] = [];
  private links: SimLink[] = [];
  private selectedNode: SimNode | null = null;
  private onEntitySelect: EntitySelectCallback | null = null;
  private backlinksFetcher: BacklinksFetcher | null = null;
  private width: number;
  private height: number;
  private searchTerm: string = '';
  private activeTypeFilter: string = '';
  private backlinksPanel: HTMLElement | null = null;
  private searchInput: HTMLInputElement | null = null;
  private typeSelector: HTMLSelectElement | null = null;

  // D3 selections for elements
  private linkGroup: Selection<SVGGElement, unknown, null, undefined>;
  private nodeGroup: Selection<SVGGElement, unknown, null, undefined>;
  private linkElements: Selection<SVGLineElement, SimLink, SVGGElement, unknown> | null = null;
  private nodeElements: Selection<SVGGElement, SimNode, SVGGElement, unknown> | null = null;

  constructor(container: HTMLElement) {
    this.container = container;
    this.width = container.clientWidth || 800;
    this.height = container.clientHeight || 500;

    // Create SVG element
    this.svg = select(container)
      .append<SVGSVGElement>('svg')
      .attr('width', '100%')
      .attr('height', '100%')
      .attr('viewBox', `0 0 ${this.width} ${this.height}`)
      .style('background', '#1a1a2e')
      .style('cursor', 'grab');

    // Add defs for arrow markers
    const defs = this.svg.append('defs');
    defs.append('marker')
      .attr('id', 'arrowhead')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 20)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#555');

    // Main group for zoom/pan
    this.g = this.svg.append<SVGGElement>('g');

    // Create link and node groups (links rendered below nodes)
    this.linkGroup = this.g.append<SVGGElement>('g').attr('class', 'links');
    this.nodeGroup = this.g.append<SVGGElement>('g').attr('class', 'nodes');

    // Set up zoom
    this.setupZoom();

    // Build UI controls
    this.buildControls();

    // Click on background clears selection
    this.svg.on('click', () => {
      this.clearSelection();
    });
  }

  // ----------------------------------------------------------
  // Public API
  // ----------------------------------------------------------

  /**
   * Set callback for entity selection events
   */
  setEntitySelectCallback(cb: EntitySelectCallback): void {
    this.onEntitySelect = cb;
  }

  /**
   * Set backlinks fetcher for the backlinks panel
   */
  setBacklinksFetcher(fetcher: BacklinksFetcher): void {
    this.backlinksFetcher = fetcher;
  }

  /**
   * Load graph data into the visualization
   */
  setData(data: GraphData): void {
    this.nodes = data.entities.map(e => ({
      id: e.id,
      type: e.type,
      name: e.name,
      properties: e.properties,
      scope_id: e.scope_id,
      source_channel: e.source_channel,
      x: undefined as number | undefined,
      y: undefined as number | undefined,
    }));

    // Build id -> index map for link resolution
    const nodeMap = new Map(this.nodes.map((n, i) => [n.id, i]));

    this.links = data.relations
      .filter(r => nodeMap.has(r.source) && nodeMap.has(r.target))
      .map(r => ({
        source: r.source,
        target: r.target,
        relationType: r.relationType,
      }));

    this.render();
  }

  /**
   * Update search term and re-apply visual filtering
   */
  setSearch(term: string): void {
    this.searchTerm = term.toLowerCase();
    this.applyFilter();
  }

  /**
   * Set entity type filter
   */
  setTypeFilter(type: string): void {
    this.activeTypeFilter = type;
    this.applyFilter();
  }

  /**
   * Get list of unique entity types in current data
   */
  getEntityTypes(): string[] {
    const types = new Set(this.nodes.map(n => n.type));
    return Array.from(types).sort();
  }

  /**
   * Destroy the visualization and clean up
   */
  destroy(): void {
    if (this.simulation) {
      this.simulation.stop();
      this.simulation = null;
    }
    this.svg.remove();
    if (this.backlinksPanel) {
      this.backlinksPanel.remove();
      this.backlinksPanel = null;
    }
  }

  // ----------------------------------------------------------
  // Zoom / Pan
  // ----------------------------------------------------------

  private setupZoom(): void {
    this.zoomBehavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event: any) => {
        this.g.attr('transform', event.transform);
      });

    this.svg.call(this.zoomBehavior);
  }

  /**
   * Reset zoom to identity (fit all)
   */
  resetZoom(): void {
    if (this.zoomBehavior) {
      this.svg.transition().duration(500).call(
        this.zoomBehavior.transform,
        zoomIdentity,
      );
    }
  }

  // ----------------------------------------------------------
  // Controls (search, filter, legend)
  // ----------------------------------------------------------

  private buildControls(): void {
    // Controls bar above the SVG
    const controlsBar = document.createElement('div');
    controlsBar.style.cssText = 'display:flex;gap:8px;align-items:center;padding:8px 12px;background:#16213e;border-bottom:1px solid #0f3460;font-family:sans-serif;font-size:13px;color:#ccc;';

    // Search input
    this.searchInput = document.createElement('input');
    this.searchInput.type = 'text';
    this.searchInput.placeholder = 'Search entities...';
    this.searchInput.style.cssText = 'flex:1;padding:6px 10px;border:1px solid #0f3460;border-radius:4px;background:#1a1a2e;color:#ddd;font-size:13px;outline:none;';
    this.searchInput.addEventListener('input', () => {
      this.setSearch(this.searchInput!.value);
    });
    controlsBar.appendChild(this.searchInput);

    // Type filter dropdown
    this.typeSelector = document.createElement('select');
    this.typeSelector.style.cssText = 'padding:6px 8px;border:1px solid #0f3460;border-radius:4px;background:#1a1a2e;color:#ddd;font-size:13px;outline:none;min-width:120px;';
    this.typeSelector.innerHTML = '<option value="">All types</option>';
    this.typeSelector.addEventListener('change', () => {
      this.setTypeFilter(this.typeSelector!.value);
    });
    controlsBar.appendChild(this.typeSelector);

    // Reset zoom button
    const resetBtn = document.createElement('button');
    resetBtn.textContent = 'Reset Zoom';
    resetBtn.style.cssText = 'padding:6px 12px;border:1px solid #0f3460;border-radius:4px;background:#0f3460;color:#ddd;cursor:pointer;font-size:12px;';
    resetBtn.addEventListener('click', () => this.resetZoom());
    controlsBar.appendChild(resetBtn);

    // Stats label
    const statsLabel = document.createElement('span');
    statsLabel.id = 'kg-stats';
    statsLabel.style.cssText = 'font-size:11px;color:#888;margin-left:auto;';
    controlsBar.appendChild(statsLabel);

    this.container.insertBefore(controlsBar, this.svg.node());

    // Legend below SVG
    const legend = document.createElement('div');
    legend.style.cssText = 'padding:6px 12px;background:#16213e;border-top:1px solid #0f3460;font-family:sans-serif;font-size:11px;color:#888;display:flex;flex-wrap:wrap;gap:10px;';

    const domains = [
      { label: 'Daily', types: ['task', 'person', 'event', 'place', 'habit'] },
      { label: 'Coding', types: ['function', 'class', 'module', 'api', 'bug', 'feature', 'test'] },
      { label: 'Legal', types: ['statute', 'clause', 'case', 'party', 'contract'] },
    ];

    for (const domain of domains) {
      const group = document.createElement('span');
      group.style.cssText = 'display:flex;align-items:center;gap:4px;';
      const domainLabel = document.createElement('span');
      domainLabel.textContent = `${domain.label}:`;
      domainLabel.style.cssText = 'font-weight:600;color:#aaa;';
      group.appendChild(domainLabel);

      for (const t of domain.types) {
        const item = document.createElement('span');
        item.style.cssText = 'display:inline-flex;align-items:center;gap:2px;';
        const dot = document.createElement('span');
        dot.style.cssText = `width:8px;height:8px;border-radius:50%;background:${getColorForType(t)};display:inline-block;`;
        item.appendChild(dot);
        const txt = document.createElement('span');
        txt.textContent = t;
        item.appendChild(txt);
        group.appendChild(item);
      }
      legend.appendChild(group);
    }

    this.container.appendChild(legend);
  }

  private updateTypeSelector(): void {
    if (!this.typeSelector) return;
    const types = this.getEntityTypes();
    this.typeSelector.innerHTML = '<option value="">All types</option>';
    for (const t of types) {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      this.typeSelector.appendChild(opt);
    }
    // Restore current selection if still valid
    if (this.activeTypeFilter && types.includes(this.activeTypeFilter)) {
      this.typeSelector.value = this.activeTypeFilter;
    } else {
      this.typeSelector.value = '';
      this.activeTypeFilter = '';
    }
  }

  private updateStats(): void {
    const statsEl = this.container.querySelector('#kg-stats');
    if (statsEl) {
      statsEl.textContent = `${this.nodes.length} nodes, ${this.links.length} links`;
    }
  }

  // ----------------------------------------------------------
  // Rendering
  // ----------------------------------------------------------

  private render(): void {
    // Stop existing simulation
    if (this.simulation) {
      this.simulation.stop();
    }

    // Clear existing elements
    this.linkGroup.selectAll('*').remove();
    this.nodeGroup.selectAll('*').remove();

    // Update UI
    this.updateTypeSelector();
    this.updateStats();

    // Build simulation
    this.simulation = forceSimulation<SimNode, SimLink>(this.nodes)
      .force(
        'link',
        forceLink<SimNode, SimLink>(this.links)
          .id((d: SimNode) => d.id)
          .distance(80),
      )
      .force('charge', forceManyBody().strength(-200))
      .force('center', forceCenter(this.width / 2, this.height / 2))
      .force('collide', forceCollide<SimNode>().radius(20))
      .on('tick', () => this.tick());

    // Render links
    this.linkElements = this.linkGroup
      .selectAll<SVGLineElement, SimLink>('line')
      .data(this.links)
      .join('line')
      .attr('stroke', '#444')
      .attr('stroke-width', 1.5)
      .attr('marker-end', 'url(#arrowhead)')
      .attr('class', 'graph-link');

    // Render nodes as groups (circle + label)
    this.nodeElements = this.nodeGroup
      .selectAll<SVGGElement, SimNode>('g.node')
      .data(this.nodes, (d: SimNode) => d.id)
      .join('g')
      .attr('class', 'node')
      .style('cursor', 'pointer')
      .call(this.dragBehavior());

    // Circle
    this.nodeElements
      .append('circle')
      .attr('r', 8)
      .attr('fill', (d: SimNode) => getColorForType(d.type))
      .attr('stroke', '#222')
      .attr('stroke-width', 1.5);

    // Label
    this.nodeElements
      .append('text')
      .text((d: SimNode) => this.truncateLabel(d.name, 16))
      .attr('dx', 12)
      .attr('dy', 4)
      .attr('fill', '#bbb')
      .attr('font-size', '11px')
      .attr('font-family', 'sans-serif')
      .attr('pointer-events', 'none');

    // Click handler for selection
    this.nodeElements.on('click', (event: MouseEvent, d: SimNode) => {
      event.stopPropagation();
      this.selectNode(d);
    });

    // Apply current filter state
    this.applyFilter();
  }

  /**
   * Called on each simulation tick to update element positions
   */
  private tick(): void {
    if (this.linkElements) {
      this.linkElements
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y);
    }

    if (this.nodeElements) {
      this.nodeElements.attr('transform', (d: any) => `translate(${d.x},${d.y})`);
    }
  }

  /**
   * Drag behavior for nodes
   */
  private dragBehavior() {
    let dragNode: SimNode | null = null;

    return (selection: Selection<SVGGElement, SimNode, SVGGElement, unknown>) => {
      selection
        .on('mousedown', (event: MouseEvent, d: SimNode) => {
          event.stopPropagation();
          dragNode = d;
          if (this.simulation) {
            d.fx = d.x;
            d.fy = d.y;
            this.simulation.alphaTarget(0.3).restart();
          }
        })
        .on('mousemove', (event: MouseEvent) => {
          if (!dragNode || !this.simulation) return;
          // Get mouse position relative to SVG
          const [mx, my] = this.getMouseSVGCoords(event);
          dragNode.fx = mx;
          dragNode.fy = my;
        })
        .on('mouseup', () => {
          if (dragNode && this.simulation) {
            dragNode.fx = null;
            dragNode.fy = null;
            this.simulation.alphaTarget(0);
          }
          dragNode = null;
        });
    };
  }

  /**
   * Convert mouse event coordinates to SVG coordinates accounting for zoom transform
   */
  private getMouseSVGCoords(event: MouseEvent): [number, number] {
    const svgEl = this.svg.node();
    if (!svgEl) return [0, 0];

    // Get the current transform from the g element
    const gEl = this.g.node();
    if (gEl) {
      const ctm = gEl.getScreenCTM();
      if (ctm) {
        const point = svgEl.createSVGPoint();
        point.x = event.clientX;
        point.y = event.clientY;
        const svgPoint = point.matrixTransform(ctm.inverse());
        return [svgPoint.x, svgPoint.y];
      }
    }

    // Fallback: simple relative coords
    const rect = svgEl.getBoundingClientRect();
    return [
      (event.clientX - rect.left) * (this.width / rect.width),
      (event.clientY - rect.top) * (this.height / rect.height),
    ];
  }

  // ----------------------------------------------------------
  // Node Selection
  // ----------------------------------------------------------

  private selectNode(node: SimNode): void {
    this.selectedNode = node;

    // Highlight selected node and connected elements
    this.applySelection();

    // Populate backlinks panel
    this.showBacklinksPanel(node);

    // Fire callback
    if (this.onEntitySelect) {
      this.onEntitySelect({
        id: node.id,
        type: node.type,
        name: node.name,
        properties: node.properties,
        scope_id: node.scope_id,
        source_channel: node.source_channel,
      });
    }
  }

  private clearSelection(): void {
    this.selectedNode = null;
    this.applySelection();
    this.hideBacklinksPanel();
    if (this.onEntitySelect) {
      this.onEntitySelect(null);
    }
  }

  private applySelection(): void {
    if (!this.nodeElements) return;

    const selected = this.selectedNode;

    if (!selected) {
      // Clear all highlights
      this.nodeElements
        .select('circle')
        .attr('stroke', '#222')
        .attr('stroke-width', 1.5);
      this.nodeElements
        .select('text')
        .attr('fill', '#bbb');
      if (this.linkElements) {
        this.linkElements
          .attr('stroke', '#444')
          .attr('stroke-width', 1.5)
          .attr('opacity', 1);
      }
      return;
    }

    // Find connected node ids
    const connectedIds = new Set<string>();
    connectedIds.add(selected.id);

    this.links.forEach((link: SimLink) => {
      const srcId = typeof link.source === 'object' ? (link.source as SimNode).id : String(link.source);
      const tgtId = typeof link.target === 'object' ? (link.target as SimNode).id : String(link.target);
      if (srcId === selected.id) connectedIds.add(tgtId);
      if (tgtId === selected.id) connectedIds.add(srcId);
    });

    // Dim non-connected nodes
    this.nodeElements
      .select('circle')
      .attr('stroke', (d: SimNode) => {
        if (d.id === selected.id) return '#fff';
        return connectedIds.has(d.id) ? '#888' : '#222';
      })
      .attr('stroke-width', (d: SimNode) => {
        return d.id === selected.id ? 3 : connectedIds.has(d.id) ? 2 : 1.5;
      });

    // Dim non-connected nodes' labels
    this.nodeElements
      .select('text')
      .attr('fill', (d: SimNode) => {
        return connectedIds.has(d.id) ? '#ddd' : '#555';
      });

    // Highlight connected links, dim others
    if (this.linkElements) {
      this.linkElements
        .attr('stroke', (d: SimLink) => {
          const srcId = typeof d.source === 'object' ? (d.source as SimNode).id : d.source;
          const tgtId = typeof d.target === 'object' ? (d.target as SimNode).id : d.target;
          if (srcId === selected.id || tgtId === selected.id) return getColorForType(selected.type);
          return '#333';
        })
        .attr('stroke-width', (d: SimLink) => {
          const srcId = typeof d.source === 'object' ? (d.source as SimNode).id : d.source;
          const tgtId = typeof d.target === 'object' ? (d.target as SimNode).id : d.target;
          return (srcId === selected.id || tgtId === selected.id) ? 2.5 : 1;
        })
        .attr('opacity', (d: SimLink) => {
          const srcId = typeof d.source === 'object' ? (d.source as SimNode).id : d.source;
          const tgtId = typeof d.target === 'object' ? (d.target as SimNode).id : d.target;
          return (srcId === selected.id || tgtId === selected.id) ? 1 : 0.3;
        });
    }
  }

  // ----------------------------------------------------------
  // Search / Filter
  // ----------------------------------------------------------

  private applyFilter(): void {
    if (!this.nodeElements) return;

    const hasSearch = this.searchTerm.length > 0;
    const hasType = this.activeTypeFilter.length > 0;

    this.nodeElements
      .select('circle')
      .attr('opacity', (d: SimNode) => {
        if (!hasSearch && !hasType) return 1;

        const matchesSearch = !hasSearch ||
          d.name.toLowerCase().includes(this.searchTerm) ||
          d.id.toLowerCase().includes(this.searchTerm) ||
          d.type.toLowerCase().includes(this.searchTerm);

        const matchesType = !hasType || d.type === this.activeTypeFilter;

        return (matchesSearch && matchesType) ? 1 : 0.2;
      });

    this.nodeElements
      .select('text')
      .attr('opacity', (d: SimNode) => {
        if (!hasSearch && !hasType) return 1;

        const matchesSearch = !hasSearch ||
          d.name.toLowerCase().includes(this.searchTerm) ||
          d.id.toLowerCase().includes(this.searchTerm) ||
          d.type.toLowerCase().includes(this.searchTerm);

        const matchesType = !hasType || d.type === this.activeTypeFilter;

        return (matchesSearch && matchesType) ? 1 : 0.2;
      });

    if (this.linkElements) {
      this.linkElements.attr('opacity', (hasSearch || hasType) ? 0.2 : 1);
    }
  }

  // ----------------------------------------------------------
  // Backlinks Panel
  // ----------------------------------------------------------

  private showBacklinksPanel(node: SimNode): void {
    this.hideBacklinksPanel();

    const panel = document.createElement('div');
    panel.style.cssText = `
      position: absolute;
      top: 50px;
      right: 10px;
      width: 280px;
      max-height: 80%;
      overflow-y: auto;
      background: #16213e;
      border: 1px solid #0f3460;
      border-radius: 6px;
      padding: 12px;
      font-family: sans-serif;
      color: #ccc;
      font-size: 12px;
      z-index: 10;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    `;
    panel.id = 'kg-backlinks-panel';

    // Header
    const header = document.createElement('div');
    header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;';
    const title = document.createElement('strong');
    title.style.cssText = `color:${getColorForType(node.type)};font-size:14px;`;
    title.textContent = node.name;
    header.appendChild(title);

    const closeBtn = document.createElement('span');
    closeBtn.textContent = '×';
    closeBtn.style.cssText = 'cursor:pointer;font-size:18px;color:#888;padding:0 4px;';
    closeBtn.addEventListener('click', () => this.clearSelection());
    header.appendChild(closeBtn);
    panel.appendChild(header);

    // Type badge
    const badge = document.createElement('div');
    badge.style.cssText = `display:inline-block;padding:2px 8px;border-radius:3px;background:${getColorForType(node.type)};color:#fff;font-size:10px;margin-bottom:8px;`;
    badge.textContent = node.type;
    panel.appendChild(badge);

    // Relations section
    const relationsSection = document.createElement('div');
    relationsSection.style.cssText = 'margin-top:8px;';

    // Find local relations for this node
    const localRelations = this.links.filter((l: SimLink) => {
      const srcId = typeof l.source === 'object' ? (l.source as SimNode).id : l.source;
      const tgtId = typeof l.target === 'object' ? (l.target as SimNode).id : l.target;
      return srcId === node.id || tgtId === node.id;
    });

    if (localRelations.length > 0) {
      const relTitle = document.createElement('div');
      relTitle.style.cssText = 'font-weight:600;margin-bottom:4px;color:#aaa;';
      relTitle.textContent = `Relations (${localRelations.length})`;
      relationsSection.appendChild(relTitle);

      for (const rel of localRelations) {
        const srcId = typeof rel.source === 'object' ? (rel.source as SimNode).id : String(rel.source);
        const tgtId = typeof rel.target === 'object' ? (rel.target as SimNode).id : String(rel.target);
        const isOutgoing = srcId === node.id;
        const otherId: string = isOutgoing ? tgtId : srcId;
        const otherNode = this.nodes.find(n => n.id === otherId);

        const relItem = document.createElement('div');
        relItem.style.cssText = 'padding:4px 6px;margin:2px 0;background:#1a1a2e;border-radius:3px;cursor:pointer;display:flex;align-items:center;gap:4px;';

        const arrow = document.createElement('span');
        arrow.style.cssText = 'color:#666;font-size:10px;';
        arrow.textContent = isOutgoing ? '→' : '←';
        relItem.appendChild(arrow);

        const relType = document.createElement('span');
        relType.style.cssText = 'color:#888;font-size:10px;min-width:50px;';
        relType.textContent = rel.relationType;
        relItem.appendChild(relType);

        const relName = document.createElement('span');
        relName.style.cssText = `color:${otherNode ? getColorForType(otherNode.type) : '#aaa'};`;
        relName.textContent = otherNode ? otherNode.name : otherId;
        relItem.appendChild(relName);

        // Click to navigate to connected node
        relItem.addEventListener('click', () => {
          if (otherNode) {
            this.selectNode(otherNode);
          }
        });

        relationsSection.appendChild(relItem);
      }
    }

    panel.appendChild(relationsSection);

    // Properties section
    const propsSection = document.createElement('div');
    propsSection.style.cssText = 'margin-top:10px;';
    const propsTitle = document.createElement('div');
    propsTitle.style.cssText = 'font-weight:600;margin-bottom:4px;color:#aaa;';
    propsTitle.textContent = 'Properties';
    propsSection.appendChild(propsTitle);

    const propsList = document.createElement('div');
    propsList.style.cssText = 'font-size:11px;color:#999;';
    const propKeys = Object.keys(node.properties);
    if (propKeys.length === 0) {
      propsList.textContent = 'No properties';
    } else {
      for (const key of propKeys.slice(0, 8)) {
        const val = node.properties[key];
        const line = document.createElement('div');
        line.style.cssText = 'padding:2px 0;';
        const keySpan = document.createElement('span');
        keySpan.style.cssText = 'color:#aaa;';
        keySpan.textContent = `${escapeHtml(key)}: `;
        line.appendChild(keySpan);
        const valSpan = document.createElement('span');
        valSpan.textContent = typeof val === 'string' ? val : JSON.stringify(val);
        line.appendChild(valSpan);
        propsList.appendChild(line);
      }
      if (propKeys.length > 8) {
        const more = document.createElement('div');
        more.style.cssText = 'color:#666;';
        more.textContent = `+${propKeys.length - 8} more...`;
        propsList.appendChild(more);
      }
    }
    propsSection.appendChild(propsList);
    panel.appendChild(propsSection);

    // Fetch remote backlinks if fetcher is set
    if (this.backlinksFetcher) {
      const remoteSection = document.createElement('div');
      remoteSection.style.cssText = 'margin-top:10px;';
      const remoteTitle = document.createElement('div');
      remoteTitle.style.cssText = 'font-weight:600;margin-bottom:4px;color:#aaa;';
      remoteTitle.textContent = 'Remote Backlinks';
      remoteSection.appendChild(remoteTitle);

      const loading = document.createElement('div');
      loading.style.cssText = 'color:#666;font-size:11px;';
      loading.textContent = 'Loading...';
      remoteSection.appendChild(loading);
      panel.appendChild(remoteSection);

      this.backlinksFetcher(node.id).then((backlinks: GraphRelation[]) => {
        loading.remove();
        if (backlinks.length === 0) {
          const empty = document.createElement('div');
          empty.style.cssText = 'color:#666;font-size:11px;';
          empty.textContent = 'No remote backlinks';
          remoteSection.appendChild(empty);
          return;
        }

        for (const bl of backlinks.slice(0, 10)) {
          const blItem = document.createElement('div');
          blItem.style.cssText = 'padding:4px 6px;margin:2px 0;background:#1a1a2e;border-radius:3px;font-size:11px;color:#999;';
          const isSource = bl.source === node.id;

          const arrowSpan = document.createElement('span');
          arrowSpan.style.cssText = 'color:#666;';
          arrowSpan.textContent = isSource ? '→ ' : '← ';
          blItem.appendChild(arrowSpan);

          const typeSpan = document.createElement('span');
          typeSpan.style.cssText = 'color:#aaa;';
          typeSpan.textContent = bl.relationType + ' ';
          blItem.appendChild(typeSpan);

          const nameSpan = document.createElement('span');
          nameSpan.textContent = isSource ? bl.target : bl.source;
          blItem.appendChild(nameSpan);

          remoteSection.appendChild(blItem);
        }
        if (backlinks.length > 10) {
          const more = document.createElement('div');
          more.style.cssText = 'color:#666;font-size:11px;';
          more.textContent = `+${backlinks.length - 10} more...`;
          remoteSection.appendChild(more);
        }
      }).catch(() => {
        loading.textContent = 'Failed to load backlinks';
        loading.style.color = '#F44336';
      });
    }

    this.container.appendChild(panel);
    this.backlinksPanel = panel;
  }

  private hideBacklinksPanel(): void {
    if (this.backlinksPanel) {
      this.backlinksPanel.remove();
      this.backlinksPanel = null;
    }
  }

  // ----------------------------------------------------------
  // Utility
  // ----------------------------------------------------------

  private truncateLabel(text: string, maxLen: number): string {
    if (text.length <= maxLen) return text;
    return text.slice(0, maxLen - 1) + '…';
  }
}
