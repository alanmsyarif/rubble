// Sidecar entry: commands on stdin (one JSON per line), framed messages on stdout, text on stderr.
import { createInterface } from 'node:readline';
import { format } from 'node:util';

// Before anything else loads: stdout carries messages only (imports below are dynamic, as static
// ones would be hoisted above this).
const toStderr = (...a: unknown[]) => void process.stderr.write(format(...a) + '\n');
console.log = console.info = console.debug = console.warn = toStderr;

const { createDevice } = await import('./device.ts');
const { encodeMessage, MSG, parseCommand } = await import('./wire.ts');
const { Session } = await import('./session.ts');

const write = (msg: Uint8Array) => void process.stdout.write(msg);
const error = (e: unknown) => {
  console.error(e);
  write(encodeMessage(MSG.EVENT, { kind: 'error', message: e instanceof Error ? e.message : String(e) }));
};
// A failure inside the vendored sim's async readback must not kill the sidecar
process.on('unhandledRejection', error);

const device = await createDevice();
// A real startup log through console.log: main.test's byte-exact stdout decode proves the redirect
console.log(`rubble sidecar: WebGPU device ready (max storage binding ${device.limits.maxStorageBufferBindingSize} bytes)`);
const session = new Session(device, write);
write(encodeMessage(MSG.EVENT, { kind: 'ready' }));

for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
  if (!line.trim()) continue;
  try {
    const cmd = parseCommand(line);
    await session.handle(cmd);
    if (cmd.cmd === 'quit') break;
  } catch (e) {
    error(e);
  }
}
session.destroy();
// Exit once stdout has flushed (Dawn would keep the process alive)
process.stdout.write('', () => process.exit(0));
