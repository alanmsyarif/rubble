# Rubble v2 — simulate your own Blender objects

Date: 2026-11-04. Builds on v1 (branch `feat/v1`, spec `2026-11-04-rubble-design.md`); v2 work on branch `feat/v2`.

## 1. Intent

v1 plays three-avbd's built-in demo scenes. v2 lets the user simulate **any of their own objects** with the same
AVBD GPU solver: mark objects, press Start, watch them fall, stack, smash and break live; then bake the result to
keyframes so Cycles/EEVEE render it. The user said "anything" — no specific shot — so v2 aims for general-purpose
rigid-body use: props falling and stacking, walls smashed, objects that break apart, things pushed by animated
objects.

## 2. Goals

1. **Mark objects** in a new "Rubble" panel in Object Properties (per object):
   - **Type:** Dynamic (simulated) · Static (fixed collider) · Animated (keyframed motion drives a kinematic collider
     that pushes dynamic bodies). Unmarked objects are ignored.
   - **Shape:** Auto · Box · Sphere · Convex Hull · Convex Parts.
     - Auto: Box if the mesh is close to its oriented bounding box, Sphere if close to a sphere, else Convex Hull.
     - Convex Parts: **each loose part of the mesh becomes one convex hull**; the parts are welded with fixed joints
       and do not collide with each other. Optional **Break Force** (none = never breaks) turns the welds breakable,
       so the object fractures along its parts on impact. Decomposition is done by the user (manually or with any
       decomposition addon); Rubble does not decompose meshes in v2.
   - **Density** (kg/m³) and **Friction**.
2. **Live mode** ("Start (own objects)" in the Rubble sidebar tab):
   - All marked objects are sent to the sidecar and simulated; **the real Blender objects move** in the viewport
     every frame (their transforms are driven by the simulation).
   - Animated objects follow their keyframed motion as the timeline plays (each sim step samples the scene frame
     matching sim time), pushing dynamic bodies.
   - v1 controls keep working: left-drag grab, Space cannonball, P play/pause, `.` single step, R reset, Esc stop.
   - **R / Stop restores every object's original transform** (the user's scene is never left modified by a live run).
3. **Bake:** a "Bake" button simulates a frame range (default: scene start–end) and writes **keyframes** (location +
   rotation) on every Dynamic object, so the timeline scrubs and Cycles/EEVEE render it. "Clear Bake" removes them
   and restores the original transforms. Baking runs as fast as the solver allows, not at 60 fps.
4. Speed target: up to ~2,000 marked objects live at ≥30 fps on the user's RTX 5050 (the real-object update is the
   expected bottleneck, not the solver).

## 3. Non-goals (v2)

