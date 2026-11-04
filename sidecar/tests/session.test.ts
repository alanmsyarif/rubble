import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createDevice } from '../device.ts';
import { MSG, SHAPE, STATIC_FLOATS, POSE_FLOATS, type Command } from '../wire.ts';
import { V1_SCENES, paramsFor } from '../scenes.ts';
import { PosePacker } from '../pack.ts';
import { Session } from '../session.ts';
import { decode, type Msg } from './decode.ts';
import { createGpuSim3D } from '../../vendor/three-avbd/src/avbd3d/gpu/sim.ts';
import { BODY_FLOATS, B_POS, B_ROT } from '../../vendor/three-avbd/src/avbd3d/gpu/layout.ts';

const device = await createDevice();
const T = { timeout: 120_000 };

function capture() {
  const msgs: Msg[] = [];
  const session = new Session(device, (m) => msgs.push(...decode(m).msgs));
  const run = async (cmd: Command) => {
    const from = msgs.length;
    await session.handle(cmd);
    return msgs.slice(from);
  };
  return { msgs, session, run };
}

const load = (scene: string): Command => ({ cmd: 'load', scene, options: {} });
const step: Command = { cmd: 'step' };

test('V1_SCENES are the ten v1 scenes', () => {
  assert.deepEqual(V1_SCENES, ['Brick Ring (28k)', 'Brick Ring (110k)', 'Brick Walls (27k)', 'Wall Smash (2k)', 'Breakable Wall (600)',
    'Chain Mail (1.6k)', 'Heavy Pendulum', 'Box Pile (4k)', 'Box Pile (32k)', 'Box Columns (100k)']);
});

test('paramsFor is the demo defaults() merge', () => {
  const p = paramsFor('Brick Ring (110k)');
  assert.deepEqual(p.up, [0, 0, 1]);
  assert.equal(p.matchNearest, true);
  assert.equal(p.faceBias, true);
});

for (const name of V1_SCENES) {
  test(`${name}: load and 30 steps`, T, async () => {
    const { session, run } = capture();
    const [scene] = await run(load(name));
    assert.equal(scene.type, MSG.SCENE);
    const n = scene.json.bodyCount;
    assert.ok(n > 0);
    assert.equal(scene.json.name, name);
    assert.equal(scene.bin.byteLength, n * STATIC_FLOATS * 4);
    const dynamic = (i: number) => scene.bin[i * STATIC_FLOATS + 7] === 1;
    const times: number[] = [];
    for (let s = 0; s < 30; s++) {
      const out = await run(step);
      const frame = out[out.length - 1];
      assert.equal(frame.type, MSG.FRAME);
      assert.equal(frame.json.step, s + 1);
      const m = frame.json.bodyCount;
      assert.equal(frame.bin.length, m * POSE_FLOATS);
      for (let i = 0; i < frame.bin.length; i++) assert.ok(Number.isFinite(frame.bin[i]), `pose ${i} finite`);
      for (let i = 0; i < Math.min(n, m); i++) if (dynamic(i)) assert.ok(frame.bin[i * POSE_FLOATS + 2] >= -1, `body ${i} below floor`);
      times.push(frame.json.stepMs);
    }
    times.sort((a, b) => a - b);
    console.error(`${name}: ${n} bodies, median stepMs ${times[15].toFixed(2)}`);
    await session.handle({ cmd: 'quit' });
  });
}

test('PosePacker matches the body buffer', T, async () => {
  const sim = createGpuSim3D(device, 'Wall Smash (2k)', paramsFor('Wall Smash (2k)'));
  const packer = new PosePacker(device, sim.solver.bodyBuffer, sim.solver.bodyCapacity);
  for (let s = 0; s < 5; s++) sim.step();
  const n = sim.bodyCount;
  const packed = await packer.read(n);
  const full = await sim.solver.readBodies();
  assert.equal(packed.length, n * 8);
  for (let i = 0; i < n; i++) {
    for (let k = 0; k < 3; k++) assert.equal(packed[i * 8 + k], full[i * BODY_FLOATS + B_POS + k]);
    assert.equal(packed[i * 8 + 3], 0);
    for (let k = 0; k < 4; k++) assert.equal(packed[i * 8 + 4 + k], full[i * BODY_FLOATS + B_ROT + k]);
  }
  packer.destroy();
  sim.destroy();
});

