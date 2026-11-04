import test from 'node:test';
import assert from 'node:assert/strict';
import { encodeMessage, parseCommand, MSG } from '../wire.ts';

test('encodeMessage header', () => {
  const out = encodeMessage(MSG.FRAME, { step: 1 }, new Float32Array([1, 2]));
  const dv = new DataView(out.buffer, out.byteOffset, out.byteLength);
  assert.equal(new TextDecoder().decode(out.subarray(0, 4)), 'RBL1');
  assert.equal(dv.getUint32(4, true), 4);
  const jl = JSON.stringify({ step: 1 }).length;
  assert.equal(dv.getUint32(8, true), jl);
  assert.equal(dv.getUint32(12, true), 8);
  assert.equal(out.length, 16 + jl + 8);
});

test('parseCommand pick', () => {
  assert.deepEqual(parseCommand('{"cmd":"pick","origin":[0,0,0],"dir":[0,0,-1]}'), {
    cmd: 'pick', origin: [0, 0, 0], dir: [0, 0, -1],
  });
});

test('parseCommand rejects bad input', () => {
  assert.throws(() => parseCommand('{"cmd":"fly"}'), /bad command/);
  assert.throws(() => parseCommand('{"cmd":"pick","origin":[0,0,0]}'), /bad command/);
  assert.throws(() => parseCommand('nope'), /bad command/);
});