- Automatic convex decomposition (a later "Decompose" button can feed the same Convex Parts path).
- Concave/SDF collision (three-avbd's SDF path is experimental).
- Blender rigid-body constraints → AVBD joints (planned v2.1), springs, motors.
- Cloth, soft bodies; Blender's own Rigid Body World (Rubble is separate from it).
- Mixing demo scenes with own objects in one run.
- More than ~2,000 objects live via real-object transforms (the v1 instanced preview path for huge counts is later).
- Packaging as a shareable zip (v1's folder-link install continues to apply).
- Scale and shear on simulated objects beyond what is baked into the collision shape at Start (see §5.3).

## 4. Anti-goals

- Damaging the user's scene: a live run or failed bake must never leave objects moved, keyframes half-written, or
  mesh data modified. Bake writes keyframes only on Dynamic objects and only when the user presses Bake.
- Everything v1's anti-goals said: no crash, no freeze, no orphaned sidecar after stop / new file / quit.
- Collision shapes that visibly disagree with the object (e.g. a box shape on a mug) under Auto: Auto must fall back
  to Convex Hull when unsure.

## 5. Architecture (decided)

### 5.1 Same two processes as v1
The v1 sidecar and wire protocol stay. Demo scenes keep their v1 path unchanged. Own-object runs use three-avbd's
**public library API** (`vendor/three-avbd/src/lib/world.ts`: `World.create({device, maxBodies, gravity, dt,
iterations})`, `addBox` / `addSphere` / `addHull`, `addJoint({type:'fixed', breakForce})`, `Body.moveTo` for
kinematic bodies, `setCollisionGroups`, `raycast`, `onBreak`) instead of the demo's `createGpuSim3D`, which only builds
registry scenes. Vendored code stays unedited.

- Gravity `[0, 0, -9.81]` (Blender is z-up; the World default is y-up). dt 1/60. Iterations: the World default unless
  testing shows welds need more (record the measurement).
- Hull limits from three-avbd: at most 32 vertices, 255 faces, 255 edges per hull (`hull.ts:51`, `shapes.ts:60`);
  larger hulls are reduced by three-avbd's own `convexHull` (spreads to 32 vertices). The Python side sends raw part
  vertices; the sidecar builds hulls.
- Pieces of one Convex Parts object share a collision group that excludes itself.

### 5.2 Protocol additions (exact framing is the builder's, following v1's style)
- `load_objects {bodies:[{id, type, shape, size|radius|vertices, position, rotation, density, friction}],
  welds:[{a, b, anchorA, anchorB, breakForce?}]}` → answered by SCENE (statics as v1, so the existing renderer/pick
  code keeps working) — body ids map to Blender objects/parts on the Python side.
- `move {moves:[{body, position, rotation}]}` for Animated bodies, sent before each `step`.
- `bake {frames, moves_per_frame}` or a step loop driven by Python — builder's call; bake must not block Blender's
  UI for more than a frame at a time (progress shown; Esc cancels and leaves no partial keyframes).
- Break events: EVENT `{kind:"break", a, b}` (informational; the panel may count them).

### 5.3 Blender side
- **Object → body** (pure, testable module): evaluated mesh in world space at Start.
  - Box/Sphere sizes from the object's oriented bounds (object scale baked in); Convex Hull from evaluated vertices;
    Convex Parts from loose parts (bmesh/numpy connected components).
  - Body pose = the object's world location + rotation (unit scale); the shape carries the scale. On every frame,
    write `matrix_world` = sim pose × original scale (so scaled objects stay scaled).
  - Convex Parts: one body per part, welded; the Blender object follows **its first part's body with the
    part-relative offset**, unless the welds break — then the object can't follow all parts (see §8).
- **Live update:** apply poses to `matrix_world` of the marked objects each frame (batched; no per-object depsgraph
  thrash beyond Blender's own). Restore originals on R/Stop/Esc/error.
- **Animated:** each step, evaluate the object's world matrix at the scene frame for the current sim time and send
  `move`.
- **Bake:** step through the range, insert location/rotation keyframes per Dynamic object per frame (via fcurve
  arrays, not `keyframe_insert` per call, for speed); undo-pushable as one step.
- The v1 instanced renderer is not used for own objects (the real objects are what you see).

## 6. Constraints
- Everything in v1's Global Constraints still binds (Windows, Blender 5.2, Node 24 sidecar, no GPU binding in Blender,
  no module-level GPU objects, vendored code unedited, pure modules free of bpy).
- No new runtime dependencies on either side.

## 7. Measured facts this rests on
- v1: Brick Ring 110k live at mostly 30+ fps; Wall Smash ~60 fps; sidecar pipe ~0.9 ms per 3.5 MB; welded hard
  joints (Breakable Wall) behave like the demo (user check 2026-11-04).
- three-avbd World supports kinematic `moveTo` via its `BodyMover` (velocity from target pose) — read from source,
  not yet measured from Rubble.

## 7a. Decisions settled by the builder check (assistant's calls, 2026-11-04)

1. **Concave Static/Animated objects:** Convex Parts is allowed for every type. For Static and Animated objects the
   parts are separate fixed / kinematic bodies with **no welds** (each Animated part gets its own `moveTo` per step).
   Under Auto or Convex Hull, when hull volume > 1.5× mesh volume, the panel shows a warning ("concave — use Convex
   Parts") on that object; Start still proceeds.
2. **Time mapping:** substeps per scene frame `k = ceil(60 / fps)`, solver `dt = 1 / (fps · k)` (≤ 1/60; 24 fps → 3
   steps of 1/72 s). One scene frame = exactly k steps, so bake keyframes land on frames and Animated objects are
   sampled at `frame + i/k` (subframe evaluation). Live Start begins at `frame_current` and **plays the timeline**:
   the frame advances every k steps.
3. **Existing animation / parents:** a Dynamic object must have no parent and no location/rotation animation; Start
   (and Bake) lists offending objects and refuses until fixed. Bake writes into a new action named
   `Rubble Bake <object>` and Clear Bake removes only actions with that name; original transforms are stored on Start
   / Bake and restored on Stop / Clear.
4. **Object types:** mesh objects only (other types are not offered the panel). The **evaluated** mesh is used
   (modifiers count). Any object scale (including non-uniform) is baked into the collision shape at Start; the body
   pose has unit scale and `matrix_world` = sim pose ∘ stored local offset ∘ original scale.
5. **Origin vs body frame:** three-avbd places hull bodies at their centre of mass on principal axes. Rubble stores
   a per-object local offset (object origin relative to the body frame, from the body's initial pose after add) and
   composes it when writing `matrix_world`.
6. **Break Force:** the panel field is **Break Strength**, in multiples of the object's own weight (`breakForce =
   strength · mass · 9.81` N); 0 = unbreakable. On the first break of an object, Rubble hides it and shows one
   temporary display object per part (each following its own body), so still-welded islands look right automatically;
   all are removed and the original restored on Stop. Bake with breaks creates real per-part objects only when "Split
   on break" is enabled; otherwise it warns and keyframes the first part.
7. **Capacity:** World `maxBodies` = marked bodies + 4096 (cannonballs). A null from `addBox/addSphere/addHull` aborts
   Start with a clear message. A hull reduced to 32 vertices logs one warning per object.

## 8. Left to the builder
- Auto shape thresholds (how close to a box/sphere counts), with a test set of meshes.
- How a broken Convex Parts object is shown live: recommended — on the first break, the object is hidden and its parts
  are drawn as separate temporary display objects (or with the v1 instanced renderer), restored on Stop. Bake of a
  broken object: keyframe per-part objects created on Bake only if the user enables "Split on break" — otherwise bake
  keyframes the first part only and warns.
- Pacing of bake (steps per timer tick), progress UI.
- Protocol field names and framing details within §5.2.

## 9. Risks to check first in the plan
1. **Real-object update cost** at 500 / 2,000 objects (matrix_world writes per frame) — measure before building on it.
2. **World API under Dawn headless** — create a World, add hulls and a fixed joint, step, read poses; confirm z-up
   gravity and kinematic `moveTo` work.
3. **Weld stiffness:** a Convex Parts object of ~8 parts dropped on the ground — does it visibly flex at the default
   iteration count? If yes, record the iteration count that fixes it.
