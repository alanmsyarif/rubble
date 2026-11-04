import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createDevice } from '../device.ts';

test('device limits and compute readback', async () => {
  const device = await createDevice();
  assert.ok(device.limits.maxStorageBuffersPerShaderStage >= 9);
  const buf = device.createBuffer({ size: 4, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC });
  const out = device.createBuffer({ size: 4, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
  const module = device.createShaderModule({
    code: `@group(0) @binding(0) var<storage, read_write> b: array<u32>;
@compute @workgroup_size(1) fn main() { b[0] = 42u; }`,
  });
  const pipeline = device.createComputePipeline({ layout: 'auto', compute: { module, entryPoint: 'main' } });
  const bg = device.createBindGroup({ layout: pipeline.getBindGroupLayout(0), entries: [{ binding: 0, resource: { buffer: buf } }] });
  const enc = device.createCommandEncoder();
  const pass = enc.beginComputePass();
  pass.setPipeline(pipeline);
  pass.setBindGroup(0, bg);
  pass.dispatchWorkgroups(1);
  pass.end();
  enc.copyBufferToBuffer(buf, 0, out, 0, 4);
  device.queue.submit([enc.finish()]);
  await out.mapAsync(GPUMapMode.READ);
  assert.equal(new Uint32Array(out.getMappedRange())[0], 42);
  out.unmap();
});
