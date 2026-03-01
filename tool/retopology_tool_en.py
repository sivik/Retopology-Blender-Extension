bl_info = {
    "name": "Retopo Stroke Tool (EN)",
    "author": "Retopo MCP",
    "version": (2, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > N-Panel > Retopo Tool",
    "description": "Retopology with multiple methods: Voxel, Shrinkwrap, Decimate, Quadriflow, Instant Meshes, QuadWild",
    "category": "Mesh",
}

import bpy
import bmesh
import os
import subprocess
import tempfile
from mathutils import Vector
from bpy_extras import view3d_utils


# ─────────────────────────────────────────────────────────────────────────────
# PROPERTIES
# ─────────────────────────────────────────────────────────────────────────────

class RetopoPipelineProps(bpy.types.PropertyGroup):

    target_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="High-Poly Target",
        description="Source model for retopology"
    )

    # ── Retopo Mode ────────────────────────────────────────────
    retopo_mode: bpy.props.EnumProperty(
        name="Retopo Mode",
        description="Choose retopology method",
        items=[
            ('VOXEL',       "Voxel Remesh",
             "Fast voxel remesh — automatic mesh over the entire model",
             'MOD_REMESH', 0),
            ('SHRINKWRAP',  "Remesh + Shrinkwrap",
             "Remesh + fit to original — more accurate surface conforming",
             'MOD_SHRINKWRAP', 1),
            ('DECIMATE',    "Decimate",
             "Reduces poly count while preserving original topology",
             'MOD_DECIM', 2),
            ('QUADRIFLOW',     "Quadriflow",
             "Builds a clean quad mesh respecting curvature — best topology quality",
             'OUTLINER_OB_SURFACE', 3),
            ('INSTANT_MESHES', "Instant Meshes",
             "External tool — great topology with edge loops (requires IM binary)",
             'EXPORT', 4),
            ('QUADWILD', "QuadWild",
             "Closest quality to ZRemesher — open-source solver (requires quadwild-bimdf binary)",
             'OUTLINER_OB_CURVES', 5),
        ],
        default='VOXEL'
    )

    # ── Voxel Settings ─────────────────────────────────────────
    voxel_size: bpy.props.FloatProperty(
        name="Voxel Size",
        default=0.05, min=0.001, max=1.0,
        description="Smaller = more polygons"
    )

    # ── Decimate Settings ──────────────────────────────────────
    decimate_ratio: bpy.props.FloatProperty(
        name="Decimate Ratio",
        default=0.3, min=0.01, max=1.0,
        description="1.0 = no change, 0.1 = 10% of original faces"
    )

    # ── Density Preset ─────────────────────────────────────────
    density_preset: bpy.props.EnumProperty(
        name="Density",
        description="Polygon count preset",
        items=[
            ('GAME',   "Game  (~500-1000f)",   "Very low-poly for real-time games"),
            ('MEDIUM', "Medium (~1000-3000f)",  "Balance of detail and performance"),
            ('HIGH',   "High   (~3000-6000f)",  "High detail, for rendering"),
            ('CUSTOM', "Custom",                "Manual parameter control"),
        ],
        default='MEDIUM',
        update=lambda self, ctx: RetopoPipelineProps._apply_preset(self, ctx)
    )

    # ── Edge Loops ─────────────────────────────────────────────
    stroke_thickness: bpy.props.FloatProperty(
        name="Stroke Thickness",
        default=0.03, min=0.001, max=0.5
    )
    active_stroke_index: bpy.props.IntProperty(default=0)
    is_drawing: bpy.props.BoolProperty(default=False)
    stroke_counter: bpy.props.IntProperty(default=0)
    use_stroke_guidance: bpy.props.BoolProperty(
        name="Stroke Guidance",
        default=False,
        description="After remesh, attracts vertices towards drawn strokes"
    )
    stroke_snap_radius: bpy.props.FloatProperty(
        name="Snap Radius",
        default=0.05, min=0.001, max=0.5,
        description="Snap radius for attracting vertices to strokes"
    )
    stroke_guidance_mode: bpy.props.EnumProperty(
        name="Guidance Mode",
        description="Snap: pulls vertices TO the stroke. Field: aligns edge direction with the stroke",
        items=[
            ('SNAP',  "Snap",  "Vertices snap onto the stroke line (hard edge loops)",  'SNAP_ON',    0),
            ('FIELD', "Field", "Edges align with the stroke tangent (soft guidance)", 'FORCE_MAGNETIC', 1),
        ],
        default='SNAP'
    )
    stroke_field_strength: bpy.props.FloatProperty(
        name="Strength",
        default=0.5, min=0.0, max=1.0,
        description="Strength of edge alignment to the stroke direction (0 = no effect, 1 = full alignment)"
    )
    stroke_field_radius: bpy.props.FloatProperty(
        name="Influence Radius",
        default=0.15, min=0.001, max=1.0,
        description="Influence radius of the stroke tangent field on surrounding vertices"
    )

    # ── Instant Meshes Settings ────────────────────────────────
    instant_meshes_path: bpy.props.StringProperty(
        name="Instant Meshes Path",
        description="Full path to the Instant Meshes executable",
        subtype='FILE_PATH',
        default=""
    )
    instant_meshes_faces: bpy.props.IntProperty(
        name="Target Faces",
        default=2000, min=100, max=50000,
        description="Target face count"
    )
    instant_meshes_crease: bpy.props.IntProperty(
        name="Crease Angle",
        default=30, min=0, max=90,
        description="Angle in degrees above which an edge is treated as a hard edge"
    )
    instant_meshes_smooth: bpy.props.IntProperty(
        name="Smooth Iterations",
        default=2, min=0, max=10,
        description="Number of mesh smoothing iterations after remesh"
    )
    instant_meshes_dominant: bpy.props.BoolProperty(
        name="Dominant Quads",
        default=False,
        description="Allows triangles at poles (dominant mode) — better results for difficult topology"
    )
    instant_meshes_boundaries: bpy.props.BoolProperty(
        name="Align to Boundaries",
        default=False,
        description="Aligns edge loops to open mesh boundaries (-b). "
                    "Essential for retopo of cut models: half-body, hands, clothing pieces"
    )
    instant_meshes_deterministic: bpy.props.BoolProperty(
        name="Deterministic",
        default=False,
        description="Uses a slower but deterministic algorithm (-d). "
                    "Same model always produces identical result — useful in production pipelines"
    )
    instant_meshes_threads: bpy.props.IntProperty(
        name="CPU Threads",
        default=0, min=0, max=64,
        description="Number of CPU threads (-t). 0 = automatic (IM default). "
                    "Increase on multi-core machines to speed up large meshes"
    )

    # ── QuadWild Settings (#15) ────────────────────────────────
    quadwild_path: bpy.props.StringProperty(
        name="QuadWild Binary",
        description="Full path to the QuadWild executable (quadwild-bimdf). "
                    "Used when the QRemeshify addon is NOT installed",
        subtype='FILE_PATH',
        default=""
    )
    quadwild_faces: bpy.props.IntProperty(
        name="Target Faces",
        default=2000, min=100, max=50000,
        description="Target face count (subprocess mode — when QRemeshify is unavailable)"
    )
    quadwild_scale_fact: bpy.props.FloatProperty(
        name="Scale Factor",
        default=1.0, min=0.05, max=10.0,
        description="Quad size: <1 = more detail (more poly), >1 = larger quads (less poly). "
                    "Used by the QRemeshify addon (scaleFact)"
    )
    quadwild_sharp_angle: bpy.props.FloatProperty(
        name="Sharp Angle",
        default=30.0, min=1.0, max=180.0,
        subtype='ANGLE',
        description="Angle above which an edge is treated as sharp (passed to QuadWild)"
    )

    # ── Mesh Healing (#18) ─────────────────────────────────────
    use_mesh_healing: bpy.props.BoolProperty(
        name="Mesh Healing",
        default=True,
        description="Before remesh: auto-repair of the mesh (Fill Holes, Remove Doubles, "
                    "Recalc Normals). Eliminates the main cause of holes after Voxel Remesh"
    )

    # ── Quadriflow Settings ────────────────────────────────────
    quadriflow_faces: bpy.props.IntProperty(
        name="Target Faces",
        default=2000, min=100, max=50000,
        description="Target face count (approximate)"
    )
    quadriflow_use_curvature: bpy.props.BoolProperty(
        name="Use Mesh Curvature",
        default=False,
        description="Increases mesh density where curvature is higher"
    )
    quadriflow_preserve_sharp: bpy.props.BoolProperty(
        name="Preserve Hard Edges",
        default=True,
        description="Forces edge loops along sharp edges (essential for hard-surface)"
    )
    quadriflow_preserve_boundary: bpy.props.BoolProperty(
        name="Preserve Boundaries",
        default=True,
        description="Aligns edge loops to open mesh boundaries"
    )
    quadriflow_use_symmetry: bpy.props.BoolProperty(
        name="Use Symmetry",
        default=False,
        description="Remeshes one half and mirrors it — guarantees symmetric topology"
    )
    quadriflow_smooth_normals: bpy.props.BoolProperty(
        name="Smooth Normals",
        default=False,
        description="Smooths normals after remesh"
    )

    # ── Hard Edge Detection ────────────────────────────────────
    use_hard_edge_prepass: bpy.props.BoolProperty(
        name="Hard Edge Pre-pass",
        default=False,
        description="Before remesh: marks target edges as creases by angle. "
                    "Respected by Quadriflow (preserve_sharp) and Instant Meshes (--crease)"
    )
    hard_edge_angle: bpy.props.FloatProperty(
        name="Crease Angle",
        default=30.0, min=1.0, max=180.0,
        subtype='ANGLE',
        description="Edges above this angle will be marked as sharp/crease"
    )

    # ── Laplacian Smooth + Re-project ──────────────────────────
    use_smooth_reproject: bpy.props.BoolProperty(
        name="Smooth + Re-project",
        default=False,
        description="After remesh: iterative Laplacian smooth + re-projection back "
                    "onto high-poly. Evens out vertex distribution and improves fit"
    )
    smooth_reproject_iterations: bpy.props.IntProperty(
        name="Iterations",
        default=3, min=1, max=20,
        description="Number of smooth → re-project cycles"
    )
    smooth_reproject_factor: bpy.props.FloatProperty(
        name="Smooth Factor",
        default=0.5, min=0.0, max=1.0,
        description="Laplacian smooth strength per iteration"
    )

    # ── Voxel Settings ──────────────────────────────── (additional)
    voxel_adaptivity: bpy.props.FloatProperty(
        name="Adaptivity",
        default=0.0, min=0.0, max=1.0,
        description="Triangulates flat areas to reduce poly count. "
                    "Note: value > 0 disables Fix Poles"
    )

    # ── Curvature Density Map (#3) ─────────────────────────────
    use_curvature_density: bpy.props.BoolProperty(
        name="Curvature Pre-pass",
        default=False,
        description="Paints Gaussian curvature as Vertex Colors on the target "
                    "(analogue of Vertex Color Density Map from Quad Remesher)"
    )

    # ── LOD Chain (#6) ─────────────────────────────────────────
    generate_lod: bpy.props.BoolProperty(
        name="Generate LOD Chain",
        default=False,
        description="After remesh, creates LOD0-LODn via progressive Decimate "
                    "in a dedicated collection"
    )
    lod_levels: bpy.props.IntProperty(
        name="LOD Levels",
        default=3, min=2, max=4,
        description="Number of levels: LOD0=full, LOD1=50%, LOD2=25%, LOD3=10%"
    )

    # ── Topology Quality Metrics (#8) ──────────────────────────
    compute_quality_metrics: bpy.props.BoolProperty(
        name="Quality Metrics",
        default=False,
        description="After remesh, computes: % quads, poles, aspect ratio, "
                    "deviation from high-poly"
    )
    last_metrics_valid:      bpy.props.BoolProperty(default=False)
    last_metrics_quad_pct:   bpy.props.FloatProperty(default=0.0)
    last_metrics_poles:      bpy.props.IntProperty(default=0)
    last_metrics_avg_aspect: bpy.props.FloatProperty(default=0.0)
    last_metrics_avg_dist:   bpy.props.FloatProperty(default=0.0)
    last_metrics_avg_angle:  bpy.props.FloatProperty(default=0.0)

    # ── Stroke Symmetry (#9) ───────────────────────────────────
    stroke_use_symmetry: bpy.props.BoolProperty(
        name="Symmetry",
        default=False,
        description="Creates a mirrored stroke on the opposite side of the selected axis"
    )
    stroke_symmetry_axis: bpy.props.EnumProperty(
        name="Axis",
        items=[
            ('X', "X", "Symmetry along the X axis"),
            ('Y', "Y", "Symmetry along the Y axis"),
            ('Z', "Z", "Symmetry along the Z axis"),
        ],
        default='X'
    )

    # ── Shrinkwrap offset ──────────────────────────────────────
    shrinkwrap_offset: bpy.props.FloatProperty(
        name="Offset",
        default=0.001, min=0.0, max=0.1,
        description="Distance from the original surface"
    )

    def _apply_preset(self, context):
        if self.density_preset == 'GAME':
            self.voxel_size            = 0.15
            self.decimate_ratio        = 0.1
            self.quadriflow_faces      = 500
            self.instant_meshes_faces  = 500
            self.quadwild_faces        = 500
            self.quadwild_scale_fact   = 2.5
        elif self.density_preset == 'MEDIUM':
            self.voxel_size            = 0.06
            self.decimate_ratio        = 0.3
            self.quadriflow_faces      = 2000
            self.instant_meshes_faces  = 2000
            self.quadwild_faces        = 2000
            self.quadwild_scale_fact   = 1.0
        elif self.density_preset == 'HIGH':
            self.voxel_size            = 0.03
            self.decimate_ratio        = 0.6
            self.quadriflow_faces      = 5000
            self.instant_meshes_faces  = 5000
            self.quadwild_faces        = 5000
            self.quadwild_scale_fact   = 0.4


