import cytoscape, { Core, ElementDefinition } from 'cytoscape';
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import type { Analysis, GEdge, GNode } from '../types';
import { CATEGORY_STYLE, NODE_STYLE } from '../lib/vocab';

export type LayoutMode = 'route' | 'network' | 'concentric';

export interface GraphFilters {
  nodeTypes: Set<string>;
  sources: Set<string>;
  categories: Set<string>;
  showSecondary: boolean;
}

export interface GraphHandle {
  fit: () => void;
  zoom: (factor: number) => void;
  reset: () => void;
  center: (id: string) => void;
  png: () => string | null;
}

interface Props {
  analysis: Analysis;
  filters: GraphFilters;
  layout: LayoutMode;
  selectedId: string | null;
  pathNodes: string[];
  pathEdges: string[];
  searchTerm: string;
  marked: string[];
  flashIds: string[];
  onSelectNode: (id: string) => void;
  onSelectEdge: (id: string) => void;
  onBackground: () => void;
  onExpand: (id: string) => void;
}

const COL = 205;
const ROW = 54;

/** Deterministic "route" layout: the GPS reading direction variant → gene → protein → pathway → downstream. */
function routePositions(nodes: GNode[], edges: GEdge[]): Record<string, { x: number; y: number }> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const col = new Map<string, number>();
  const base: Record<string, number> = { variant: 0, gene: 1, protein: 2, protein_region: 3, reactome_entity: 3, pathway: 4 };
  nodes.forEach((n) => { if (n.type in base) col.set(n.id, base[n.type]); });
  // reactions: depth along curated event order, starting from those the protein participates in
  const queue: string[] = [];
  edges.forEach((e) => {
    if ((e.type === 'PROTEIN_PARTICIPATES_IN_REACTION') && byId.get(e.target)?.type === 'reaction' && !col.has(e.target)) {
      col.set(e.target, 5); queue.push(e.target);
    }
  });
  while (queue.length) {
    const id = queue.shift()!;
    const c = col.get(id)!;
    edges.forEach((e) => {
      if (e.source !== id) return;
      const t = byId.get(e.target);
      if (!t || col.has(t.id)) return;
      if (e.type === 'REACTION_PRECEDES' && t.type === 'reaction') { col.set(t.id, Math.min(c + 1, 9)); queue.push(t.id); }
      if (e.type === 'REACTION_PRODUCES' && t.type === 'physical_entity') { col.set(t.id, Math.min(c + 1, 10)); queue.push(t.id); }
      if (e.type === 'ENTITY_INPUT_OF_REACTION' && t.type === 'reaction') { col.set(t.id, Math.min(c + 1, 10)); queue.push(t.id); }
    });
  }
  nodes.forEach((n) => {
    if (!col.has(n.id) && (n.type === 'reaction' || n.type === 'physical_entity')) col.set(n.id, n.type === 'reaction' ? 5 : 6);
  });

  const pos: Record<string, { x: number; y: number }> = {};
  const columns = new Map<number, GNode[]>();
  nodes.forEach((n) => {
    const c = col.get(n.id);
    if (c === undefined) return;
    if (!columns.has(c)) columns.set(c, []);
    columns.get(c)!.push(n);
  });
  let maxHalf = 0;
  columns.forEach((list, c) => {
    list.sort((a, b) => (a.flags.includes('disease_pathway') || a.flags.includes('disease_event') ? 0 : 1) - (b.flags.includes('disease_pathway') || b.flags.includes('disease_event') ? 0 : 1) || a.label.localeCompare(b.label));
    const half = ((list.length - 1) * ROW) / 2;
    maxHalf = Math.max(maxHalf, half);
    list.forEach((n, i) => { pos[n.id] = { x: c * COL, y: i * ROW - half }; });
  });
  const band = (types: string[], y0: number, dir: 1 | -1) => {
    const list = nodes.filter((n) => types.includes(n.type)).sort((a, b) => Number(a.secondary) - Number(b.secondary) || a.label.localeCompare(b.label));
    const perRow = 9;
    list.forEach((n, i) => {
      const r = Math.floor(i / perRow);
      pos[n.id] = { x: COL * 0.5 + (i % perRow) * 150, y: y0 + dir * r * 70 };
    });
    return Math.ceil(list.length / perRow);
  };
  const top = -maxHalf - 110;
  band(['interactor'], top, -1);
  const rowsD = band(['disease'], maxHalf + 110, 1);
  band(['drug'], maxHalf + 110 + rowsD * 70 + 60, 1);
  return pos;
}

