# Rubble

Rubble runs three-avbd's GPU rigid-body demo scenes (AVBD, SIGGRAPH 2025) live in the Blender 5.2 viewport. The physics runs unchanged in a Node 24 + Dawn sidecar process, and Blender draws the poses it sends back. It is viewport-only: no Cycles or EEVEE render, no bake, no cache output. Windows only. It runs from the repo checkout; there is no installable zip.

## Requirements

- Windows 11
- Blender 5.2
- Node 24 or newer on PATH
- A WebGPU-capable GPU

## Setup

```
npm install --ignore-scripts
python -m venv .venv
.venv\Scripts\pip install pytest numpy==2.3.4
```

The Python venv is only needed for the tests.

## Run

```
powershell -File tools\dev_blender.ps1
```

This starts Blender with Rubble registered from the checkout. Open the N-panel, go to the Rubble tab, pick a scene, and press Start. The first scene load takes about 11 s while the shaders compile.

Controls in the viewport:

- Left-drag: grab a body
- Space: fire a cannonball from the view
- P: play / pause
- `.`: single step
- R: reset
- Esc: stop live mode

## Scenes

- Brick Ring (28k)
- Brick Ring (110k)
- Brick Walls (27k)
- Wall Smash (2k)
- Breakable Wall (600)
- Chain Mail (1.6k)
- Heavy Pendulum
- Box Pile (4k)
- Box Pile (32k)
- Box Columns (100k)

## Measured performance

Machine: RTX 5050, 2026-11-04.

| Scene | Result |
| --- | --- |
| Brick Ring (110k) | mostly 30+ fps (user GUI test) |
| Wall Smash (2k) | about 60 fps (GUI smoke test) |

Viewport draw alone, on Blender's default OpenGL backend, with the pose texture rebuilt each tick:

| Bodies | fps |
| --- | --- |
| 110,592 | 90 |
| 262,144 | 71 |
| 512,000 | 49 |

Sidecar step time (median):

- Wall Smash: about 15 ms
- Brick Ring (110k): about 22 ms

The other scenes were not measured individually.

## Tests

```
npm run test:sidecar
.venv\Scripts\python -m pytest
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python tests\blender\run_tests.py
```

## Notes

- Works on Blender's default OpenGL backend. Vulkan is not needed.
- Reloading the addon in the dev launch path is not meaningful. There is no `bl_info` or manifest, and F3 Reload Scripts does not call `rubble.unregister()`. Reload and unregister teardown is covered by the headless test `test_register_unregister_twice`.
- The Node path preference has no effect in dev launch mode. Node must be on PATH.

## Credits

AVBD: Chris Giles, Elie Diaz, Cem Yuksel (SIGGRAPH 2025). three-avbd: Steven Bobyn (MIT), including ports of avbd-demo3d and avbd-demo2d by Chris Giles (MIT). Dawn via the `webgpu` npm package.

## License

The vendored three-avbd code in `vendor/three-avbd/` is MIT licensed. See `vendor/three-avbd/LICENSE` and `vendor/three-avbd/THIRD_PARTY_NOTICES.md`.

This repository's own license has not been chosen yet.
