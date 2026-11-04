"""N-panel tab "Rubble", its window-manager props and the addon preferences."""
import bpy
import gpu
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from . import ops

# Same names, same order as sidecar/scenes.ts V1_SCENES
SCENES = ["Brick Ring (28k)", "Brick Ring (110k)", "Brick Walls (27k)", "Wall Smash (2k)", "Breakable Wall (600)",
          "Chain Mail (1.6k)", "Heavy Pendulum", "Box Pile (4k)", "Box Pile (32k)", "Box Columns (100k)"]
# The scene options the demo's panel exposes (vendor app3d/scene-extras.ts): scene -> (prop, demo key)
OPTIONS = {
    "Breakable Wall (600)": ("weld_strength", "strength"),
    "Chain Mail (1.6k)": ("ball_density", "ballDensity"),
    "Heavy Pendulum": ("mass_ratio", "ratio"),
}


def _choices(*pairs):
    return [(str(v), label, "") for label, v in pairs]


def _reload(self, context):
    """The demo reloads the scene when it or one of its options changes; so does a live session."""
    s = ops.live()
    if s:
        s.load(self.scene, self.options())


class RubbleProps(bpy.types.PropertyGroup):
    scene: EnumProperty(name="Scene", items=[(n, n, "") for n in SCENES], default="Wall Smash (2k)", update=_reload)
    playing: BoolProperty(name="Playing", default=True)
    # choices from scene-extras.ts, defaults from bench-scenes.ts options
    weld_strength: EnumProperty(name="Weld strength", items=_choices(("Weak", 20), ("Normal", 50), ("Strong", 150)),
                                default="50", update=_reload)
    ball_density: EnumProperty(name="Ball", items=_choices(("Light", 1), ("Heavy", 10), ("Massive", 100)),
                               default="10", update=_reload)
    mass_ratio: EnumProperty(name="Block : one link",
                             items=_choices(("1:1", 1), ("100:1", 100), ("1k:1", 1000), ("50k:1", 50000)),
                             default="50000", update=_reload)
    fps: FloatProperty(name="FPS")
    step_ms: FloatProperty(name="Step ms")
    bodies: IntProperty(name="Bodies")
    error: StringProperty(name="Error")

    def options(self):
        """The load command's options for the selected scene, with the demo's keys."""
        o = OPTIONS.get(self.scene)
        return {o[1]: int(getattr(self, o[0]))} if o else {}


class RubblePrefs(bpy.types.AddonPreferences):
    bl_idname = __package__
    node_path: StringProperty(name="Node executable", default="node", subtype="FILE_PATH",
                              description="Node 24+; a bare name is looked up on PATH")

    def draw(self, context):
        self.layout.prop(self, "node_path")


class RUBBLE_PT_panel(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Rubble"
    bl_label = "Rubble"

    def draw(self, context):
        p = context.window_manager.rubble
        s = ops.live()
        col = self.layout.column()
        col.label(text=f"GPU backend: {gpu.platform.backend_type_get()}")  # R4: no Vulkan hint
        col.prop(p, "scene", text="")
        o = OPTIONS.get(p.scene)
        if o:
            col.prop(p, o[0])
        if s:
            col.operator("rubble.stop", icon="CANCEL")
            row = col.row(align=True)
            row.operator("rubble.play_toggle", text="Pause" if p.playing else "Play",
                         icon="PAUSE" if p.playing else "PLAY")
            row.operator("rubble.step", text="", icon="FRAME_NEXT")
            row.operator("rubble.reset", text="", icon="FILE_REFRESH")
            if p.bodies == 0:
                col.label(text="Loading scene…", icon="TIME")
            else:
                col.label(text=f"{p.fps:.0f} fps   step {p.step_ms:.1f} ms")
                col.label(text=f"{p.bodies:,} bodies")
            col.label(text="Drag LMB · Space ball · P · . · R · Esc")
        else:
            col.operator("rubble.live", icon="PLAY")
        if p.error:
            col.label(text=p.error, icon="ERROR")


CLASSES = (RubbleProps, RubblePrefs, RUBBLE_PT_panel)