# ─────────────────────────────────────────────────────────────────────────────
# UIList – strokes only (filters out Camera, Light, etc.)
# ─────────────────────────────────────────────────────────────────────────────

class RETOPO_UL_StrokeList(bpy.types.UIList):

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        if not item.get("is_retopo_stroke"):
            return
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            vis_icon = 'HIDE_OFF' if not item.hide_viewport else 'HIDE_ON'
            row.prop(item, "hide_viewport", text="", emboss=False, icon=vis_icon)
            row.prop(item, "name", text="", emboss=False, icon='CURVE_BEZCURVE')
            if item.type == 'CURVE' and item.data.splines:
                pts = len(item.data.splines[0].bezier_points)
                row.label(text=f"{pts}pt")

    def filter_items(self, context, data, propname):
        objects   = getattr(data, propname)
        flt_flags = []
        for obj in objects:
            if obj.get("is_retopo_stroke") is True:
                flt_flags.append(self.bitflag_filter_item)
            else:
                flt_flags.append(0)
        return flt_flags, []


def get_stroke_objects(context):
    return [o for o in bpy.data.objects if o.get("is_retopo_stroke") is True]


def _obj_in_scene(obj):
    """Returns True if the object exists and is linked to the active scene.
    A PointerProperty may hold a reference to an orphan object (deleted
    with the Delete key in the viewport) — this helper distinguishes that case."""
    if obj is None:
        return False
    try:
        return bpy.context.scene.objects.get(obj.name) is obj
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# RAYCAST – snapping lines to the surface
# ─────────────────────────────────────────────────────────────────────────────

def raycast_to_surface(context, x, y, target_obj):
    region = context.region
    rv3d   = context.region_data
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, (x, y))
    ray_origin  = view3d_utils.region_2d_to_origin_3d(region, rv3d, (x, y))

    depsgraph = context.evaluated_depsgraph_get()
    eval_obj  = target_obj.evaluated_get(depsgraph)
    mat_inv   = eval_obj.matrix_world.inverted()

    ray_origin_local = mat_inv @ ray_origin
    ray_dir_local    = (mat_inv.to_3x3() @ view_vector).normalized()
    success, location, normal, _ = eval_obj.ray_cast(ray_origin_local, ray_dir_local)

    if success:
        wp = eval_obj.matrix_world @ location
        wn = (eval_obj.matrix_world.to_3x3() @ normal).normalized()
        return wp + wn * 0.002
    return None


def fallback_to_plane(context, x, y, target_obj):
    from mathutils.geometry import intersect_line_plane
    region = context.region
    rv3d   = context.region_data
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, (x, y))
    ray_origin  = view3d_utils.region_2d_to_origin_3d(region, rv3d, (x, y))
    depth_point = target_obj.location if target_obj else context.scene.cursor.location
    normal = rv3d.view_rotation @ Vector((0, 0, 1))
    return intersect_line_plane(ray_origin, ray_origin + view_vector, depth_point, normal)


# ─────────────────────────────────────────────────────────────────────────────
# CURVATURE DENSITY MAP  (#3)
# ─────────────────────────────────────────────────────────────────────────────