function toElements(a: Analysis): ElementDefinition[] {
  const els: ElementDefinition[] = [];
  for (const n of a.graph.nodes) {
    const style = NODE_STYLE[n.type] ?? NODE_STYLE.reaction;
    const label = n.type === 'variant' ? `${n.label}` : n.label.length > 46 ? `${n.label.slice(0, 44)}…` : n.label;
    els.push({
      group: 'nodes',
      data: { id: n.id, label, type: n.type, color: style.color, shape: style.shape, source: n.source, secondary: n.secondary },
      classes: [n.type, n.id === a.root_id ? 'root' : '', n.flags.includes('vus') ? 'vus' : '', n.flags.includes('disease_pathway') || n.flags.includes('disease_event') ? 'disease-flag' : ''].join(' '),
    });
  }
  for (const e of a.graph.edges) {
    const cs = CATEGORY_STYLE[e.category] ?? CATEGORY_STYLE.inferred;
    els.push({
      group: 'edges',
      data: { id: e.id, source: e.source, target: e.target, label: e.label, color: cs.color, line: cs.line, width: 1.4 + Math.min(e.evidence.length, 8) * 0.35, category: e.category },
      classes: e.category,
    });
  }
  return els;
}

const STYLE: any[] = [
  { selector: 'node', style: {
    'background-color': 'data(color)', shape: 'data(shape)', width: 26, height: 26, label: 'data(label)', color: '#dbeafe',
    'font-size': 10, 'font-family': 'Inter, ui-sans-serif, system-ui, sans-serif', 'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 5,
    'text-wrap': 'wrap', 'text-max-width': '150px', 'text-outline-color': '#070d1a', 'text-outline-width': 2.5, 'border-width': 1.5, 'border-color': '#0b1324',
    'transition-property': 'opacity, border-width, border-color', 'transition-duration': 180,
  } },
  { selector: 'node.root', style: { width: 46, height: 46, 'font-size': 13, 'font-weight': 700, 'border-width': 3, 'border-color': '#fdf2f8', color: '#fff' } },
  { selector: 'node.gene, node.protein', style: { width: 38, height: 30, 'font-size': 12, 'font-weight': 600 } },
  { selector: 'node.pathway', style: { width: 30, height: 30 } },
  { selector: 'node.reaction, node.physical_entity', style: { width: 18, height: 18, 'font-size': 9 } },
  { selector: 'node.interactor', style: { width: 16, height: 16, 'font-size': 9, opacity: 0.85 } },
  { selector: 'node.disease-flag', style: { 'border-color': '#f472b6', 'border-width': 2 } },
  { selector: 'node.vus', style: { 'border-color': '#fbbf24', 'border-style': 'dashed', 'border-width': 3 } },
  { selector: 'edge', style: {
    width: 'data(width)', 'line-color': 'data(color)', 'target-arrow-color': 'data(color)', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.8,
    'curve-style': 'bezier', 'line-style': 'data(line)', opacity: 0.55, 'font-size': 9, color: '#cbd5e1', 'text-outline-color': '#070d1a', 'text-outline-width': 2,
    'text-rotation': 'autorotate', 'transition-property': 'opacity, width', 'transition-duration': 180,
  } },
  { selector: 'edge.show-label, edge:selected', style: { label: 'data(label)', opacity: 1 } },
  { selector: 'node:selected', style: { 'border-width': 4, 'border-color': '#ffffff', 'overlay-opacity': 0 } },
  { selector: 'edge:selected', style: { width: 5, opacity: 1 } },
  { selector: '.faded', style: { opacity: 0.12 } },
  { selector: 'node.path', style: { 'border-width': 4, 'border-color': '#fef08a', opacity: 1 } },
  { selector: 'edge.path', style: { width: 5, opacity: 1, label: 'data(label)', 'line-color': '#fef08a', 'target-arrow-color': '#fef08a' } },
  { selector: 'node.match', style: { 'border-width': 5, 'border-color': '#22d3ee', 'underlay-color': '#22d3ee', 'underlay-opacity': 0.25, 'underlay-padding': 8 } },
  { selector: 'node.marked', style: { 'underlay-color': '#facc15', 'underlay-opacity': 0.35, 'underlay-padding': 7, 'underlay-shape': 'ellipse' } },
  { selector: 'node.flash', style: { 'underlay-color': '#2dd4bf', 'underlay-opacity': 0.45, 'underlay-padding': 10 } },
  { selector: '.hidden', style: { display: 'none' } },
];

