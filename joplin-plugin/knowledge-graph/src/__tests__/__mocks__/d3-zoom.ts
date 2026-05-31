/*
 * Mock for d3-zoom module in tests
 */

export const zoomIdentity = {
  x: 0,
  y: 0,
  k: 1,
  translate(_x: number, _y: number): any { return this; },
  scale(_k: number): any { return this; },
  apply(_point: any): any { return _point; },
  applyX(_x: number): number { return _x; },
  applyY(_y: number): number { return _y; },
  invert(_point: any): any { return _point; },
  invertX(_x: number): number { return _x; },
  invertY(_y: number): number { return _y; },
  rescaleX(_x: any): any { return _x; },
  rescaleY(_y: any): any { return _y; },
  rescale(_scale: any): any { return _scale; },
  toString(): string { return 'translate(0,0) scale(1)'; },
};

export class ZoomBehavior {
  scaleExtent(_extent: [number, number]): ZoomBehavior { return this; }
  translateExtent(_extent: [[number, number], [number, number]]): ZoomBehavior { return this; }
  constrain(_constrain: any): ZoomBehavior { return this; }
  filter(_filter: any): ZoomBehavior { return this; }
  wheelDelta(_delta: any): ZoomBehavior { return this; }
  touchable(_touchable: any): ZoomBehavior { return this; }
  clickDistance(_distance: number): ZoomBehavior { return this; }
  tapDistance(_distance: number): ZoomBehavior { return this; }
  duration(_duration: number): ZoomBehavior { return this; }
  interpolate(_interpolate: any): ZoomBehavior { return this; }
  on(_typenames: string, _listener?: any): ZoomBehavior { return this; }
  transform(_selection: any, _transform: any, _point?: any): void {}
  transformBy(_selection: any, _transform: any, _point?: any): void {}
  translateTo(_selection: any, _x: number, _y: number): void {}
  scaleTo(_selection: any, _k: number, _point?: any): void {}
}

export function zoom(): ZoomBehavior {
  return new ZoomBehavior();
}

export function zoomTransform(_node: any): any {
  return zoomIdentity;
}
