// The v1 scenes and the solver params the demo runs them with.
import type { SceneOptions } from '../vendor/three-avbd/src/avbd3d/bench-scenes.ts';
import { type GpuParams3D, gpuParams3D, REF_UP } from '../vendor/three-avbd/src/avbd3d/gpu/solver.ts';
import { sceneByName3D } from '../vendor/three-avbd/src/avbd3d/sim.ts';

export const V1_SCENES = ['Brick Ring (28k)', 'Brick Ring (110k)', 'Brick Walls (27k)', 'Wall Smash (2k)', 'Breakable Wall (600)',
  'Chain Mail (1.6k)', 'Heavy Pendulum', 'Box Pile (4k)', 'Box Pile (32k)', 'Box Columns (100k)'];

/** The demo's GPU `defaults()` (app3d/main.ts:103-110), scene params resolved against its options. */
export function paramsFor(name: string, options: SceneOptions = {}): Partial<GpuParams3D> {
  const scene = sceneByName3D(name);
  const p = scene.params;
  return {
    ...gpuParams3D(),
    up: REF_UP,
    matchNearest: true,
    faceBias: true,
    ...(typeof p === 'function' ? p({ ...scene.options, ...options }) : p),
  };
}
