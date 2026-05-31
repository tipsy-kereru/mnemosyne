/*
 * Mock for d3-force module in tests
 */

export interface SimulationNodeDatum {
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
  index?: number;
}

export interface SimulationLinkDatum<N> {
  source: string | number | N;
  target: string | number | N;
  index?: number;
}

export class Simulation {
  private _nodes: any[] = [];
  private _forces: Map<string, any> = new Map();
  private _handlers: Map<string, Function> = new Map();

  nodes(): any[] { return this._nodes; }
  force(name: string, _?: any): any { return this; }
  on(name: string, handler?: Function): any {
    if (handler) { this._handlers.set(name, handler); }
    return this;
  }
  alpha(_?: number): any { return this; }
  alphaTarget(_?: number): any { return this; }
  alphaDecay(_?: number): any { return this; }
  velocityDecay(_?: number): any { return this; }
  restart(): any { return this; }
  stop(): any { return this; }
  tick(_?: number): any { return this; }
  find(_x: number, _y: number, _radius?: number): any { return undefined; }
}

export function forceSimulation<N extends SimulationNodeDatum>(nodes?: N[]): Simulation {
  const sim = new Simulation();
  if (nodes) { (sim as any)._nodes = nodes; }
  return sim;
}

export function forceLink<N extends SimulationNodeDatum, L extends SimulationLinkDatum<N>>(
  links?: L[]
): any {
  return {
    id: (_fn?: (d: N, i: number, nodes: N[]) => string) => ({ distance: (_d?: number) => ({}) }),
    distance: (_d?: number) => ({}),
    strength: (_s?: any) => ({}),
  };
}

export function forceManyBody(): any {
  return { strength: (_s?: number) => ({}) };
}

export function forceCenter(_x?: number, _y?: number): any {
  return { strength: (_s?: number) => ({}) };
}

export function forceCollide<N extends SimulationNodeDatum>(): any {
  return { radius: (_r?: number) => ({}) };
}

export function forceX<N extends SimulationNodeDatum>(_x?: number): any {
  return { strength: (_s?: number) => ({}) };
}

export function forceY<N extends SimulationNodeDatum>(_y?: number): any {
  return { strength: (_s?: number) => ({}) };
}

export function forceRadial<N extends SimulationNodeDatum>(_r?: number, _x?: number, _y?: number): any {
  return { strength: (_s?: number) => ({}) };
}
