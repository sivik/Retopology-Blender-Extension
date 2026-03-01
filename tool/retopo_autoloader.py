"""
Retopo Script Auto-Loader
=========================
A development-convenience addon for Blender.

Automatically executes *.py scripts found next to this file at Blender startup,
so you can edit them externally without reinstalling the addon every time.

Installation:
  Edit → Preferences → Add-ons → Install → retopo_autoloader.py
  Enable "Retopo Script Auto-Loader"

Default behaviour:
  Scans the same directory this file lives in for files matching
  the pattern defined in AddonPreferences (default: "retopology_tool*.py").
  Override the scan directory in:
  Edit → Preferences → Add-ons → Retopo Script Auto-Loader → Scripts Directory

Reload button:
  The operator "Reload Scripts" re-executes all matched files on demand.
  Useful after editing a script — no need to restart Blender.
"""

bl_info = {
    "name": "Retopo Script Auto-Loader",
    "version": (1, 1, 0),
    "blender": (3, 0, 0),
    "category": "Development",
    "description": (
        "Executes retopology scripts at startup from a configurable directory. "
        "Development tool — no hardcoded paths."
    ),
}

import bpy
import os
import glob


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _this_dir() -> str:
    """Return the directory this file lives in (works whether installed or run as script)."""
    try:
        return os.path.dirname(os.path.realpath(__file__))
    except NameError:
        # __file__ is not defined when run via bpy.ops.script.python_file_run
        return bpy.utils.user_resource('SCRIPTS', path="addons")


def _get_prefs():
    try:
        return bpy.context.preferences.addons[__name__].preferences
    except (KeyError, AttributeError):
        return None


def _resolve_directory() -> str:
    """Return effective scripts directory: preference override or this file's directory."""
    prefs = _get_prefs()
    if prefs and prefs.scripts_dir.strip():
        return os.path.realpath(prefs.scripts_dir.strip())
    return _this_dir()


def _resolve_pattern() -> str:
    prefs = _get_prefs()
    if prefs and prefs.file_pattern.strip():
        return prefs.file_pattern.strip()
    return "retopology_tool*.py"


def _find_scripts() -> list[str]:
    """Return sorted list of script paths matching the pattern in the target directory."""
    directory = _resolve_directory()
    pattern   = _resolve_pattern()
    self_path = os.path.realpath(__file__)
    matches   = sorted(glob.glob(os.path.join(directory, pattern)))
    # Never exec ourselves
    return [p for p in matches if os.path.realpath(p) != self_path]


def _exec_script(path: str) -> bool:
    """Execute a single Python file. Returns True on success."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
        exec(compile(source, path, "exec"), {"__name__": "__main__", "__file__": path})
        print(f"[AutoLoader] ✓  {os.path.basename(path)}")
        return True
    except Exception as exc:
        print(f"[AutoLoader] ✗  {os.path.basename(path)}: {exc}")
        return False


def load_scripts():
    """Load all matched scripts. Returns None so bpy.app.timers does not repeat."""
    scripts = _find_scripts()
    if not scripts:
        print(f"[AutoLoader] No scripts found — directory: {_resolve_directory()!r}, "
              f"pattern: {_resolve_pattern()!r}")
    for path in scripts:
        _exec_script(path)
    return None   # <-- required: returning None stops the timer from repeating


# ---------------------------------------------------------------------------
# Addon Preferences
# ---------------------------------------------------------------------------

class AUTOLOADER_Preferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    scripts_dir: bpy.props.StringProperty(
        name="Scripts Directory",
        description=(
            "Directory to scan for scripts. "
            "Leave empty to use the directory this addon file lives in."
        ),
        subtype="DIR_PATH",
        default="",
    )

    file_pattern: bpy.props.StringProperty(
        name="File Pattern",
        description=(
            "Glob pattern for script filenames (e.g. 'retopology_tool*.py', '*.py'). "
            "This file is always excluded."
        ),
        default="retopology_tool*.py",
    )

    startup_delay: bpy.props.FloatProperty(
        name="Startup Delay (s)",
        description="Seconds to wait after Blender starts before loading scripts",
        default=1.5,
        min=0.0,
        max=10.0,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "scripts_dir")
        layout.prop(self, "file_pattern")
        layout.prop(self, "startup_delay")

        layout.separator()
        col = layout.column(align=True)
        scripts = _find_scripts()
        if scripts:
            col.label(text=f"Found {len(scripts)} script(s):", icon="CHECKMARK")
            for p in scripts:
                col.label(text=f"  {os.path.basename(p)}", icon="FILE_SCRIPT")
        else:
            col.label(text="No scripts match the current pattern.", icon="ERROR")
        layout.separator()
        layout.operator("autoloader.reload_scripts", icon="FILE_REFRESH")


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class AUTOLOADER_OT_ReloadScripts(bpy.types.Operator):
    """Re-execute all matched scripts without restarting Blender"""
    bl_idname  = "autoloader.reload_scripts"
    bl_label   = "Reload Scripts"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scripts = _find_scripts()
        if not scripts:
            self.report(
                {"WARNING"},
                f"No scripts found in {_resolve_directory()!r} "
                f"matching {_resolve_pattern()!r}",
            )
            return {"CANCELLED"}

        ok = sum(_exec_script(p) for p in scripts)
        self.report(
            {"INFO"} if ok == len(scripts) else {"WARNING"},
            f"Loaded {ok}/{len(scripts)} script(s) — see System Console for details",
        )
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_CLASSES = [
    AUTOLOADER_Preferences,
    AUTOLOADER_OT_ReloadScripts,
]


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    delay = 1.5
    prefs = _get_prefs()
    if prefs:
        delay = prefs.startup_delay

    bpy.app.timers.register(load_scripts, first_interval=delay, persistent=True)
    print(f"[AutoLoader] Registered — loading scripts in {delay:.1f}s "
          f"from {_resolve_directory()!r}")


def unregister():
    if bpy.app.timers.is_registered(load_scripts):
        bpy.app.timers.unregister(load_scripts)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
