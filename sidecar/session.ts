// One sidecar session: a GpuSim3D driven by wire commands, answered with wire messages.
import { BLOCK_PALETTE, LOOK, SPHERE_PALETTE } from '../vendor/three-avbd/src/app3d/look.ts';
import { createGpuSim3D, type GpuSim3D } from '../vendor/three-avbd/src/avbd3d/gpu/sim.ts';
import { PosePacker } from './pack.ts';
import { paramsFor } from './scenes.ts';
import { type Command, encodeMessage, MSG, SHAPE, STATIC_FLOATS, type Vec3 } from './wire.ts';

/** The demo's cannonball (app3d/main.ts:80-83, 559). */
const BALL = { radius: 0.7, mass: 43, friction: 0.5, speed: 45 };

/** three's TSL `hash` (PCG), as look.ts's blockColor runs it on the GPU: [0, 1). */
function pcg(seed: number): number {
  const state = (Math.imul(seed >>> 0, 747796405) + 2891336453) >>> 0;
  const word = Math.imul(((state >>> ((state >>> 28) + 4)) ^ state) >>> 0, 277803737) >>> 0;
  return (((word >>> 22) ^ word) >>> 0) / 2 ** 32;
}

const RINGS: Record<string, number> = { ringFlat: SHAPE.ringFlat, ringX: SHAPE.ringX, ringY: SHAPE.ringY, hidden: SHAPE.hidden };

export class Session {
  private readonly device: GPUDevice;
  private readonly write: (msg: Uint8Array) => void;
  private sim: GpuSim3D | null = null;
  private packer: PosePacker | null = null;
  private scene = '';
  private options: Record<string, number> = {};
  private staticsSent = 0;
  private warned = false;

  constructor(device: GPUDevice, write: (msg: Uint8Array) => void) {
    this.device = device;
    this.write = write;
  }

  async handle(cmd: Command): Promise<void> {
    switch (cmd.cmd) {
      case 'load':
        return this.load(cmd.scene, cmd.options as Record<string, number>);
      case 'reset':
        this.need();
        return this.load(this.scene, this.options);
      case 'step':
        return this.step();
      case 'pick': {
        const hit = this.need().pick(cmd.origin, unit(cmd.dir));
        this.write(encodeMessage(MSG.EVENT, { kind: 'pick', hit: hit && { body: hit.body, local: [...hit.local], t: hit.t } }));
        return;
      }
      case 'drag_start': {
        const sim = this.need();
        if (cmd.body < 0 || cmd.body >= sim.bodyCount || !sim.isDynamic(cmd.body)) throw new Error(`drag_start: no dynamic body ${cmd.body}`);
        return sim.startDrag(cmd.body, cmd.local, cmd.target);
      }
      case 'drag_move':
        return this.need().moveDrag(cmd.target);
      case 'drag_end':
        return this.need().endDrag();
      case 'cannonball':
        return this.need().addBall(BALL.radius, BALL.mass, BALL.friction, cmd.origin, unit(cmd.dir).map((x) => x * BALL.speed));
      case 'quit':
        return this.destroy();
    }
  }

  destroy(): void {
    this.sim?.destroy();
    this.packer?.destroy();
    this.sim = null;
    this.packer = null;
  }

  private need(): GpuSim3D {
    if (!this.sim) throw new Error('no scene loaded');
    return this.sim;
  }

  private load(name: string, options: Record<string, number>): void {
    const params = paramsFor(name, options); // throws on an unknown scene, before the old one goes
    this.destroy();
    const sim = createGpuSim3D(this.device, name, params, undefined, options);
    this.sim = sim;
    this.packer = new PosePacker(this.device, sim.solver.bodyBuffer, sim.solver.bodyCapacity);
    this.scene = name;
    this.options = options;
    const n = sim.bodyCount;
    this.staticsSent = n;
    const ropes = sim.ropes().map((r) => ({ links: r.links, color: r.color }));
    this.write(encodeMessage(MSG.SCENE, { name, bodyCount: n, ropes }, this.statics(0, n)));
  }

  private async step(): Promise<void> {
    const sim = this.need();
    const t0 = performance.now();
    sim.step();
    const n = sim.bodyCount;
    const poses = await this.packer!.read(n);
    const stepMs = performance.now() - t0;
    if (n > this.staticsSent) {
      this.write(encodeMessage(MSG.STATICS, { from: this.staticsSent, count: n - this.staticsSent }, this.statics(this.staticsSent, n)));
      this.staticsSent = n;
    }
    this.write(encodeMessage(MSG.FRAME, { step: sim.stepCount, bodyCount: n, stepMs, stats: sim.stats() }, poses));
  }

  /** Static records `sx sy sz shape r g b dynamic` for bodies from..to-1. */
  private statics(from: number, to: number): Float32Array {
    const sim = this.sim!;
    const out = new Float32Array((to - from) * STATIC_FLOATS);
    for (let i = from; i < to; i++) {
      const o = (i - from) * STATIC_FLOATS;
      const s = sim.size(i);
      const v = sim.visual(i);
      const dynamic = sim.isDynamic(i);
      const sphere = sim.isSphere(i);
      let shape: number = sphere ? SHAPE.sphere : SHAPE.box;
      if (v?.shape) {
        shape = RINGS[v.shape] ?? SHAPE.box;
        if (!(v.shape in RINGS) && !this.warned) {
          this.warned = true;
          console.error(`rubble: visual shape '${v.shape}' drawn as a box`);
        }
      }
      // gpu-bodies3d.ts: own paint, else the palette (dynamic) or LOOK.static
      let rgb: number[];
      if (v?.color !== undefined) rgb = hexRgb(v.color);
      else if (!dynamic) rgb = hexRgb(LOOK.static);
      else if (sphere) rgb = hexRgb(SPHERE_PALETTE[Math.floor(pcg(i) * SPHERE_PALETTE.length)]);
      else {
        const jitter = pcg(i + 7919) * 0.16 + 0.92;
        rgb = hexRgb(BLOCK_PALETTE[Math.floor(pcg(i) * BLOCK_PALETTE.length)]).map((c) => Math.min(1, c * jitter));
      }
      out.set([s[0], s[1], s[2], shape, rgb[0], rgb[1], rgb[2], dynamic ? 1 : 0], o);
    }
    return out;
  }
}

const hexRgb = (c: number): number[] => [((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255];

function unit(v: Vec3): Vec3 {
  const l = Math.hypot(v[0], v[1], v[2]);
  if (!(l > 0)) throw new Error('direction must be non-zero');
  return [v[0] / l, v[1] / l, v[2] / l];
}
