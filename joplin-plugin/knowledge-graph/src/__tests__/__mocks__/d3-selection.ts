/*
 * Mock for d3-selection module in tests
 */

export class Selection<GElement extends Datum = any, Datum = any, PDatum = any, PElement extends Datum = any> {
  private _attrs: Map<string, any> = new Map();
  private _styles: Map<string, any> = new Map();
  private _classes: Set<string> = new Set();
  private _data: any[] = [];

  select(_selector: string): Selection { return new Selection(); }
  selectAll(_selector: string): Selection { return new Selection(); }
  attr(_name: string, _value?: any): Selection { return this; }
  style(_name: string, _value?: any, _priority?: string): Selection { return this; }
  classed(_name: string, _value?: boolean): Selection { return this; }
  property(_name: string, _value?: any): Selection { return this; }
  text(_value?: any): Selection { return this; }
  html(_value?: any): Selection { return this; }
  append(_name: string): Selection { return new Selection(); }
  insert(_name: string, _before?: string): Selection { return new Selection(); }
  remove(): Selection { return this; }
  data(_data?: any[], _key?: any): Selection { return this; }
  join(_enter?: any, _update?: any, _exit?: any): Selection { return this; }
  enter(): Selection { return new Selection(); }
  exit(): Selection { return new Selection(); }
  datum(_value?: any): Selection { return this; }
  on(_typenames: string, _listener?: any): Selection { return this; }
  dispatch(_type: string, _parameters?: any): Selection { return this; }
  call(_callback: any, ..._args: any[]): Selection { if (typeof _callback === 'function') _callback(this, ..._args); return this; }
  node(): any { return null; }
  nodes(): any[] { return []; }
  size(): number { return 0; }
  empty(): boolean { return true; }
  each(_callback: any): Selection { return this; }
  transition(): any { return this; }
  raise(): Selection { return this; }
  lower(): Selection { return this; }
  merge(_other: Selection): Selection { return this; }
  filter(_selector: any): Selection { return new Selection(); }
}

export function select(_selector: any): Selection {
  return new Selection();
}

export function selectAll(_selector: any): Selection {
  return new Selection();
}

export function create(_name: string): Selection {
  return new Selection();
}

export function creator(_name: string): any {
  return (_node: any) => null;
}

export function matcher(_selector: string): any {
  return (_node: any) => false;
}

export function selector(_selector: string): any {
  return (_node: any) => null;
}

export function selectorAll(_selector: string): any {
  return (_node: any) => [];
}

export function window(_node: any): any {
  return globalThis;
}

export function style(_node: any, _name: string): string {
  return '';
}

export namespace local {
  export function set(_node: any, _value: any): void {}
  export function get(_node: any): any { return undefined; }
  export function remove(_node: any): void {}
}

export namespace namespace {
  export function prefix(_name: string): string | null { return null; }
}

export function namespaces(_name: string): { space: string; local: string } | null {
  return null;
}