def bake_curvature_density(target_obj):
    """
    Computes two curvature measures per vertex and stores them as Vertex Colors:

    1. CurvatureDensity — Gaussian curvature (discrete Gauss-Bonnet):
         K = |2pi - sum(theta_j)| / A_i   (A_i = Voronoi area)
       Red = high curvature (sharp corners), blue = flat.

    2. MeanCurvature — mean curvature (cotangent Laplacian):
         H = |sum (cot alpha + cot beta)(v_j - v)| / (2 A_i)
       Better detects bends and saddles (corners of the mouth, brow arch).
       Red = high curvature, blue = flat.

    Both maps are analogues of the Vertex Color Density Map from Quad Remesher.
    """
    import math

    bm = bmesh.new()
    bm.from_mesh(target_obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    # ── Layer 1: Gaussian curvature ────────────────────────────
    gauss_layer = bm.loops.layers.color.get("CurvatureDensity")
    if gauss_layer is None:
        gauss_layer = bm.loops.layers.color.new("CurvatureDensity")

    # ── Layer 2: Mean curvature ────────────────────────────────
    mean_layer = bm.loops.layers.color.get("MeanCurvature")
    if mean_layer is None:
        mean_layer = bm.loops.layers.color.new("MeanCurvature")

    # Cotangent weights per edge (for mean curvature)
    cot_weights = {}
    for e in bm.edges:
        v0, v1 = e.verts
        w = 0.0
        for f in e.link_faces:
            opp_verts = [v for v in f.verts if v not in (v0, v1)]
            # For a triangle: 1 opposite vertex; for a quad: 2 -> normalize
            for opp in opp_verts:
                a = v0.co - opp.co
                b = v1.co - opp.co
                cross = a.cross(b).length
                if cross > 1e-10:
                    cot = a.dot(b) / cross
                    w += max(0.0, cot) / len(opp_verts)
        cot_weights[e.index] = w

    gauss_curvatures = []
    mean_curvatures  = []
    for v in bm.verts:
        # Gaussian curvature (angle deficit / Voronoi area)
        angle_sum    = sum(l.calc_angle() for l in v.link_loops)
        voronoi_area = sum(l.face.calc_area() for l in v.link_loops) / 3.0
        if voronoi_area > 1e-10:
            gauss_curvatures.append(abs(2.0 * math.pi - angle_sum) / voronoi_area)
        else:
            gauss_curvatures.append(0.0)

        # Mean curvature (cotangent Laplacian magnitude / 2A)
        Hv = Vector((0.0, 0.0, 0.0))
        for e in v.link_edges:
            nb = e.other_vert(v)
            Hv += cot_weights[e.index] * (nb.co - v.co)
        if voronoi_area > 1e-10:
            mean_curvatures.append((Hv / (2.0 * voronoi_area)).length)
        else:
            mean_curvatures.append(0.0)

    max_g = max(gauss_curvatures) if gauss_curvatures else 1.0
    max_m = max(mean_curvatures)  if mean_curvatures  else 1.0
    if max_g < 1e-8: max_g = 1.0
    if max_m < 1e-8: max_m = 1.0

    for v, gc, mc in zip(bm.verts, gauss_curvatures, mean_curvatures):
        tg = min(gc / max_g, 1.0)
        tm = min(mc / max_m, 1.0)
        for loop in v.link_loops:
            loop[gauss_layer] = (tg, 0.0, 1.0 - tg, 1.0)
            loop[mean_layer]  = (tm, 0.0, 1.0 - tm, 1.0)

    bm.to_mesh(target_obj.data)
    bm.free()
    target_obj.data.update()
    return "CurvatureDensity"


# ─────────────────────────────────────────────────────────────────────────────
# TOPOLOGY QUALITY METRICS  (#8)
# ─────────────────────────────────────────────────────────────────────────────

def compute_topology_metrics(result_obj, target_obj, depsgraph):
    """
    Computes quality metrics for the resulting mesh:
      - quad_pct        : % of faces that are quads          (goal: 100%)
      - n_poles         : vertices with valence != 4 (excl. boundary) (goal: minimum)
      - avg_aspect      : average face aspect ratio          (goal: ~1.0)
      - avg_angle_score : min |sin theta| per quad (Scaled Jacobian)  (goal: ~1.0)
      - avg_dist        : average deviation from high-poly [m]  (goal: ~0.0)
    Returns a dict or {} for an empty mesh.
    """
    from mathutils.bvhtree import BVHTree

    bm = bmesh.new()
    bm.from_mesh(result_obj.data)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    n_faces = len(bm.faces)
    if n_faces == 0:
        bm.free()
        return {}

    n_quads  = sum(1 for f in bm.faces if len(f.verts) == 4)
    quad_pct = n_quads / n_faces * 100.0

    n_poles = sum(
        1 for v in bm.verts
        if not v.is_boundary and len(v.link_edges) not in (4,)
    )

    aspect_ratios = []
    angle_scores  = []
    for f in bm.faces:
        lens = [e.calc_length() for e in f.edges]
        mn = min(lens)
        if mn > 1e-8:
            aspect_ratios.append(max(lens) / mn)
        # Scaled Jacobian: min |sin theta_i| over 4 interior angles of the quad
        # Perfect quad: sin 90 deg = 1.0. Shear 30/150 deg: sin 30 deg = 0.5
        if len(f.verts) == 4:
            vco = [v.co for v in f.verts]
            sins = []
            for i in range(4):
                a = (vco[i - 1] - vco[i]).normalized()
                b = (vco[(i + 1) % 4] - vco[i]).normalized()
                sins.append(min(a.cross(b).length, 1.0))
            angle_scores.append(min(sins))
    avg_aspect      = sum(aspect_ratios) / len(aspect_ratios) if aspect_ratios else 0.0
    avg_angle_score = sum(angle_scores)  / len(angle_scores)  if angle_scores  else 0.0

    eval_tgt   = target_obj.evaluated_get(depsgraph)
    target_bvh = BVHTree.FromObject(eval_tgt, depsgraph)
    mat_world  = result_obj.matrix_world
    distances  = []
    for v in bm.verts:
        wco  = mat_world @ v.co
        hit, _, _, _ = target_bvh.find_nearest(wco)
        if hit:
            distances.append((wco - hit).length)
    avg_dist = sum(distances) / len(distances) if distances else 0.0

    n_verts = len(bm.verts)
    bm.free()

    return {
        'quad_pct':        quad_pct,
        'n_poles':         n_poles,
        'avg_aspect':      avg_aspect,
        'avg_angle_score': avg_angle_score,
        'avg_dist':        avg_dist,
        'n_faces':         n_faces,
        'n_verts':         n_verts,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LOD CHAIN GENERATION  (#6)
# ─────────────────────────────────────────────────────────────────────────────

def generate_lod_chain(context, result_obj, lod_levels):
    """
    Creates a LOD0-LODn chain via progressive Decimate on copies of result_obj.
    LOD0 = original (unchanged)
    LOD1 = 50%, LOD2 = 25%, LOD3 = 10% of faces.
    All placed into a collection named 'LOD_{name}'.
    Returns the LOD collection.
    """
    base_name = result_obj.name
    col_name  = f"LOD_{base_name}"

    lod_col = bpy.data.collections.get(col_name)
    if not lod_col:
        lod_col = bpy.data.collections.new(col_name)
        context.scene.collection.children.link(lod_col)

    # Move LOD0 to the collection
    result_obj.name = f"{base_name}_LOD0"
    for col in list(result_obj.users_collection):
        col.objects.unlink(result_obj)
    lod_col.objects.link(result_obj)

    ratios = [0.5, 0.25, 0.1][: lod_levels - 1]
    for i, ratio in enumerate(ratios, start=1):
        lod = result_obj.copy()
        lod.data = result_obj.data.copy()
        lod.name = f"{base_name}_LOD{i}"
        lod_col.objects.link(lod)

        bpy.ops.object.select_all(action='DESELECT')
        lod.select_set(True)
        context.view_layer.objects.active = lod
        mod = lod.modifiers.new("Decimate", 'DECIMATE')
        mod.ratio = ratio
        bpy.ops.object.modifier_apply(modifier="Decimate")

    return lod_col


# ─────────────────────────────────────────────────────────────────────────────
# HARD EDGE PRE-PASS
# ─────────────────────────────────────────────────────────────────────────────

def mark_hard_edges(target_obj, angle_deg):
    """
    Scans edges of target_obj and marks as sharp + crease those whose
    dihedral angle exceeds angle_deg. Respected by:
    - Quadriflow: use_preserve_sharp
    - Instant Meshes: --crease parameter
    Returns the number of marked edges.
    """
    import math
    threshold = math.radians(angle_deg)

    bm = bmesh.new()
    bm.from_mesh(target_obj.data)
    # Blender < 4.0: bm.edges.layers.crease  |  Blender 4.0+: float attribute "crease_edge"
    if hasattr(bm.edges.layers, 'crease'):
        crease_layer = bm.edges.layers.crease.verify()
    else:
        crease_layer = (bm.edges.layers.float.get("crease_edge") or
                        bm.edges.layers.float.new("crease_edge"))
    marked = 0

    for e in bm.edges:
        if len(e.link_faces) == 2:
            angle = e.calc_face_angle(0.0)
            if angle > threshold:
                e[crease_layer] = 1.0
                e.smooth = False
                marked += 1

    bm.to_mesh(target_obj.data)
    bm.free()
    target_obj.data.update()
    return marked


# ─────────────────────────────────────────────────────────────────────────────
# MESH HEALING PRE-PASS  (#18)
# ─────────────────────────────────────────────────────────────────────────────

def heal_mesh(target_obj):
    """
    Automatic mesh repair before remesh. Eliminates the most common causes
    of artifacts (holes after Voxel Remesh, flipped normals, duplicate verts).

    Operations (in order):
    1. Remove Doubles      — merges close vertices (dist=0.0001)
    2. Fill Holes          — fills holes in the mesh (sides=4 = quad preference)
    3. Recalc Face Normals — fixes flipped normals

    Returns a dict with the count of removed/repaired elements.
    """
    bm = bmesh.new()
    bm.from_mesh(target_obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    verts_before = len(bm.verts)

    # 1. Remove doubles
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0001)

    # 2. Fill holes — finds open edges and attempts to close them
    open_edges = [e for e in bm.edges if not e.is_manifold]
    holes_filled = 0
    if open_edges:
        result = bmesh.ops.holes_fill(bm, edges=open_edges, sides=4)
        holes_filled = len(result.get('faces', []))

    # 3. Recalc normals (outward)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    verts_after  = len(bm.verts)
    merged_verts = verts_before - verts_after

    bm.to_mesh(target_obj.data)
    bm.free()
    target_obj.data.update()

    return {
        'merged_verts': merged_verts,
        'holes_filled': holes_filled,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LAPLACIAN SMOOTH + RE-PROJECT
# ─────────────────────────────────────────────────────────────────────────────

def _cotangent_smooth_step(result_obj, factor):
    """
    One step of cotangent-weighted Laplacian smooth (pure bmesh, no Edit Mode).

    Advantage over uniform smooth (bpy.ops.mesh.vertices_smooth):
    - Does not cause geometry shrinkage (shrinkage bias) at irregular density.
    - Edges with small opposite angles (cot -> large) have more influence —
      this corresponds to the actual triangulated mesh geometry.
    - Safe for quad meshes: quads are treated as two triangles.

    Formula: Lc(v) = sum_j w_j * (v_j - v) / sum_j w_j,   w_j = cot(alpha_j) + cot(beta_j)
    """
    bm = bmesh.new()
    bm.from_mesh(result_obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    # Compute cotangent weight per edge
    cot_w = {}
    for e in bm.edges:
        v0, v1 = e.verts
        w = 0.0
        for f in e.link_faces:
            opp_verts = [v for v in f.verts if v not in (v0, v1)]
            for opp in opp_verts:
                a = v0.co - opp.co
                b = v1.co - opp.co
                cross = a.cross(b).length
                if cross > 1e-10:
                    cot = a.dot(b) / cross
                    w += max(0.0, cot) / len(opp_verts)  # normalize for quad
        cot_w[e.index] = w

    # Compute new positions (all at once, don't overwrite in-place)
    new_cos = {}
    for v in bm.verts:
        if v.is_boundary:
            continue
        w_total = 0.0
        pos = Vector((0.0, 0.0, 0.0))
        for e in v.link_edges:
            nb = e.other_vert(v)
            w = cot_w[e.index]
            pos += w * nb.co
            w_total += w
        if w_total > 1e-10:
            new_cos[v.index] = v.co.lerp(pos / w_total, factor)

    for v in bm.verts:
        if v.index in new_cos:
            v.co = new_cos[v.index]

    bm.to_mesh(result_obj.data)
    bm.free()
    result_obj.data.update()


def smooth_reproject(context, result_obj, target_obj, iterations, factor):
    """
    Iterative loop: Cotangent Laplacian smooth -> re-projection back onto the target BVH.
    Cotangent smooth eliminates the shrinkage bias typical of uniform Laplacian —
    vertices in denser areas are not overly attracted.
    """
    from mathutils.bvhtree import BVHTree

    depsgraph  = context.evaluated_depsgraph_get()
    eval_tgt   = target_obj.evaluated_get(depsgraph)
    target_bvh = BVHTree.FromObject(eval_tgt, depsgraph)

    mat_world = result_obj.matrix_world
    mat_inv   = mat_world.inverted()

    for _ in range(iterations):
        # Cotangent Laplacian smooth (no Edit Mode — pure bmesh)
        _cotangent_smooth_step(result_obj, factor)

        # Re-project — each vertex back onto the target surface
        bm = bmesh.new()
        bm.from_mesh(result_obj.data)
        for v in bm.verts:
            world_co = mat_world @ v.co
            hit_loc, _, _, _ = target_bvh.find_nearest(world_co)
            if hit_loc:
                v.co = mat_inv @ hit_loc
        bm.to_mesh(result_obj.data)
        bm.free()
        result_obj.data.update()


# ─────────────────────────────────────────────────────────────────────────────
# STROKE FIELD GUIDANCE
# ─────────────────────────────────────────────────────────────────────────────

def apply_stroke_guidance(context, result_obj, target_obj):
    """
    Post-process after remesh: attracts vertices of the resulting mesh to the
    nearest points of drawn strokes, then re-projects them back onto the
    target surface (BVH).

    Effect: vertices near strokes "slide" along the drawn lines,
    creating edge loops that follow the strokes.

    Returns the number of attracted vertices (0 = no strokes in range).
    """
    from mathutils.kdtree import KDTree
    from mathutils.bvhtree import BVHTree

    props   = context.scene.retopo_props
    strokes = get_stroke_objects(context)
    if not strokes:
        return 0

    # ── Step 1: sample strokes via eval mesh ──────────────────────────────
    # Converting a bezier curve to a temporary mesh gives points with all
    # interpolated positions (respects resolution_u).
    stroke_points = []
    depsgraph = context.evaluated_depsgraph_get()
    for s in strokes:
        eval_s = s.evaluated_get(depsgraph)
        tmp    = eval_s.to_mesh()
        if tmp and tmp.vertices:
            mw = s.matrix_world
            for v in tmp.vertices:
                stroke_points.append(mw @ v.co)
        eval_s.to_mesh_clear()

    if not stroke_points:
        return 0

    # ── Step 2: KD-Tree from stroke points ────────────────────────────────
    kd = KDTree(len(stroke_points))
    for i, pt in enumerate(stroke_points):
        kd.insert(pt, i)
    kd.balance()

    # ── Step 3: BVH of target — for re-projection onto surface ───────────
    eval_target = target_obj.evaluated_get(depsgraph)
    target_bvh  = BVHTree.FromObject(eval_target, depsgraph)

    # ── Step 4: edit result mesh via BMesh ────────────────────────────────
    bm = bmesh.new()
    bm.from_mesh(result_obj.data)
    bm.verts.ensure_lookup_table()

    snap_radius = props.stroke_snap_radius
    mat_world   = result_obj.matrix_world
    mat_inv     = mat_world.inverted()
    snapped     = 0

    for v in bm.verts:
        world_co = mat_world @ v.co
        nearest_co, _, dist = kd.find(world_co)
        if dist >= snap_radius:
            continue
        # Quadratic falloff: strength=1 at dist=0, strength=0 at dist=snap_radius
        weight  = (1.0 - dist / snap_radius) ** 2
        # Re-project stroke position onto high-poly surface
        hit_loc, _, _, _ = target_bvh.find_nearest(nearest_co)
        if hit_loc:
            snapped_co = mat_inv @ hit_loc
            v.co = v.co.lerp(snapped_co, weight)
            snapped += 1

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(result_obj.data)
    bm.free()
    result_obj.data.update()
    return snapped


def apply_stroke_guidance_field(context, result_obj, target_obj):
    """
    Post-process after remesh: aligns edge direction to the tangent of the
    nearest stroke (Field / Approximate mode).

    Instead of pulling the vertex TO the stroke line, it reduces the component
    of the vector perpendicular to the stroke tangent — the vertex moves
    ALONG the stroke rather than ONTO it. Effect: quad flow follows the
    stroke direction without creating hard edge loops.

    Returns the number of modified vertices.
    """
    from mathutils.kdtree import KDTree
    from mathutils.bvhtree import BVHTree

    props   = context.scene.retopo_props
    strokes = get_stroke_objects(context)
    if not strokes:
        return 0

    # ── Step 1: sample strokes — collect (midpoint, tangent) pairs ────────
    # Converting bezier to mesh gives a sequence of vertices; the segment
    # tangent is the normalized difference between consecutive points.
    stroke_segments = []  # list of (p0, p1, tangent) — full segment
    depsgraph = context.evaluated_depsgraph_get()
    for s in strokes:
        eval_s = s.evaluated_get(depsgraph)
        tmp = eval_s.to_mesh()
        if tmp and len(tmp.vertices) >= 2:
            mw   = s.matrix_world
            pts  = [mw @ v.co for v in tmp.vertices]
            for i in range(len(pts) - 1):
                p0, p1 = pts[i], pts[i + 1]
                seg_dir = p1 - p0
                if seg_dir.length < 1e-6:
                    continue
                tangent = seg_dir.normalized()
                stroke_segments.append((p0, p1, tangent))
        eval_s.to_mesh_clear()

    if not stroke_segments:
        return 0

    # ── Step 2: KD-Tree from segment midpoints (for nearest-neighbor lookup) ──
    kd = KDTree(len(stroke_segments))
    for i, (p0, p1, _) in enumerate(stroke_segments):
        kd.insert((p0 + p1) * 0.5, i)
    kd.balance()

    # ── Step 3: BVH of target — for re-projection onto surface ───────────
    eval_target = target_obj.evaluated_get(depsgraph)
    target_bvh  = BVHTree.FromObject(eval_target, depsgraph)

    # ── Step 4: edit result mesh via BMesh ────────────────────────────────
    bm = bmesh.new()
    bm.from_mesh(result_obj.data)
    bm.verts.ensure_lookup_table()

    field_radius  = props.stroke_field_radius
    strength      = props.stroke_field_strength
    mat_world     = result_obj.matrix_world
    mat_inv       = mat_world.inverted()
    influenced    = 0

    for v in bm.verts:
        world_co = mat_world @ v.co
        nearest_mid, idx, dist = kd.find(world_co)
        if dist > field_radius:
            continue

        seg_p0, seg_p1, tangent = stroke_segments[idx]

        # Linear falloff: full strength at dist=0, zero at dist=field_radius
        weight = (1.0 - dist / field_radius) * strength

        # Closest point on segment (t in [0,1]) — avoids infinite-line artifacts
        ab = seg_p1 - seg_p0
        t  = max(0.0, min(1.0, (world_co - seg_p0).dot(ab) / ab.dot(ab)))
        foot = seg_p0 + t * ab
        # perp = vector from vertex TO stroke line (perpendicular to tangent)
        perp = foot - world_co

        # Move vertex along perp by weight
        new_co = world_co + perp * weight

        # Re-project onto high-poly surface
        hit_loc, _, _, _ = target_bvh.find_nearest(new_co)
        if hit_loc:
            v.co = mat_inv @ hit_loc
            influenced += 1

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(result_obj.data)
    bm.free()
    result_obj.data.update()
    return influenced


# ─────────────────────────────────────────────────────────────────────────────
# OPERATOR: BAKE CURVATURE MAP  (#3)
# ─────────────────────────────────────────────────────────────────────────────

class RETOPO_OT_BakeCurvatureMap(bpy.types.Operator):
    """Paints Gaussian curvature as Vertex Colors on the High-Poly Target"""
    bl_idname  = "retopo.bake_curvature"
    bl_label   = "Bake Curvature Map"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.retopo_props
        if not _obj_in_scene(props.target_object):
            props.target_object = None
            self.report({'WARNING'}, "Select a High-Poly Target!")
            return {'CANCELLED'}
        layer = bake_curvature_density(props.target_object)
        mesh  = props.target_object.data
        if mesh.vertex_colors:
            mesh.vertex_colors.active = mesh.vertex_colors[layer]
        self.report({'INFO'}, f"Curvature baked -> layer '{layer}' "
                              f"(red=dense, blue=sparse)")
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────────────────
# OPERATOR: DRAW STROKE
# ─────────────────────────────────────────────────────────────────────────────

class RETOPO_OT_DrawStroke(bpy.types.Operator):
    """Hold LMB and draw a line on the model"""
    bl_idname  = "retopo.draw_stroke"
    bl_label   = "Draw Stroke"
    bl_options = {'REGISTER', 'UNDO'}

    @staticmethod
    def _mirror_pt(pt, axis):
        if axis == 'X':
            return Vector((-pt.x,  pt.y,  pt.z))
        if axis == 'Y':
            return Vector(( pt.x, -pt.y,  pt.z))
        return     Vector(( pt.x,  pt.y, -pt.z))

    def modal(self, context, event):
        context.area.tag_redraw()
        props = context.scene.retopo_props

        if event.type == 'ESC':
            self.cancel(context)
            props.is_drawing = False
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.is_mouse_down = True

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.is_mouse_down = False
            if len(self.stroke_points) >= 2:
                self.finalize_stroke(context)
                props.is_drawing = False
                return {'FINISHED'}
            else:
                self.cancel(context)
                props.is_drawing = False
                return {'CANCELLED'}

        if event.type == 'MOUSEMOVE' and self.is_mouse_down:
            pt = self.get_surface_point(context, event.mouse_region_x,
                                        event.mouse_region_y)
            if pt and (not self.stroke_points or
                       (pt - self.stroke_points[-1]).length > self.min_distance):
                self.stroke_points.append(pt)
                self.update_curve(context)
                # Symmetry: add mirrored point
                props = context.scene.retopo_props
                if props.stroke_use_symmetry and self.mirror_curve_obj:
                    mpt = self._mirror_pt(pt, props.stroke_symmetry_axis)
                    # Snap to target surface if available
                    target = props.target_object
                    if target:
                        from mathutils.bvhtree import BVHTree
                        depsgraph  = context.evaluated_depsgraph_get()
                        eval_tgt   = target.evaluated_get(depsgraph)
                        bvh        = BVHTree.FromObject(eval_tgt, depsgraph)
                        hit, _, _, _ = bvh.find_nearest(mpt)
                        if hit:
                            mpt = hit
                    self.mirror_stroke_points.append(mpt)
                    self._update_mirror_curve()

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        # Initialize instance variables here (not in __init__) —
        # required by Blender 5.0 where operator __setattr__ is
        # hooked into RNA before the object is fully initialized.
        self.stroke_points        = []
        self.curve_obj            = None
        self.is_mouse_down        = False
        self.min_distance         = 0.005
        self.mirror_curve_obj     = None
        self.mirror_stroke_points = []

        if context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "Run in 3D Viewport!")
            return {'CANCELLED'}
        props = context.scene.retopo_props
        if not _obj_in_scene(props.target_object):
            props.target_object = None
            self.report({'WARNING'}, "Select a High-Poly Target!")
            return {'CANCELLED'}
        props.is_drawing = True
        self.create_empty_curve(context)
        if props.stroke_use_symmetry:
            self._create_mirror_curve(context, props)
        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, "Hold LMB and draw. Release to finish.")
        return {'RUNNING_MODAL'}

    def get_surface_point(self, context, x, y):
        target = context.scene.retopo_props.target_object
        if _obj_in_scene(target):
            hit = raycast_to_surface(context, x, y, target)
            if hit:
                return hit
        return fallback_to_plane(context, x, y, target)

    def create_empty_curve(self, context):
        props = context.scene.retopo_props
        props.stroke_counter += 1
        bpy.ops.curve.primitive_bezier_curve_add(
            radius=1, enter_editmode=False, align='WORLD', location=(0, 0, 0)
        )
        self.curve_obj = context.active_object
        self.curve_obj.name = f"Stroke_{props.stroke_counter:03d}"
        self.curve_obj.data.splines.clear()
        self.curve_obj.data.splines.new('BEZIER')
        self.curve_obj.data.resolution_u = 12
        self.curve_obj["is_retopo_stroke"] = True
        self.curve_obj.data.bevel_depth      = 0.008
        self.curve_obj.data.bevel_resolution = 3
        self.curve_obj.data.fill_mode        = 'FULL'
        mat = bpy.data.materials.new(name="Stroke_Blue")
        mat.diffuse_color = (0.0, 0.4, 1.0, 1.0)
        mat.use_nodes = False
        self.curve_obj.data.materials.append(mat)

    def update_curve(self, context):
        if not self.curve_obj or not self.stroke_points:
            return
        spline = self.curve_obj.data.splines[0]
        needed = len(self.stroke_points) - len(spline.bezier_points)
        if needed > 0:
            spline.bezier_points.add(needed)
        for i, pt in enumerate(self.stroke_points):
            bp = spline.bezier_points[i]
            bp.co = pt
            bp.handle_left_type = bp.handle_right_type = 'AUTO'

    def finalize_stroke(self, context):
        if self.curve_obj:
            self.curve_obj.data.splines[0].use_smooth = True
            self.report({'INFO'}, f"{self.curve_obj.name} ({len(self.stroke_points)}pt)")
        if self.mirror_curve_obj:
            self.mirror_curve_obj.data.splines[0].use_smooth = True

    def cancel(self, context):
        if self.curve_obj and self.curve_obj.name in bpy.data.objects:
            bpy.data.objects.remove(self.curve_obj, do_unlink=True)
        if self.mirror_curve_obj and self.mirror_curve_obj.name in bpy.data.objects:
            bpy.data.objects.remove(self.mirror_curve_obj, do_unlink=True)

    def _create_mirror_curve(self, context, props):
        props.stroke_counter += 1
        bpy.ops.curve.primitive_bezier_curve_add(
            radius=1, enter_editmode=False, align='WORLD', location=(0, 0, 0)
        )
        self.mirror_curve_obj = context.active_object
        self.mirror_curve_obj.name = f"Stroke_{props.stroke_counter:03d}_mirror"
        self.mirror_curve_obj.data.splines.clear()
        self.mirror_curve_obj.data.splines.new('BEZIER')
        self.mirror_curve_obj.data.resolution_u = 12
        self.mirror_curve_obj["is_retopo_stroke"] = True
        self.mirror_curve_obj.data.bevel_depth      = 0.008
        self.mirror_curve_obj.data.bevel_resolution = 3
        self.mirror_curve_obj.data.fill_mode        = 'FULL'
        mat = bpy.data.materials.new(name="Stroke_Mirror")
        mat.diffuse_color = (0.0, 0.8, 0.4, 1.0)   # green = mirror
        mat.use_nodes = False
        self.mirror_curve_obj.data.materials.append(mat)
        # restore focus to main curve
        context.view_layer.objects.active = self.curve_obj

    def _update_mirror_curve(self):
        if not self.mirror_curve_obj or not self.mirror_stroke_points:
            return
        spline = self.mirror_curve_obj.data.splines[0]
        needed = len(self.mirror_stroke_points) - len(spline.bezier_points)
        if needed > 0:
            spline.bezier_points.add(needed)
        for i, pt in enumerate(self.mirror_stroke_points):
            bp = spline.bezier_points[i]
            bp.co = pt
            bp.handle_left_type = bp.handle_right_type = 'AUTO'


# ─────────────────────────────────────────────────────────────────────────────
# OPERATOR: DELETE / CLEAR STROKES
# ─────────────────────────────────────────────────────────────────────────────

class RETOPO_OT_DeleteStroke(bpy.types.Operator):
    bl_idname  = "retopo.delete_stroke"
    bl_label   = "Delete Stroke"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props   = context.scene.retopo_props
        strokes = get_stroke_objects(context)
        if not strokes:
            return {'CANCELLED'}
        idx  = min(props.active_stroke_index, len(strokes) - 1)
        name = strokes[idx].name
        bpy.data.objects.remove(strokes[idx], do_unlink=True)
        props.active_stroke_index = max(0, idx - 1)
        props.is_drawing = False  # reset drawing flag
        self.report({'INFO'}, f"Deleted: {name}")
        return {'FINISHED'}


class RETOPO_OT_ClearStrokes(bpy.types.Operator):
    bl_idname  = "retopo.clear_strokes"
    bl_label   = "Clear All"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        strokes = get_stroke_objects(context)
        count   = len(strokes)
        for obj in strokes:
            bpy.data.objects.remove(obj, do_unlink=True)
        context.scene.retopo_props.stroke_counter = 0
        context.scene.retopo_props.is_drawing = False  # reset flag
        self.report({'INFO'}, f"Deleted {count} strokes")
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────────────────
# OPERATOR: RETOPOLOGY – three modes
# ─────────────────────────────────────────────────────────────────────────────

class RETOPO_OT_ExecuteRetopo(bpy.types.Operator):
    """Run retopology with the selected method"""
    bl_idname  = "retopo.execute_retopo"
    bl_label   = "RUN RETOPO"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props  = context.scene.retopo_props
        target = props.target_object

        if not _obj_in_scene(target):
            props.target_object = None
            self.report({'WARNING'}, "Target object does not exist — please select again.")
            return {'CANCELLED'}

        # ── Pre-pass: Mesh Healing (#18) ───────────────────────
        if props.use_mesh_healing:
            h = heal_mesh(target)
            parts = []
            if h['merged_verts'] > 0:
                parts.append(f"{h['merged_verts']} verts merged")
            if h['holes_filled'] > 0:
                parts.append(f"{h['holes_filled']} holes filled")
            if parts:
                self.report({'INFO'}, "Mesh Healing: " + ", ".join(parts))

        # ── Pre-pass: Curvature Density Map (#3) ───────────────
        if props.use_curvature_density:
            bake_curvature_density(target)

        # ── Pre-pass: Hard Edge Detection ──────────────────────
        if props.use_hard_edge_prepass:
            n = mark_hard_edges(target, props.hard_edge_angle)
            self.report({'INFO'}, f"Hard edges: {n} edges marked as crease")

        mode = props.retopo_mode

        if mode == 'VOXEL':
            result = self.retopo_voxel(context, props, target)
        elif mode == 'SHRINKWRAP':
            result = self.retopo_shrinkwrap(context, props, target)
        elif mode == 'DECIMATE':
            result = self.retopo_decimate(context, props, target)
        elif mode == 'QUADRIFLOW':
            result = self.retopo_quadriflow(context, props, target)
        elif mode == 'INSTANT_MESHES':
            result = self.retopo_instant_meshes(context, props, target)
        elif mode == 'QUADWILD':
            result = self.retopo_quadwild(context, props, target)
        else:
            result = None

        if result:
            # ── Post-pass: Stroke Guidance ──────────────────────
            # Guidance first — moves vertices toward strokes.
            if props.use_stroke_guidance and get_stroke_objects(context):
                if props.stroke_guidance_mode == 'FIELD':
                    snapped = apply_stroke_guidance_field(context, result, target)
                    if snapped:
                        self.report({'INFO'}, f"Field guidance: {snapped} vertices aligned")
                else:
                    snapped = apply_stroke_guidance(context, result, target)
                    if snapped:
                        self.report({'INFO'}, f"Snap guidance: {snapped} vertices snapped")

            # ── Post-pass: Laplacian Smooth + Re-project ────────
            # After guidance — relaxes stretched edges between
            # vertices near strokes and those further away,
            # while re-projecting back onto the high-poly surface.
            if props.use_smooth_reproject:
                smooth_reproject(
                    context, result, target,
                    props.smooth_reproject_iterations,
                    props.smooth_reproject_factor,
                )

            result.name = f"Retopo_{target.name}_{mode}"

            # ── Post-pass: Topology Metrics (#8) ────────────────
            props.last_metrics_valid = False
            if props.compute_quality_metrics:
                m = compute_topology_metrics(
                    result, target, context.evaluated_depsgraph_get()
                )
                if m:
                    props.last_metrics_quad_pct   = m['quad_pct']
                    props.last_metrics_poles       = m['n_poles']
                    props.last_metrics_avg_aspect  = m['avg_aspect']
                    props.last_metrics_avg_angle   = m['avg_angle_score']
                    props.last_metrics_avg_dist    = m['avg_dist']
                    props.last_metrics_valid       = True

            # ── Post-pass: LOD Chain (#6) ────────────────────────
            if props.generate_lod:
                lod_col = generate_lod_chain(context, result, props.lod_levels)
                self.report({'INFO'}, f"LOD chain -> collection '{lod_col.name}'")
                # result was renamed inside generate_lod_chain
                result = bpy.data.objects.get(f"{result.name}_LOD0") or result

            bpy.ops.object.select_all(action='DESELECT')
            result.select_set(True)
            context.view_layer.objects.active = result
            v = len(result.data.vertices)
            f = len(result.data.polygons)
            self.report({'INFO'}, f"Done! {v} verts, {f} faces — [{mode}]")
            return {'FINISHED'}

        self.report({'ERROR'}, "Retopo failed")
        return {'CANCELLED'}

    # ── MODE 1: Voxel Remesh ────────────────────────────────────

    def retopo_voxel(self, context, props, target):
        """
        Duplicate target -> Voxel Remesh.
        Fastest mode, automatic mesh over the entire model.
        """
        # Temporarily show object if hidden (duplicate requires visibility)
        was_hidden = target.hide_get()
        was_hidden_viewport = target.hide_viewport
        target.hide_set(False)
        target.hide_viewport = False

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target
        bpy.ops.object.duplicate(linked=False)
        result = context.active_object

        # Restore original visibility
        target.hide_set(was_hidden)
        target.hide_viewport = was_hidden_viewport

        mod = result.modifiers.new("VoxelRemesh", 'REMESH')
        mod.mode        = 'VOXEL'
        mod.voxel_size  = props.voxel_size
        mod.adaptivity  = props.voxel_adaptivity
        bpy.ops.object.modifier_apply(modifier="VoxelRemesh")

        self.report({'INFO'}, f"Voxel size: {props.voxel_size}")
        return result

    # ── MODE 2: Remesh + Shrinkwrap ─────────────────────────────

    def retopo_shrinkwrap(self, context, props, target):
        """
        Duplicate target -> Voxel Remesh (coarse) -> Shrinkwrap back
        onto the original -> result: clean mesh tightly fitting the high-poly.
        """
        was_hidden = target.hide_get()
        was_hidden_viewport = target.hide_viewport
        target.hide_set(False)
        target.hide_viewport = False

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target
        bpy.ops.object.duplicate(linked=False)
        result = context.active_object

        target.hide_set(was_hidden)
        target.hide_viewport = was_hidden_viewport

        # Step 1: Remesh — coarse mesh
        mod_remesh = result.modifiers.new("Remesh", 'REMESH')
        mod_remesh.mode       = 'VOXEL'
        mod_remesh.voxel_size = props.voxel_size
        mod_remesh.adaptivity = props.voxel_adaptivity
        bpy.ops.object.modifier_apply(modifier="Remesh")

        # Step 2: Shrinkwrap — fit to original
        mod_sw = result.modifiers.new("Shrinkwrap", 'SHRINKWRAP')
        mod_sw.target                 = target
        mod_sw.wrap_method            = 'NEAREST_SURFACEPOINT'
        mod_sw.use_negative_direction = True
        mod_sw.use_positive_direction = True
        mod_sw.offset                 = props.shrinkwrap_offset
        bpy.ops.object.modifier_apply(modifier="Shrinkwrap")

        # Step 3: Smooth — smooth the result
        bpy.ops.object.shade_smooth()

        return result

    # ── MODE 3: Decimate ────────────────────────────────────────

    def retopo_decimate(self, context, props, target):
        """
        Duplicate target -> Decimate.
        Preserves original topology, only reduces poly count.
        Best when the original already has good topology.
        """
        was_hidden = target.hide_get()
        was_hidden_viewport = target.hide_viewport
        target.hide_set(False)
        target.hide_viewport = False

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target
        bpy.ops.object.duplicate(linked=False)
        result = context.active_object

        target.hide_set(was_hidden)
        target.hide_viewport = was_hidden_viewport

        mod = result.modifiers.new("Decimate", 'DECIMATE')
        mod.ratio           = props.decimate_ratio
        mod.use_collapse_triangulate = False
        bpy.ops.object.modifier_apply(modifier="Decimate")

        return result

    # ── MODE 4: Quadriflow ──────────────────────────────────────

    def retopo_quadriflow(self, context, props, target):
        """
        Duplicate target -> Quadriflow Remesh.
        Builds a clean quad mesh respecting curvature — slower than
        Voxel, but produces much better topology suitable for animation.
        """
        was_hidden          = target.hide_get()
        was_hidden_viewport = target.hide_viewport
        target.hide_set(False)
        target.hide_viewport = False

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target
        bpy.ops.object.duplicate(linked=False)
        result = context.active_object

        target.hide_set(was_hidden)
        target.hide_viewport = was_hidden_viewport

        bpy.ops.object.quadriflow_remesh(
            target_faces       = props.quadriflow_faces,
            seed               = 0,
            use_preserve_sharp = props.quadriflow_preserve_sharp,
            use_preserve_boundary = props.quadriflow_preserve_boundary,
            use_mesh_symmetry  = props.quadriflow_use_symmetry,
            smooth_normals     = props.quadriflow_smooth_normals,
        )

        bpy.ops.object.shade_smooth()
        self.report({'INFO'}, f"Quadriflow: {props.quadriflow_faces} target faces")
        return result

    # ── MODE 5: Instant Meshes ──────────────────────────────────

    def retopo_instant_meshes(self, context, props, target):
        """
        Exports target to OBJ -> runs Instant Meshes as a subprocess
        -> imports result. Best automatic topology with edge loops.
        Requires the Instant Meshes binary to be installed.
        """
        im_path = _get_im_path(props)
        if not im_path:
            self.report({'WARNING'},
                        "Provide the path to Instant Meshes (Binary field) "
                        "or set the default in: Edit -> Preferences -> Add-ons -> Retopo Stroke Tool")
            return None
        if not os.path.isfile(im_path):
            self.report({'ERROR'}, f"File not found: {im_path}")
            return None

        tmp_dir = tempfile.gettempdir()
        tmp_in  = os.path.join(tmp_dir, "retopo_im_input.obj")
        tmp_out = os.path.join(tmp_dir, "retopo_im_output.obj")

        # Export target to OBJ
        was_hidden          = target.hide_get()
        was_hidden_viewport = target.hide_viewport
        target.hide_set(False)
        target.hide_viewport = False

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target

        try:
            # Blender 4.x
            bpy.ops.wm.obj_export(
                filepath=tmp_in,
                export_selected_objects=True,
                export_uv=False,
                export_materials=False,
            )
        except AttributeError:
            # Blender 3.x
            bpy.ops.export_scene.obj(
                filepath=tmp_in,
                use_selection=True,
                use_uvs=False,
                use_materials=False,
            )

        target.hide_set(was_hidden)
        target.hide_viewport = was_hidden_viewport

        # Run Instant Meshes
        cmd = [
            im_path,
            tmp_in,
            "-o",  tmp_out,
            "-f",  str(props.instant_meshes_faces),
            "-c",  str(props.instant_meshes_crease),
            "-S",  str(props.instant_meshes_smooth),
        ]
        if props.instant_meshes_dominant:
            cmd.append("-D")
        if props.instant_meshes_boundaries:
            cmd.append("-b")
        if props.instant_meshes_deterministic:
            cmd.append("-d")
        if props.instant_meshes_threads > 0:
            cmd += ["-t", str(props.instant_meshes_threads)]
        try:
            proc = subprocess.run(cmd, timeout=180, capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            self.report({'ERROR'}, "Instant Meshes: timeout (>180s)")
            return None
        except OSError as e:
            self.report({'ERROR'}, f"Cannot run Instant Meshes: {e}")
            return None

        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "no details")[:200]
            self.report({'ERROR'}, f"Instant Meshes error (code {proc.returncode}): {msg}")
            return None

        if not os.path.isfile(tmp_out):
            self.report({'ERROR'}, "Instant Meshes did not write an output file")
            return None

        # Import result
        before = set(o.name for o in bpy.data.objects)
        try:
            # Blender 4.x
            bpy.ops.wm.obj_import(filepath=tmp_out)
        except AttributeError:
            # Blender 3.x
            bpy.ops.import_scene.obj(filepath=tmp_out)

        new_names = set(o.name for o in bpy.data.objects) - before
        if not new_names:
            self.report({'ERROR'}, "Import of Instant Meshes result failed")
            return None

        result = bpy.data.objects[next(iter(new_names))]

        # Clean up temporary files
        for f in (tmp_in, tmp_out):
            try:
                os.remove(f)
            except OSError:
                pass

        bpy.ops.object.shade_smooth()
        return result

    # ── MODE 6: QuadWild ────────────────────────────────────────

    @staticmethod
    def _qremeshify_available():
        """Checks whether the QRemeshify addon is registered in Blender."""
        return (hasattr(bpy.ops, 'qremeshify') and
                hasattr(bpy.ops.qremeshify, 'remesh') and
                hasattr(bpy.types.Scene, 'quadwild_props'))

    def retopo_quadwild(self, context, props, target):
        """
        Mode 6: QuadWild — closest quality to ZRemesher, open-source solver.

        Path A (priority): QRemeshify addon installed ->
            bpy.ops.qremeshify.remesh() with bundled binary.
        Path B (fallback): manual path to quadwild-bimdf binary (subprocess).
        """
        import math

        if self._qremeshify_available():
            return self._retopo_quadwild_via_qremeshify(context, props, target)
        else:
            return self._retopo_quadwild_via_binary(context, props, target, math)

    def _retopo_quadwild_via_qremeshify(self, context, props, target):
        """Path A: calls bpy.ops.qremeshify.remesh() when the addon is installed."""
        import math

        # Set parameters in scene.quadwild_props (QRemeshify reads from there)
        qw_props = context.scene.quadwild_props
        qw_props.enableSharp  = True
        qw_props.sharpAngle   = math.degrees(props.quadwild_sharp_angle)
        qw_props.enableRemesh = True
        qw_props.enableSmoothing = True

        # scaleFact in quadpatches_props controls quad size
        context.scene.quadpatches_props.scaleFact = props.quadwild_scale_fact

        # Activate target before calling the operator
        was_hidden          = target.hide_get()
        was_hidden_viewport = target.hide_viewport
        target.hide_set(False)
        target.hide_viewport = False

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target

        before = set(o.name for o in bpy.data.objects)

        try:
            result_op = bpy.ops.qremeshify.remesh()
        except Exception as e:
            self.report({'ERROR'}, f"QRemeshify error: {e}")
            target.hide_set(was_hidden)
            target.hide_viewport = was_hidden_viewport
            return None

        target.hide_set(was_hidden)
        target.hide_viewport = was_hidden_viewport

        if result_op == {'CANCELLED'}:
            self.report({'ERROR'}, "QRemeshify cancelled the operation — check selection and object mode")
            return None

        new_names = set(o.name for o in bpy.data.objects) - before
        if not new_names:
            self.report({'ERROR'}, "QRemeshify did not create a new object")
            return None

        result = bpy.data.objects[next(iter(new_names))]
        self.report({'INFO'},
                    f"QuadWild via QRemeshify — scaleFact={props.quadwild_scale_fact:.2f}")
        return result

    def _retopo_quadwild_via_binary(self, context, props, target, math):
        """Path B: calls the quadwild-bimdf binary via subprocess (fallback)."""
        qw_path = props.quadwild_path.strip()
        if not qw_path:
            self.report({'WARNING'},
                        "QuadWild: install the QRemeshify addon (github.com/ksami/QRemeshify) "
                        "OR provide the path to the quadwild-bimdf binary in the field below")
            return None
        if not os.path.isfile(qw_path):
            self.report({'ERROR'}, f"QuadWild: file not found: {qw_path}")
            return None

        tmp_dir = tempfile.gettempdir()
        tmp_in  = os.path.join(tmp_dir, "retopo_qw_input.obj")
        tmp_out = os.path.join(tmp_dir, "retopo_qw_input_quadwild.obj")

        was_hidden          = target.hide_get()
        was_hidden_viewport = target.hide_viewport
        target.hide_set(False)
        target.hide_viewport = False

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target

        try:
            bpy.ops.wm.obj_export(
                filepath=tmp_in,
                export_selected_objects=True,
                export_uv=False,
                export_materials=False,
            )
        except AttributeError:
            bpy.ops.export_scene.obj(
                filepath=tmp_in,
                use_selection=True,
                use_uvs=False,
                use_materials=False,
            )

        target.hide_set(was_hidden)
        target.hide_viewport = was_hidden_viewport

        sharp_deg = math.degrees(props.quadwild_sharp_angle)
        cmd = [qw_path, tmp_in, "-f", str(props.quadwild_faces), "-c", str(int(sharp_deg))]
        try:
            proc = subprocess.run(cmd, timeout=300, capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            self.report({'ERROR'}, "QuadWild: timeout (>300s) — try reducing Target Faces")
            return None
        except OSError as e:
            self.report({'ERROR'}, f"Cannot run QuadWild: {e}")
            return None

        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "no details")[:200]
            self.report({'ERROR'}, f"QuadWild error (code {proc.returncode}): {msg}")
            return None

        if not os.path.isfile(tmp_out):
            candidates = [
                tmp_in.replace('.obj', '_quadwild.obj'),
                tmp_in.replace('.obj', '_out.obj'),
                tmp_in.replace('_input.obj', '_output.obj'),
            ]
            tmp_out = next((p for p in candidates if os.path.isfile(p)), None)
            if not tmp_out:
                self.report({'ERROR'},
                            "QuadWild did not write an output file — "
                            "check that this is the quadwild-bimdf binary (not an older version)")
                return None

        before = set(o.name for o in bpy.data.objects)
        try:
            bpy.ops.wm.obj_import(filepath=tmp_out)
        except AttributeError:
            bpy.ops.import_scene.obj(filepath=tmp_out)

        new_names = set(o.name for o in bpy.data.objects) - before
        if not new_names:
            self.report({'ERROR'}, "Import of QuadWild result failed")
            return None

        result = bpy.data.objects[next(iter(new_names))]

        for f in (tmp_in, tmp_out):
            try:
                os.remove(f)
            except OSError:
                pass

        bpy.ops.object.shade_smooth()
        self.report({'INFO'}, f"QuadWild (binary): {props.quadwild_faces} target faces")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# UI PANEL
# ─────────────────────────────────────────────────────────────────────────────

class RETOPO_PT_MainPanel(bpy.types.Panel):
    bl_label       = "Retopo Tool v2"
    bl_idname      = "RETOPO_PT_main"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'Retopo Tool'

    def draw(self, context):
        layout  = self.layout
        props   = context.scene.retopo_props
        strokes = get_stroke_objects(context)

        # ── Target ─────────────────────────────────────────────
        box = layout.box()
        box.label(text="Model", icon='MESH_DATA')
        box.prop(props, "target_object", text="High-Poly")

        layout.separator()

        # ── Retopo Mode ────────────────────────────────────────
        box = layout.box()
        box.label(text="Retopo Method", icon='MOD_REMESH')
        box.prop(props, "retopo_mode", expand=True)

        layout.separator()

        # ── Density Preset ─────────────────────────────────────
        box = layout.box()
        box.label(text="Mesh Density", icon='MESH_GRID')
        box.prop(props, "density_preset", expand=True)

        # Mode-dependent parameters
        mode = props.retopo_mode
        if props.density_preset == 'CUSTOM' or True:
            sub = box.column(align=True)
            if mode in ('VOXEL', 'SHRINKWRAP'):
                sub.prop(props, "voxel_size", slider=True)
            if mode == 'SHRINKWRAP':
                sub.prop(props, "shrinkwrap_offset", slider=True)
            if mode == 'DECIMATE':
                sub.prop(props, "decimate_ratio", slider=True)
            if mode in ('VOXEL', 'SHRINKWRAP'):
                sub.prop(props, "voxel_adaptivity", slider=True)
            if mode == 'QUADRIFLOW':
                sub.prop(props, "quadriflow_faces")
                sub.separator()
                sub.prop(props, "quadriflow_preserve_sharp")
                sub.prop(props, "quadriflow_preserve_boundary")
                sub.prop(props, "quadriflow_use_symmetry")
                sub.prop(props, "quadriflow_smooth_normals")
            if mode == 'INSTANT_MESHES':
                sub.prop(props, "instant_meshes_faces")
            if mode == 'QUADWILD':
                qremeshify_ok = RETOPO_OT_ExecuteRetopo._qremeshify_available()
                if qremeshify_ok:
                    sub.prop(props, "quadwild_scale_fact", slider=True)
                else:
                    sub.prop(props, "quadwild_faces")
                sub.prop(props, "quadwild_sharp_angle")

        if mode == 'QUADWILD':
            qw_box = layout.box()
            qw_box.label(text="QuadWild", icon='OUTLINER_OB_CURVES')
            qremeshify_ok = RETOPO_OT_ExecuteRetopo._qremeshify_available()
            if qremeshify_ok:
                qw_box.label(text="QRemeshify installed — binary bundled", icon='CHECKMARK')
                qw_box.prop(props, "quadwild_scale_fact", slider=True)
            else:
                qw_box.label(text="QRemeshify not found — provide binary manually", icon='INFO')
                qw_box.prop(props, "quadwild_path", text="Binary (quadwild-bimdf)")
                if not props.quadwild_path.strip():
                    col = qw_box.column(align=False)
                    col.label(text="Binary not set", icon='ERROR')
                    col.label(text="Option 1: install QRemeshify addon (no binary needed)", icon='URL')
                    col.label(text="Option 2: download quadwild-bimdf from github.com/nicopietroni", icon='URL')
                else:
                    qw_box.label(
                        text=f"Binary: {os.path.basename(props.quadwild_path.strip())}",
                        icon='CHECKMARK'
                    )

        if mode == 'INSTANT_MESHES':
            im_box = layout.box()
            im_box.label(text="Instant Meshes", icon='EXPORT')

            # Per-scene path field (optional — overrides preferences)
            path_row = im_box.row(align=True)
            path_row.prop(props, "instant_meshes_path", text="Binary")
            path_row.operator("retopo.save_im_path", text="", icon='BOOKMARKS')

            # Effective path status
            effective = _get_im_path(props)
            if not effective:
                im_box.label(text="Path not set — enter above or in Preferences", icon='ERROR')
                im_box.label(text="Download: meshlab.github.io/instant-meshes", icon='INFO')
            elif not props.instant_meshes_path.strip():
                im_box.label(text=f"Default: {os.path.basename(effective)}", icon='CHECKMARK')

            col = im_box.column(align=True)
            col.prop(props, "instant_meshes_crease", slider=True)
            col.prop(props, "instant_meshes_smooth", slider=True)
            col.prop(props, "instant_meshes_dominant")
            col.separator()
            col.prop(props, "instant_meshes_boundaries")
            col.prop(props, "instant_meshes_deterministic")
            col.prop(props, "instant_meshes_threads")

        # Estimated poly count preview
        self._draw_poly_estimate(box, props)

        layout.separator()

        # ── Edge Loops (optional) ───────────────────────────────
        box = layout.box()
        row = box.row()
        row.label(text=f"Edge Loops ({len(strokes)})", icon='CURVE_BEZCURVE')

        if not _obj_in_scene(props.target_object):
            box.label(text="Select a Target to draw", icon='INFO')
        elif props.is_drawing:
            box.label(text="Drawing active...", icon='REC')
        else:
            btn = box.row()
            btn.scale_y = 1.4
            btn.operator("retopo.draw_stroke",
                         text="+ Draw Edge Loop",
                         icon='CURVE_BEZCURVE')
            # Symmetry
            sym_row = box.row(align=True)
            sym_row.prop(props, "stroke_use_symmetry", toggle=True, icon='MOD_MIRROR')
            if props.stroke_use_symmetry:
                sym_row.prop(props, "stroke_symmetry_axis", expand=True)

        if strokes:
            box.template_list(
                "RETOPO_UL_StrokeList", "",
                bpy.data, "objects",
                props, "active_stroke_index",
                rows=3, maxrows=5,
            )
            row = box.row(align=True)
            row.operator("retopo.delete_stroke",   text="Delete",  icon='X')
            row.operator("retopo.clear_strokes",   text="Clear",   icon='TRASH')

            # ── Stroke Guidance — hidden for DECIMATE ───────────
            if mode != 'DECIMATE':
                guidance_row = box.row()
                guidance_row.prop(
                    props, "use_stroke_guidance",
                    text="Use as Guidance",
                    icon='FORCE_MAGNETIC',
                    toggle=True,
                )
                if props.use_stroke_guidance:
                    mode_row = box.row(align=True)
                    mode_row.prop(props, "stroke_guidance_mode", expand=True)
                    if props.stroke_guidance_mode == 'SNAP':
                        box.prop(props, "stroke_snap_radius", slider=True)
                    else:
                        box.prop(props, "stroke_field_radius", slider=True)
                        box.prop(props, "stroke_field_strength", slider=True)

        layout.separator()

        # ── Advanced ────────────────────────────────────────────
        box = layout.box()
        box.label(text="Advanced", icon='SETTINGS')

        # Mesh Healing — always shown
        col_heal = box.column(align=True)
        col_heal.prop(props, "use_mesh_healing", toggle=True, icon='TOOL_SETTINGS')

        # Curvature Density Map — hidden for DECIMATE
        if mode != 'DECIMATE':
            box.separator()
            col0 = box.column(align=True)
            row0 = col0.row(align=True)
            row0.prop(props, "use_curvature_density", toggle=True, icon='COLORSET_01_VEC')
            row0.operator("retopo.bake_curvature", text="Bake Now", icon='VPAINT_HLT')

        # Hard Edge Pre-pass — only QUADRIFLOW and INSTANT_MESHES
        if mode in ('QUADRIFLOW', 'INSTANT_MESHES'):
            box.separator()
            col = box.column(align=True)
            col.prop(props, "use_hard_edge_prepass", toggle=True, icon='EDGESEL')
            if props.use_hard_edge_prepass:
                col.prop(props, "hard_edge_angle", slider=True)

        # Smooth + Re-project — hidden for DECIMATE and SHRINKWRAP
        if mode not in ('DECIMATE', 'SHRINKWRAP'):
            box.separator()
            col2 = box.column(align=True)
            col2.prop(props, "use_smooth_reproject", toggle=True, icon='MOD_SMOOTH')
            if props.use_smooth_reproject:
                col2.prop(props, "smooth_reproject_iterations", slider=True)
                col2.prop(props, "smooth_reproject_factor",     slider=True)

        box.separator()

        # LOD Chain — always shown
        col3 = box.column(align=True)
        col3.prop(props, "generate_lod", toggle=True, icon='RENDERLAYERS')
        if props.generate_lod:
            col3.prop(props, "lod_levels", slider=True)

        box.separator()

        # Quality Metrics — always shown
        col4 = box.column(align=True)
        col4.prop(props, "compute_quality_metrics", toggle=True, icon='VIEWZOOM')

        layout.separator()

        # ── MAIN BUTTON ─────────────────────────────────────────
        box = layout.box()

        # Status
        if not _obj_in_scene(props.target_object):
            box.label(text="Select a model above", icon='ERROR')
        else:
            mode_labels = {
                'VOXEL':          "Voxel Remesh",
                'SHRINKWRAP':     "Remesh + Shrinkwrap",
                'DECIMATE':       "Decimate",
                'QUADRIFLOW':     "Quadriflow",
                'INSTANT_MESHES': "Instant Meshes",
                'QUADWILD':       "QuadWild",
            }
            box.label(
                text=f"Mode: {mode_labels[mode]}",
                icon='INFO'
            )

        btn = box.row()
        btn.scale_y = 2.2
        btn.enabled = props.target_object is not None and not props.is_drawing
        btn.operator("retopo.execute_retopo",
                     text="▶  RUN RETOPO",
                     icon='MOD_REMESH')

        # ── Quality metrics (displayed after remesh) ────────────
        if props.last_metrics_valid:
            mbox = layout.box()
            mbox.label(text="Last Remesh Metrics", icon='VIEWZOOM')
            col = mbox.column(align=True)
            q = props.last_metrics_quad_pct
            q_icon = 'CHECKMARK' if q >= 95 else ('ERROR' if q < 80 else 'INFO')
            col.label(text=f"Quads:        {q:.1f}%",        icon=q_icon)
            col.label(text=f"Poles:        {props.last_metrics_poles}",
                      icon='VERTEXSEL')
            col.label(text=f"Aspect Ratio: {props.last_metrics_avg_aspect:.2f}",
                      icon='FULLSCREEN_ENTER')
            a_score = props.last_metrics_avg_angle
            a_icon  = 'CHECKMARK' if a_score >= 0.85 else ('ERROR' if a_score < 0.5 else 'INFO')
            col.label(text=f"Angle (Jacobian): {a_score:.2f}",
                      icon=a_icon)
            col.label(text=f"HP Deviation: {props.last_metrics_avg_dist*1000:.2f} mm",
                      icon='ARROW_LEFTRIGHT')

    def _draw_poly_estimate(self, layout, props):
        """Show estimated polygon count for the current settings"""
        mode = props.retopo_mode

        if mode in ('VOXEL', 'SHRINKWRAP'):
            vs = props.voxel_size
            if vs <= 0.03:
                est = "~3000-6000 faces (High)"
            elif vs <= 0.07:
                est = "~1000-3000 faces (Medium)"
            else:
                est = "~500-1000 faces (Game)"
        elif mode == 'DECIMATE':
            r = props.decimate_ratio
            est = f"~{int(r*100)}% of original faces"
        elif mode == 'QUADRIFLOW':
            est = f"~{props.quadriflow_faces} faces (quads)"
        elif mode == 'INSTANT_MESHES':
            est = f"~{props.instant_meshes_faces} faces (quads + edge loops)"
        else:
            est = ""

        if est:
            row = layout.row()
            row.label(text=est, icon='FUND')


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRATION
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# ADDON PREFERENCES — persistent settings outside the scene
# ─────────────────────────────────────────────────────────────────────────────

class RETOPO_AddonPreferences(bpy.types.AddonPreferences):
    """Settings saved in Blender preferences (userpref.blend).

    Accessible via: Edit -> Preferences -> Add-ons -> Retopo Stroke Tool."""
    bl_idname = __name__

    instant_meshes_path: bpy.props.StringProperty(
        name="Default Instant Meshes Path",
        description="Path to the Instant Meshes binary — saved globally, "
                    "loaded automatically in every new file",
        subtype='FILE_PATH',
        default=""
    )

    def draw(self, context):
        self.layout.prop(self, "instant_meshes_path")


def _get_im_path(props):
    """Returns the effective path to the Instant Meshes binary.
    Priority: (1) path in the current scene -> (2) default from AddonPreferences."""
    scene_path = props.instant_meshes_path.strip()
    if scene_path:
        return scene_path
    try:
        prefs = bpy.context.preferences.addons[__name__].preferences
        return prefs.instant_meshes_path.strip()
    except (KeyError, AttributeError):
        return ""


class RETOPO_OT_SaveImPath(bpy.types.Operator):
    """Saves the current Instant Meshes binary path as the default in addon preferences."""
    bl_idname  = "retopo.save_im_path"
    bl_label   = "Save as Default"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        props = context.scene.retopo_props
        path  = props.instant_meshes_path.strip()
        if not path:
            self.report({'WARNING'}, "Path field is empty — enter a path first.")
            return {'CANCELLED'}
        try:
            prefs = context.preferences.addons[__name__].preferences
            prefs.instant_meshes_path = path
            bpy.ops.wm.save_userpref()
            self.report({'INFO'}, f"Saved default path: {path}")
        except (KeyError, AttributeError):
            self.report({'ERROR'}, "Cannot save — addon must be installed (not just run as a script).")
            return {'CANCELLED'}
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────────────────

classes = [
    RETOPO_AddonPreferences,
    RetopoPipelineProps,
    RETOPO_UL_StrokeList,
    RETOPO_OT_BakeCurvatureMap,
    RETOPO_OT_DrawStroke,
    RETOPO_OT_DeleteStroke,
    RETOPO_OT_ClearStrokes,
    RETOPO_OT_SaveImPath,
    RETOPO_OT_ExecuteRetopo,
    RETOPO_PT_MainPanel,
]


@bpy.app.handlers.persistent
def _retopo_cleanup_handler(scene, depsgraph):
    """After each scene update, checks whether target_object still exists
    in the active scene. If not (object deleted with Delete in the viewport)
    — clears the reference to avoid exceptions on next tool use."""
    props = scene.retopo_props
    if props.target_object is not None and not _obj_in_scene(props.target_object):
        props.target_object = None


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.retopo_props = bpy.props.PointerProperty(
        type=RetopoPipelineProps
    )
    bpy.app.handlers.depsgraph_update_post.append(_retopo_cleanup_handler)


def unregister():
    if _retopo_cleanup_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_retopo_cleanup_handler)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.retopo_props


if __name__ == "__main__":
    register()
