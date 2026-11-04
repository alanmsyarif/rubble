// Dawn WebGPU device for the sidecar (approach copied from three-avbd tests-gpu/device.ts).
import { create, globals } from 'webgpu';

Object.assign(globalThis, globals);

// gpu/adapter/device must stay reachable for the process lifetime, else Dawn's async runner
// polls freed memory (SIGSEGV).
const keepAlive: unknown[] = [];
(globalThis as { __dawn?: unknown }).__dawn = keepAlive;

export async function createDevice(): Promise<GPUDevice> {
  const gpu = create([]);
  const adapter = await gpu.requestAdapter();
  if (!adapter) throw new Error('no WebGPU adapter available');
  const requiredFeatures = (['timestamp-query'] as GPUFeatureName[]).filter((f) => adapter.features.has(f));
  const requiredLimits = {
    maxStorageBufferBindingSize: adapter.limits.maxStorageBufferBindingSize,
    maxBufferSize: adapter.limits.maxBufferSize,
    maxStorageBuffersPerShaderStage: adapter.limits.maxStorageBuffersPerShaderStage,
  };
  const device = await adapter.requestDevice({ requiredFeatures, requiredLimits });
  keepAlive.push(gpu, adapter, device);
  device.onuncapturederror = (e) => console.error(e.error.message);
  return device;
}
