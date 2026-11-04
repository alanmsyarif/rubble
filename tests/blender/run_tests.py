"""Blender test runner: blender -b --factory-startup --python tests/blender/run_tests.py"""
import importlib
import inspect
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]), str(HERE)]

import bpy  # noqa: E402
import gpu  # noqa: E402

if bpy.app.background and hasattr(gpu, "init"):
    gpu.init()

failed = 0
for path in sorted(HERE.glob("test_*.py")):
    try:
        mod = importlib.import_module(path.stem)
    except Exception:
        failed += 1
        print(f"FAIL {path.stem} (import)\n{traceback.format_exc()}")
        continue
    for name, fn in inspect.getmembers(mod, inspect.isfunction):
        if not name.startswith("test_") or fn.__module__ != mod.__name__:
            continue
        try:
            fn()
            print(f"PASS {path.stem}.{name}")
        except Exception:
            failed += 1
            print(f"FAIL {path.stem}.{name}\n{traceback.format_exc()}")

print(f"{'FAILED' if failed else 'OK'}: {failed} failure(s)")
sys.stdout.flush()
sys.exit(1 if failed else 0)
