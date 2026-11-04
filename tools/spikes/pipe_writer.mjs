// Spike: 300 messages of 16-byte header + 3,535,872 payload bytes, respecting backpressure.
import { once } from 'node:events';
const N = 300, PAY = 3535872;
const payload = Buffer.alloc(PAY, 7);
const head = Buffer.alloc(16);
for (let i = 0; i < N; i++) {
  head.writeUInt32LE(i, 0); head.writeUInt32LE(PAY, 4);
  const msg = Buffer.concat([head, payload]);
  if (!process.stdout.write(msg)) await once(process.stdout, 'drain');
}
