"""Development launch: blender --python tools/dev_register.py registers Rubble from this checkout."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rubble  # noqa: E402

rubble.register()
