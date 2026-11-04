"""Rubble: three-avbd's GPU rigid-body demo scenes live in Blender's viewport.
bpy is imported only inside register()/unregister(), so core tests can import this package."""
import atexit

from .sidecar import stop_all

bl_info = {
    "name": "Rubble",
    "author": "Rubble contributors (three-avbd by Steven Bobyn, AVBD by Giles, Diaz, Yuksel)",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "3D Viewport > Sidebar (N) > Rubble",
    "description": "three-avbd GPU rigid-body demo scenes live in the viewport (Node 24 sidecar)",
    "category": "Physics",
}


def _classes():
    from . import ops, panel
    return panel.CLASSES + ops.CLASSES


def _stop_everything(*_args):
    from . import ops
    s = ops.live()
    if s:
        s.stop()
    stop_all()


def register():
    import bpy
    for c in _classes():
        bpy.utils.register_class(c)
    from .panel import RubbleProps
    bpy.types.WindowManager.rubble = bpy.props.PointerProperty(type=RubbleProps)
    if _stop_everything not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(bpy.app.handlers.persistent(_stop_everything))
    atexit.register(stop_all)


def unregister():
    import bpy
    _stop_everything()
    if _stop_everything in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_stop_everything)
    atexit.unregister(stop_all)
    del bpy.types.WindowManager.rubble
    for c in reversed(_classes()):
        bpy.utils.unregister_class(c)
