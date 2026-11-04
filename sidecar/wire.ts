// Framed binary protocol, sidecar stdout -> addon. See docs wire-protocol.
export const MSG = { EVENT: 1, SCENE: 2, STATICS: 3, FRAME: 4 } as const;
export const STATIC_FLOATS = 8;
export const POSE_FLOATS = 8;
export const SHAPE = { box: 0, sphere: 1, ringFlat: 2, ringX: 3, ringY: 4, hidden: 5 } as const;

export function encodeMessage(type: number, json: object, bin?: Float32Array): Uint8Array {
  const j = new TextEncoder().encode(JSON.stringify(json));
  const bl = bin ? bin.byteLength : 0;
  const out = new Uint8Array(16 + j.length + bl);
  out.set([0x52, 0x42, 0x4c, 0x31]); // "RBL1"
  const dv = new DataView(out.buffer);
  dv.setUint32(4, type, true);
  dv.setUint32(8, j.length, true);
  dv.setUint32(12, bl, true);
  out.set(j, 16);
  if (bin) out.set(new Uint8Array(bin.buffer, bin.byteOffset, bl), 16 + j.length);
  return out;
}

export type Vec3 = [number, number, number];
export type Command =
  | { cmd: 'load'; scene: string; options: Record<string, unknown> }
  | { cmd: 'step' }
  | { cmd: 'reset' }
  | { cmd: 'pick'; origin: Vec3; dir: Vec3 }
  | { cmd: 'drag_start'; body: number; local: Vec3; target: Vec3 }
  | { cmd: 'drag_move'; target: Vec3 }
  | { cmd: 'drag_end' }
  | { cmd: 'cannonball'; origin: Vec3; dir: Vec3 }
  | { cmd: 'quit' };

const bad = (why: string): never => { throw new Error(`bad command: ${why}`); };
const vec3 = (o: Record<string, unknown>, k: string): Vec3 => {
  const v = o[k];
  if (!Array.isArray(v) || v.length !== 3 || !v.every((x) => typeof x === 'number' && Number.isFinite(x))) bad(`${k} must be [x,y,z]`);
  return v as Vec3;
};

export function parseCommand(line: string): Command {
  let o: Record<string, unknown>;
  try { o = JSON.parse(line); } catch { return bad('invalid JSON'); }
  if (o === null || typeof o !== 'object') return bad('not an object');
  switch (o.cmd) {
    case 'load':
      if (typeof o.scene !== 'string') bad('load needs scene');
      if (o.options !== undefined && (o.options === null || typeof o.options !== 'object')) bad('load options');
      return { cmd: 'load', scene: o.scene as string, options: (o.options ?? {}) as Record<string, unknown> };
    case 'step': case 'reset': case 'drag_end': case 'quit':
      return { cmd: o.cmd };
    case 'pick': case 'cannonball':
      return { cmd: o.cmd, origin: vec3(o, 'origin'), dir: vec3(o, 'dir') };
    case 'drag_start':
      if (typeof o.body !== 'number' || !Number.isInteger(o.body)) bad('drag_start needs body');
      return { cmd: 'drag_start', body: o.body as number, local: vec3(o, 'local'), target: vec3(o, 'target') };
    case 'drag_move':
      return { cmd: 'drag_move', target: vec3(o, 'target') };
    default:
      return bad(`unknown cmd ${String(o.cmd)}`);
  }
}
