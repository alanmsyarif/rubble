# Rubble: three-avbd's GPU physics demo, live inside Blender 5.2

Date: 2026-11-04. Working name "Rubble" (the assistant's choice, not checked against the extensions site yet).

## 1. Intent

The user saw https://three-avbd.vercel.app, a browser demo of Augmented Vertex Block Descent (AVBD, Giles/Diaz/Yuksel,
SIGGRAPH 2025) running 100k+ rigid bodies on the GPU in real time, and wants that experience inside Blender:
pick a scene, press play, watch thousands of bricks and boxes stack, smash and break live in the 3D viewport, grab
bodies with the mouse, fire cannonballs.

v1 is the demo's own scenes. Simulating the user's own scene objects is explicitly a later version.

Why it is worth doing: no AVBD tool exists for Blender (VeeDynamics is VBD-only soft bodies; Blender's own node
physics is XPBD, and its Jolt rigid-body work is unreleased). The demo's code is MIT and already runs headless on
this machine, so the path is integration, not research.

## 2. Goals

1. Run these demo scenes live in the Blender viewport, behaving exactly as in the browser demo:
   Brick Ring (28k), Brick Ring (110k), Brick Walls (27k), Wall Smash (2k), Breakable Wall (600), Chain Mail (1.6k),
   Heavy Pendulum, Box Pile (4k), Box Pile (32k), Box Columns (100k). (Names as in three-avbd's scene registry.)
2. Demo-style interaction in the viewport: play / pause / single step / reset; left-drag grabs a body;
   Space fires a cannonball from the view; normal viewport navigation keeps working when not grabbing.
3. A sidebar (N-panel) tab: scene picker, scene size options where the scene has them, playback buttons,
   a readout of fps, solver ms per step, body count.
4. Speed targets on the user's RTX 5050 (acceptance numbers, measured in the GUI):
   - scenes up to about 30k bodies: 60 fps
   - Brick Ring (110k): 25 fps or better

## 3. Non-goals (v1)

- Simulating the user's own Blender objects.
- Rendering with Cycles or EEVEE, baking, or any keyframe or cache output. The live view is viewport-only.
- The remaining demo scenes: Ragdolls on Cloth, Flag in the Wind, Starry Night, Mona Lisa Tower, Plastic Beam,
  Jointed Drop, Custom, the small reference scenes, the 2D demo, the SDF pages.
- Drawing joint lines, labels, contact points, paintings or other demo decorations. Two drawing exceptions are
  in scope; see §5.3.
- Packaging as an installable extension zip or bundling a Node runtime. v1 runs from the repo checkout.
- macOS and Linux. Windows only.
- Changing three-avbd's solver behavior or parameters.

## 4. Anti-goals (would make it a failure even if it runs)

- Physics that behave differently from the browser demo for the same scene. Rubble is a viewer for three-avbd,
  not a reimplementation of it.
- Blender crashing, freezing, or leaving an orphaned solver process after the user stops, reloads the addon,
  opens another file, or quits Blender.
- Slideshow performance on the small scenes: if Wall Smash isn't smooth, v1 has failed.

## 5. Architecture (decided)

Two processes.

```
Blender (Python addon)                         Node 24 sidecar (TypeScript, unchanged three-avbd inside)
  N-panel, modal operator  ── commands ──────▶  stdin  (newline-delimited JSON)
  reader thread            ◀── frames/events ─  stdout (binary framed messages)
  viewport draw handler                         stderr (log text only; Blender logs it)
```

### 5.1 Sidecar (Node)

- three-avbd is vendored at commit `afc1442e64e4b36f2d49be70bf35ea0c9b85cf6c` (2026-11-02), MIT, with its
  LICENSE and THIRD_PARTY_NOTICES kept. Vendored source is never edited. Anything Rubble needs lives in its
  own sidecar files that import from the vendored tree.
- Runs as `node --experimental-transform-types --no-warnings sidecar/main.ts`, the same way three-avbd runs its
  own GPU tests and benchmarks. WebGPU comes from Dawn via the `webgpu@0.6.1` npm package, installed with
  `npm install --ignore-scripts`. Device setup copies three-avbd's `tests-gpu/device.ts`: request the adapter's
  max storage-buffer limits and keep the GPU, adapter and device objects reachable for the process lifetime.
  The file documents a SIGSEGV if they are collected.
- Scenes are built with three-avbd's own `createGpuSim3D(device, sceneName, params, …)`. Parameters are built
  the way the demo app's `defaults()` builds them: `gpuParams3D()` merged with the scene's own `params`
  (e.g. Brick Ring runs at 4 iterations) and `up: REF_UP`. The sidecar reproduces that merge rather than
  calling `gpuParams3D()` alone.
- Scene options: none of the v1 scenes has a size option. The only options are weld strength, ball density and
  mass ratio, and the panel exposes them with the demo's choices.
- Pose output: three-avbd's body buffer is 40 floats per body (`BODY_FLOATS`), with position at float 0
  (`B_POS`), quaternion x,y,z,w at float 4 (`B_ROT`) and size at float 16 (`B_SIZE`). Reading it whole is
  17.6 MB per frame at 110k, too much. The sidecar adds its own small compute pass that packs each body's
  position and quaternion into a compact buffer of 8 floats (32 bytes) per body, then reads that buffer back
  (3.5 MB at 110k).
- Static per-body data (size, sphere or box, color from the scene's visual, dynamic or static) is sent once
  per scene load, not per frame.

### 5.2 Protocol

- **Commands** (Blender to sidecar), one JSON object per line on stdin:
  - `load {scene, options}`
  - `step` (advance one 1/60 s step and send a pose frame)
  - `reset`
  - `pick {origin, dir}`, which replies with the hit body or none
  - `drag_start {body, local, target}`, `drag_move {target}`, `drag_end`
  - `cannonball {origin, dir}`, using the demo's defaults for radius, mass and speed
  - `quit`
- **Messages** (sidecar to Blender) on stdout. Each has a fixed binary header (magic, type, payload length).
  Types:
  - `scene` (JSON metadata + static per-body arrays)
  - `frame` (step number, stats JSON, float32 poses)
  - `event` (JSON: pick result, errors, ready)
- Nothing but framed messages may ever be written to stdout. All logging goes to stderr.
- Pacing is lockstep with one step in flight. Blender sends `step`, draws the latest frame it has, and sends the
  next `step` as soon as a frame arrives, so the solver runs while Blender draws. When Blender is slower than
  60 fps the simulation runs in slow motion rather than skipping steps, as the demo does.

### 5.3 Blender addon (Python)

- **Process manager:** starts and stops the sidecar.
  - A reader thread parses messages and keeps only the newest frame. Older unread frames are dropped.
  - The main thread never blocks on the pipe.
  - The sidecar is killed on addon unregister, on `load_pre`, and at exit. If a polite `quit` gets no answer
    within a short timeout, the process is terminated.
- **Viewport draw:** a `SpaceView3D` POST_VIEW draw handler.
  - It draws boxes and spheres with `GPUBatch.draw_instanced`, one batch per shape.
  - Per-instance pose comes from an RGBA32F texture (2 texels per body: position, quaternion), read in the
    vertex shader with `texelFetch` and `gl_InstanceID`.
  - Static data (size, color) lives in a second texture uploaded once per scene.
  - The pose texture is recreated each frame from `gpu.types.Buffer("FLOAT", n, ndarray)`; see §7.
  - Lambert-style shading with depth test.
  - **The scene's own visuals are honored (user decision, 2026-11-04):**
    - Bodies marked `hidden` in three-avbd's `visuals.ts` are not drawn.
    - Chain Mail links are drawn as rings (tori), matching the demo's `ringFlat` / `ringX` / `ringY` visuals.
      This means a third instanced batch, and the static per-body data carries a shape enum (box, sphere,
      ring variant) instead of a sphere flag.
    - Heavy Pendulum's hidden links are drawn as a rope: a line strip through the link positions that
      three-avbd's `ropes()` view lists.
- **Modal operator** (live mode) handles:
  - a timer that drives steps and redraws
  - left-drag grab, through the `pick` and `drag_*` commands, with a ray from the view
  - Space for a cannonball, P to pause, `.` to single-step, R to reset, Esc to stop
  - pass-through of all other events, so viewport navigation works
- **N-panel tab "Rubble":** scene enum, scene options, Start/Stop live mode, Play/Pause/Step/Reset, stats
  readout, and the path to the Node executable as an addon preference (default `node` on PATH).
- GPU objects (shaders, batches, textures) are held on instances, never in module-level globals; see §7.
- Coordinates: three-avbd's 3D demo is z-up in metres, the same as Blender. Bodies are drawn in world space,
  and no Blender objects are created for them.

## 6. Constraints

- Blender 5.2.0 LTS on Windows 11, RTX 5050, Node 24.19.0 via nvm-windows at `C:\nvm4w\nodejs`.
- No wgpu or any other GPU binding inside Blender's own process (see §7).
- Blender's bundled Python and numpy only (numpy 2.3.4). No pip installs into Blender.
- Vendored three-avbd stays unmodified, so it can be updated by replacing the folder.

## 7. Measured facts the design rests on (2026-11-04, this machine)

- **three-avbd runs headless via Dawn on the RTX 5050** (Dawn chose Direct3D 12).
  - Brick ring 110k (4 iterations): 14.0 ms per step wall time (GPU 13.6, of which collision 4.8 and solve 7.9).
  - Brick ring 9k: 1.5 ms. Wall smash 2k: 1.7 ms GPU.
- **Running wgpu inside GUI Blender on its default OpenGL backend crashes** with EXCEPTION_ACCESS_VIOLATION at
  address 0, at a different site each run. It worked only with `--gpu-backend vulkan`. The sidecar keeps every
  GPU binding out of Blender's process, which is why §6 forbids them.
- **Viewport display cost, 110k / 262k / 512k bodies:**
  - Geometry-nodes instancing with per-frame attribute updates: about 20 / 7 / 5 fps. Rejected.
  - A gpu-module instanced draw handler fed by a texture: **68 / 61 / 46 fps**. Chosen.
  - Copying back from the GPU and uploading the texture took about 2 ms each at 110k.
  - Only the instanced draw was measured on the Vulkan backend. Its speed on Blender's default OpenGL backend is
    not yet measured; see §9.
- `gpu.types.Buffer("FLOAT", n, ndarray)` costs about 0.01 ms; built from a Python list it costs 26 ms.
- Blender crashes at shutdown if GPU objects sit in module-level globals (measured in an earlier project).
- A GPUTexture can silently lose its contents (measured in an earlier project). Here that would only corrupt one
  displayed frame, since the texture is rebuilt each frame, and is accepted.

## 8. Left to the builder

- File layout, module names, the exact binary header format, and the JSON field names.
- How static per-body data is encoded, and the shading details.
- How the sidecar's npm dependencies are installed for development (a script or a documented command).
- Timer interval and how frames are scheduled within the lockstep rule in §5.2.
- Test structure, following the user's existing pattern (headless pytest-style plus a Blender
  `-b --python` runner).

## 9. Risks to check first in the plan

1. **Pipe throughput.** Not yet measured: whether 3.5 MB per frame through a Windows pipe is read fast enough.
   If it isn't, fall back to a memory-mapped file shared by both processes.
2. **Draw speed on Blender's default OpenGL backend.** The 68 fps figure was measured on Vulkan. Measure the
   draw handler on default Blender before building on it. *Assistant's call:* if OpenGL misses the §2 targets,
   v1 requires Blender's Vulkan backend (Preferences → System → Backend, or `--gpu-backend vulkan`). The addon
   detects the backend and shows that hint. No separate draw-optimisation track is planned for v1.
3. **Shape coverage — resolved by the builder check.** Every v1 scene's physics uses only boxes and spheres,
   with no convex hulls.

## 9a. How "behaves like the demo" is checked (assistant's call)

The scenes are not bit-deterministic. `GpuSim3D` adapts capacity when async readbacks land, so contact overflow
depends on thread timing, and bitwise comparison is impossible even between two runs. The bar is:

- the same code path: the same `createGpuSim3D` call with the demo's merged parameters, verified by review
- a cheap automated sanity check per scene in the sidecar's tests: load, step N, every pose finite, body count as
  expected, nothing fallen below the floor
- a side-by-side look by the user against the browser demo

There is no numeric tolerance harness in v1.

## 10. Credits

AVBD: Chris Giles, Elie Diaz, Cem Yuksel (SIGGRAPH 2025). three-avbd: Steven Bobyn (MIT), including ports of
avbd-demo3d / avbd-demo2d by Chris Giles (MIT). Dawn via the `webgpu` npm package.