const GraphCanvas = forwardRef<GraphHandle, Props>(function GraphCanvas(props, ref) {
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const handlers = useRef(props);
  handlers.current = props;
  const lastStructure = useRef<string>('');

  useEffect(() => {
    if (!container.current) return;
    const cy = cytoscape({ container: container.current, style: STYLE, minZoom: 0.08, maxZoom: 3, wheelSensitivity: 0.25, boxSelectionEnabled: false });
    cy.on('tap', 'node', (evt) => handlers.current.onSelectNode(evt.target.id()));
    cy.on('tap', 'edge', (evt) => handlers.current.onSelectEdge(evt.target.id()));
    cy.on('tap', (evt) => { if (evt.target === cy) handlers.current.onBackground(); });
    cy.on('dbltap', 'node', (evt) => handlers.current.onExpand(evt.target.id()));
    cy.on('mouseover', 'edge', (evt) => evt.target.addClass('show-label'));
    cy.on('mouseout', 'edge', (evt) => evt.target.removeClass('show-label'));
    cy.on('mouseover', 'node', () => { if (container.current) container.current.style.cursor = 'pointer'; });
    cy.on('mouseout', 'node', () => { if (container.current) container.current.style.cursor = 'default'; });
    cyRef.current = cy;
    // The container may still be 0×0 on first render (tab switches, flex layout); keep Cytoscape in sync.
    let lastW = 0;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      cy.resize();
      if (lastW === 0 && w > 0) cy.fit(cy.elements().not('.hidden'), 40);
      lastW = w;
    });
    ro.observe(container.current);
    return () => { ro.disconnect(); cy.destroy(); cyRef.current = null; };
  }, []);

  const runLayout = (fit: boolean) => {
    const cy = cyRef.current;
    if (!cy) return;
    const visible = cy.elements().not('.hidden');
    cy.resize();
    if (props.layout === 'route') {
      const pos = routePositions(props.analysis.graph.nodes, props.analysis.graph.edges);
      cy.layout({ name: 'preset', positions: (n: any) => pos[n.id()] ?? { x: 0, y: 0 }, fit, padding: 40, animate: !fit, animationDuration: 350 } as any).run();
    } else if (props.layout === 'network') {
      visible.layout({ name: 'cose', animate: false, fit, padding: 40, nodeRepulsion: () => 9000, idealEdgeLength: () => 90, randomize: false, nodeDimensionsIncludeLabels: true } as any).run();
    } else {
      const rank: Record<string, number> = { variant: 10, gene: 9, protein: 8, protein_region: 7, reactome_entity: 7, pathway: 5, reaction: 4, physical_entity: 3, disease: 6, drug: 6, interactor: 2 };
      visible.layout({ name: 'concentric', fit, padding: 40, minNodeSpacing: 24, concentric: (n: any) => rank[n.data('type')] ?? 1, levelWidth: () => 1, animate: false } as any).run();
    }
  };

  // Rebuild elements when the graph structure changes (new analysis or expansion).
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const structure = `${props.analysis.analysis_id}:${props.analysis.graph.nodes.length}:${props.analysis.graph.edges.length}`;
    if (structure === lastStructure.current) return;
    const isNewAnalysis = !lastStructure.current.startsWith(`${props.analysis.analysis_id}:`);
    lastStructure.current = structure;
    cy.batch(() => {
      cy.elements().remove();
      cy.add(toElements(props.analysis));
    });
    applyFilters();
    runLayout(isNewAnalysis);
    if (isNewAnalysis) requestAnimationFrame(() => { cy.resize(); cy.fit(cy.elements().not('.hidden'), 40); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.analysis]);

  useEffect(() => { runLayout(true); }, [props.layout]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyFilters = () => {
    const cy = cyRef.current;
    if (!cy) return;
    const { filters } = handlers.current;
    const a = handlers.current.analysis;
    const nodeOk = new Map<string, boolean>();
    const evidence = a.graph.evidence;
    cy.batch(() => {
      for (const n of a.graph.nodes) {
        const ok = n.id === a.root_id || (filters.nodeTypes.has(n.type) && (filters.showSecondary || !n.secondary));
        nodeOk.set(n.id, ok);
      }
      for (const e of a.graph.edges) {
        const srcs = e.evidence.map((id) => evidence[id]?.source).filter(Boolean);
        const sourceOk = srcs.some((s) => filters.sources.has(s));
        const catOk = e.categories.some((c) => filters.categories.has(c));
        const ok = Boolean(nodeOk.get(e.source) && nodeOk.get(e.target) && sourceOk && catOk && (filters.showSecondary || !e.secondary));
        cy.getElementById(e.id).toggleClass('hidden', !ok);
      }
      // hide nodes left without any visible edge (except the root)
      for (const n of a.graph.nodes) {
        const el = cy.getElementById(n.id);
        const visibleEdges = el.connectedEdges().not('.hidden').length;
        el.toggleClass('hidden', !nodeOk.get(n.id) || (n.id !== a.root_id && visibleEdges === 0));
      }
    });
  };

  useEffect(() => { applyFilters(); }, [props.filters]); // eslint-disable-line react-hooks/exhaustive-deps

  // Selection, path, search, marks and flashes.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.elements().removeClass('faded path match marked flash');
      cy.elements().unselect();
      if (props.selectedId) cy.getElementById(props.selectedId).select();
      if (props.pathNodes.length) {
        cy.elements().addClass('faded');
        props.pathNodes.forEach((id) => cy.getElementById(id).removeClass('faded').addClass('path'));
        props.pathEdges.forEach((id) => cy.getElementById(id).removeClass('faded').addClass('path'));
      }
      const term = props.searchTerm.trim().toLowerCase();
      if (term.length >= 2) {
        cy.nodes().forEach((n) => {
          const node = props.analysis.graph.nodes.find((x) => x.id === n.id());
          const hay = `${node?.label} ${node?.subtitle ?? ''} ${node?.id}`.toLowerCase();
          if (hay.includes(term)) n.addClass('match');
        });
      }
      props.marked.forEach((id) => cy.getElementById(id).addClass('marked'));
      props.flashIds.forEach((id) => cy.getElementById(id).addClass('flash'));
    });
  }, [props.selectedId, props.pathNodes, props.pathEdges, props.searchTerm, props.marked, props.flashIds, props.analysis]);

  useImperativeHandle(ref, () => ({
    fit: () => cyRef.current?.fit(cyRef.current.elements().not('.hidden'), 40),
    zoom: (factor: number) => {
      const cy = cyRef.current;
      if (!cy) return;
      cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
    },
    reset: () => runLayout(true),
    center: (id: string) => {
      const cy = cyRef.current;
      const el = cy?.getElementById(id);
      if (cy && el && el.length) cy.animate({ center: { eles: el }, zoom: Math.max(cy.zoom(), 0.9) } as any, { duration: 300 });
    },
    png: () => cyRef.current?.png({ full: true, bg: '#070d1a', scale: 2 }) ?? null,
  }));

  return <div ref={container} className="h-full w-full" role="application" aria-label="Interactive biological network. Use the node list in the side panel for keyboard access." />;
});

export default GraphCanvas;