test('Heavy Pendulum rope links are hidden', T, async () => {
  const { session, run } = capture();
  const [scene] = await run(load('Heavy Pendulum'));
  const links: number[] = scene.json.ropes[0].links;
  assert.equal(links.length, 50);
  assert.equal(typeof scene.json.ropes[0].color, 'number');
  for (const i of links) assert.equal(scene.bin[i * STATIC_FLOATS + 3], SHAPE.hidden);
  await session.handle({ cmd: 'quit' });
});

test('Chain Mail statics have rings and hidden bodies', T, async () => {
  const { session, run } = capture();
  const [scene] = await run(load('Chain Mail (1.6k)'));
  const shapes = new Set<number>();
  for (let i = 0; i < scene.json.bodyCount; i++) shapes.add(scene.bin[i * STATIC_FLOATS + 3]);
  assert.ok(shapes.has(SHAPE.ringFlat) || shapes.has(SHAPE.ringX) || shapes.has(SHAPE.ringY));
  assert.ok(shapes.has(SHAPE.hidden));
  await session.handle({ cmd: 'quit' });
});

test('cannonball emits STATICS before the next FRAME', T, async () => {
  const { session, run } = capture();
  const [scene] = await run(load('Wall Smash (2k)'));
  const n = scene.json.bodyCount;
  assert.deepEqual(await run({ cmd: 'cannonball', origin: [0, -20, 5], dir: [0, 1, 0] }), []);
  const [statics, frame] = await run(step);
  assert.equal(statics.type, MSG.STATICS);
  assert.deepEqual(statics.json, { from: n, count: 1 });
  assert.equal(statics.bin.length, STATIC_FLOATS);
  assert.equal(statics.bin[3], SHAPE.sphere);
  assert.equal(statics.bin[7], 1);
  assert.deepEqual([...statics.bin.subarray(4, 7)], [0x3a / 255, 0x3d / 255, 0x42 / 255].map(Math.fround)); // CANNONBALL
  const floor = [...Array(n).keys()].find((i) => scene.bin[i * 8 + 7] === 0)!;
  assert.deepEqual([...scene.bin.subarray(floor * 8 + 4, floor * 8 + 7)], [0x9a / 255, 0xa0 / 255, 0xa6 / 255].map(Math.fround)); // LOOK.static
  assert.equal(frame.type, MSG.FRAME);
  assert.equal(frame.json.bodyCount, n + 1);
  // The ball flies +y at 45 m/s from where it was shot
  assert.ok(Math.abs(frame.bin[n * 8] - 0) < 0.5 && frame.bin[n * 8 + 1] > -20);
  assert.equal((await run(step)).length, 1); // nothing new: FRAME only
  await session.handle({ cmd: 'quit' });
});

test('pick, drag and reset on Box Pile', T, async () => {
  const { session, run } = capture();
  const [scene] = await run(load('Box Pile (4k)'));
  for (let s = 0; s < 15; s++) await run(step);
  const [hit] = await run({ cmd: 'pick', origin: [0.3, 0.2, 100], dir: [0, 0, -1] });
  assert.equal(hit.type, MSG.EVENT);
  assert.equal(hit.json.kind, 'pick');
  assert.ok(hit.json.hit, 'straight down hits the pile');
  const { body, local, t } = hit.json.hit;
  assert.ok(Number.isInteger(body) && local.length === 3 && t > 0);
  const [sky] = await run({ cmd: 'pick', origin: [0, 0, 100], dir: [0, 0, 1] });
  assert.deepEqual(sky.json, { kind: 'pick', hit: null });

  await run({ cmd: 'drag_start', body, local, target: [0.3, 0.2, 100 - t + 1] });
  await run(step);
  await run({ cmd: 'drag_move', target: [0.3, 0.2, 100 - t + 2] });
  await run(step);
  await run({ cmd: 'drag_end' });
  await run(step);
  await assert.rejects(session.handle({ cmd: 'drag_start', body: 1e9, local: [0, 0, 0], target: [0, 0, 0] }));

  const [again] = await run({ cmd: 'reset' });
  assert.equal(again.type, MSG.SCENE);
  assert.equal(again.json.bodyCount, scene.json.bodyCount);
  const [frame] = await run(step);
  assert.equal(frame.json.step, 1);
  await session.handle({ cmd: 'quit' });
});

test('commands before load fail', async () => {
  const { session } = capture();
  await assert.rejects(session.handle(step), /no scene/);
  await assert.rejects(session.handle(load('Nope')), /unknown scene/);
});
