// Test helper: split a byte stream into wire messages (throws on a bad header).
export interface Msg { type: number; json: any; bin: Float32Array }

export function decode(buf: Uint8Array): { msgs: Msg[]; rest: Uint8Array } {
  const msgs: Msg[] = [];
  let o = 0;
  while (buf.length - o >= 16) {
    if (new TextDecoder().decode(buf.subarray(o, o + 4)) !== 'RBL1') throw new Error(`bad magic at ${o}`);
    const dv = new DataView(buf.buffer, buf.byteOffset + o, 16);
    const [type, jl, bl] = [dv.getUint32(4, true), dv.getUint32(8, true), dv.getUint32(12, true)];
    if (buf.length - o < 16 + jl + bl) break;
    const json = JSON.parse(new TextDecoder().decode(buf.subarray(o + 16, o + 16 + jl)));
    const bin = new Float32Array(buf.slice(o + 16 + jl, o + 16 + jl + bl).buffer);
    msgs.push({ type, json, bin });
    o += 16 + jl + bl;
  }
  return { msgs, rest: buf.subarray(o) };
}
