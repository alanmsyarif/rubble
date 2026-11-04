// Packs each body's pose (px py pz 0 qx qy qz qw) out of the 40-float body buffer and reads it back.
import { B_POS, B_ROT, BODY_FLOATS } from '../vendor/three-avbd/src/avbd3d/gpu/layout.ts';
import { POSE_FLOATS } from './wire.ts';

const WGSL = /* wgsl */ `
@group(0) @binding(0) var<storage, read> bodies: array<f32>;
@group(0) @binding(1) var<storage, read_write> poses: array<f32>;
@group(0) @binding(2) var<uniform> count: u32;
@compute @workgroup_size(64) fn main(@builtin(global_invocation_id) g: vec3u) {
  let i = g.x;
  if (i >= count) { return; }
  let s = i * ${BODY_FLOATS}u;
  let d = i * ${POSE_FLOATS}u;
  poses[d] = bodies[s + ${B_POS}u];
  poses[d + 1u] = bodies[s + ${B_POS + 1}u];
  poses[d + 2u] = bodies[s + ${B_POS + 2}u];
  poses[d + 3u] = 0.0;
  poses[d + 4u] = bodies[s + ${B_ROT}u];
  poses[d + 5u] = bodies[s + ${B_ROT + 1}u];
  poses[d + 6u] = bodies[s + ${B_ROT + 2}u];
  poses[d + 7u] = bodies[s + ${B_ROT + 3}u];
}`;

export class PosePacker {
  private readonly device: GPUDevice;
  private readonly poses: GPUBuffer;
  private readonly staging: GPUBuffer;
  private readonly count: GPUBuffer;
  private readonly pipeline: GPUComputePipeline;
  private readonly group: GPUBindGroup;
  private readonly capacity: number;

  /** `capacity`: bodies the body buffer can hold (the solver's bodyCapacity, room for cannonballs). */
  constructor(device: GPUDevice, bodyBuffer: GPUBuffer, capacity: number) {
    this.device = device;
    this.capacity = capacity;
    const size = Math.max(capacity, 1) * POSE_FLOATS * 4;
    this.poses = device.createBuffer({ label: 'rubble poses', size, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC });
    this.staging = device.createBuffer({ label: 'rubble poses staging', size, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST });
    this.count = device.createBuffer({ label: 'rubble pose count', size: 16, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    this.pipeline = device.createComputePipeline({ layout: 'auto', compute: { module: device.createShaderModule({ code: WGSL }), entryPoint: 'main' } });
    this.group = device.createBindGroup({
      layout: this.pipeline.getBindGroupLayout(0),
      entries: [
        { binding: 0, resource: { buffer: bodyBuffer, size: capacity * BODY_FLOATS * 4 } },
        { binding: 1, resource: { buffer: this.poses } },
        { binding: 2, resource: { buffer: this.count } },
      ],
    });
  }

  /** Poses of bodies 0..count-1, after all GPU work submitted so far. Not reentrant. */
  async read(count: number): Promise<Float32Array> {
    if (count > this.capacity) throw new Error(`PosePacker: ${count} bodies over capacity ${this.capacity}`);
    if (count === 0) return new Float32Array(0);
    const bytes = count * POSE_FLOATS * 4;
    this.device.queue.writeBuffer(this.count, 0, new Uint32Array([count]));
    const enc = this.device.createCommandEncoder();
    const pass = enc.beginComputePass();
    pass.setPipeline(this.pipeline);
    pass.setBindGroup(0, this.group);
    pass.dispatchWorkgroups(Math.ceil(count / 64));
    pass.end();
    enc.copyBufferToBuffer(this.poses, 0, this.staging, 0, bytes);
    this.device.queue.submit([enc.finish()]);
    await this.staging.mapAsync(GPUMapMode.READ, 0, bytes);
    const out = new Float32Array(this.staging.getMappedRange(0, bytes).slice(0));
    this.staging.unmap();
    return out;
  }

  destroy(): void {
    this.poses.destroy();
    this.staging.destroy();
    this.count.destroy();
  }
}
