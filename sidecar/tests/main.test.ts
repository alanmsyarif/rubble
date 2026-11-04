import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { MSG } from '../wire.ts';
import { decode, type Msg } from './decode.ts';

const main = fileURLToPath(new URL('../main.ts', import.meta.url));

test('main: ready, errors, load/step/quit, stdout is messages only', { timeout: 120_000 }, async () => {
  const child = spawn(process.execPath, ['--experimental-transform-types', '--no-warnings', main], { stdio: ['pipe', 'pipe', 'inherit'] });
  let buf = new Uint8Array(0);
  const msgs: Msg[] = [];
  let wake = () => {};
  child.stdout.on('data', (d: Buffer) => {
    const all = new Uint8Array(buf.length + d.length);
    all.set(buf);
    all.set(d, buf.length);
    const r = decode(all); // throws on any stray (non-message) byte
    msgs.push(...r.msgs);
    buf = r.rest.slice();
    wake();
  });
  let dead = false;
  child.on('exit', () => ((dead = true), wake()));
  const next = async (): Promise<Msg> => {
    while (!msgs.length) {
      if (dead) throw new Error('sidecar exited');
      await new Promise<void>((r) => (wake = r));
    }
    return msgs.shift()!;
  };
  const send = (o: object | string) => child.stdin.write((typeof o === 'string' ? o : JSON.stringify(o)) + '\n');
  const exited = once(child, 'exit');

  const ready = await next();
  assert.equal(ready.type, MSG.EVENT);
  assert.deepEqual(ready.json, { kind: 'ready' });

  send({ cmd: 'fly' });
  const err = await next();
  assert.equal(err.json.kind, 'error');
  assert.match(err.json.message, /bad command/);
  send({ cmd: 'step' }); // no scene yet: an error, not death
  assert.equal((await next()).json.kind, 'error');

  send({ cmd: 'load', scene: 'Wall Smash (2k)', options: {} });
  assert.equal((await next()).type, MSG.SCENE);
  send({ cmd: 'step' });
  const frame = await next();
  assert.equal(frame.type, MSG.FRAME);
  assert.equal(frame.json.step, 1);

  const t0 = Date.now();
  send({ cmd: 'quit' });
  const [code] = await exited;
  assert.equal(code, 0);
  assert.ok(Date.now() - t0 < 5000, 'exits within 5 s');
  assert.equal(buf.length, 0, 'no partial bytes on stdout');
  assert.equal(msgs.length, 0);
});

test('main: stdin EOF exits 0', { timeout: 60_000 }, async () => {
  const child = spawn(process.execPath, ['--experimental-transform-types', '--no-warnings', main], { stdio: ['pipe', 'pipe', 'inherit'] });
  child.stdout.once('data', () => child.stdin.end());
  const [code] = await once(child, 'exit');
  assert.equal(code, 0);
});
