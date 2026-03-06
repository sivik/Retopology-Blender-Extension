bl_info = {
    "name": "Retopo Stroke Tool",
    "author": "Retopo MCP",
    "version": (2, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > N-Panel > Retopo Tool",
    "description": "Retopologia z wyborem metody: Voxel, Shrinkwrap, Decimate",
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
# WŁAŚCIWOŚCI
# ─────────────────────────────────────────────────────────────────────────────

class RetopoPipelineProps(bpy.types.PropertyGroup):

    target_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="High-Poly Target",
        description="Model źródłowy do retopo"
    )

    # ── Tryb retopo ────────────────────────────────────────────
    retopo_mode: bpy.props.EnumProperty(
        name="Tryb Retopo",
        description="Wybierz metodę retopologii",
        items=[
            ('VOXEL',       "Voxel Remesh",
             "Szybki remesh voxelowy — automatyczna siatka na całym modelu",
             'MOD_REMESH', 0),
            ('SHRINKWRAP',  "Remesh + Shrinkwrap",
             "Remesh + dopasowanie do oryginału — dokładniejsze przyleganie",
             'MOD_SHRINKWRAP', 1),
            ('DECIMATE',    "Decimate",
             "Redukuje poly count zachowując oryginalną topologię",
             'MOD_DECIM', 2),
            ('QUADRIFLOW',     "Quadriflow",
             "Buduje czystą siatkę quadów z zachowaniem krzywizn — najlepsza jakość topologii",
             'OUTLINER_OB_SURFACE', 3),
            ('INSTANT_MESHES', "Instant Meshes",
             "Zewnętrzne narzędzie — świetna topologia z edge loopami (wymaga binarki IM)",
             'EXPORT', 4),
            ('QUADWILD', "QuadWild",
             "Najbliższy jakością ZRemesherowi open-source solver (wymaga binarki quadwild-bimdf)",
             'OUTLINER_OB_CURVES', 5),
        ],
        default='VOXEL'
    )

    # ── Ustawienia Voxel ───────────────────────────────────────
    voxel_size: bpy.props.FloatProperty(
        name="Voxel Size",
        default=0.05, min=0.001, max=1.0,
        description="Mniejszy = więcej polygonów"
    )

    # ── Ustawienia Decimate ────────────────────────────────────
    decimate_ratio: bpy.props.FloatProperty(
        name="Decimate Ratio",
        default=0.3, min=0.01, max=1.0,
        description="1.0 = bez zmian, 0.1 = 10% oryginalnych face'ów"
    )

    # ── Preset gęstości ────────────────────────────────────────
    density_preset: bpy.props.EnumProperty(
        name="Gęstość",
        description="Preset liczby polygonów",
        items=[
            ('GAME',   "Game  (~500-1000f)",   "Bardzo low-poly do gier real-time"),
            ('MEDIUM', "Medium (~1000-3000f)",  "Balans detalu i wydajności"),
            ('HIGH',   "High   (~3000-6000f)",  "Dużo detalu, do renderingu"),
            ('CUSTOM', "Custom",                "Ręczne ustawienie parametrów"),
        ],
        default='MEDIUM',
        update=lambda self, ctx: RetopoPipelineProps._apply_preset(self, ctx)
    )

    # ── Stroke'i ───────────────────────────────────────────────
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
        description="Po remeshu przyciąga wierzchołki do narysowanych stroke'ów"
    )
    stroke_snap_radius: bpy.props.FloatProperty(
        name="Snap Radius",
        default=0.05, min=0.001, max=0.5,
        description="Promień przyciągania wierzchołków do stroke'ów"
    )
    stroke_snap_strength: bpy.props.FloatProperty(
        name="Strength",
        default=1.0, min=0.0, max=1.0,
        description="Siła przyciągania (0 = brak efektu, 1 = pełne). "
                    "Zmniejsz przy dużym promieniu aby uniknąć nadmiernej deformacji siatki"
    )
    stroke_guidance_mode: bpy.props.EnumProperty(
        name="Tryb Guidance",
        description="Snap: przyciąga wierzchołki DO stroke'a. Field: wyrównuje kierunek krawędzi ze stroke'iem",
        items=[
            ('SNAP',   "Snap",   "Wierzchołki przeskakują na linię stroke'a (twarde edge loopy)",                          'SNAP_ON',       0),
            ('FIELD',  "Field",  "Krawędzie wyrównują się z tangentą stroke'a (miękkie prowadzenie)",                      'FORCE_MAGNETIC', 1),
            ('DIFFUSE',"Diffuse","Propaguje pole orientacji przez krawędzie siatki — gładkie globalne wyrównanie jak IM",  'BRUSH_SOFTEN',  2),
        ],
        default='SNAP'
    )
    stroke_field_strength: bpy.props.FloatProperty(
        name="Strength",
        default=0.5, min=0.0, max=1.0,
        description="Siła wyrównania krawędzi do kierunku stroke'a (0 = brak efektu, 1 = pełne wyrównanie)"
    )
    stroke_field_radius: bpy.props.FloatProperty(
        name="Influence Radius",
        default=0.15, min=0.001, max=1.0,
        description="Promień wpływu tangentowego pola stroke'a na otaczające wierzchołki"
    )
    stroke_diffusion_iterations: bpy.props.IntProperty(
        name="Diffusion Steps",
        default=10, min=1, max=30,
        description="Liczba kroków propagacji pola orientacji przez krawędzie siatki. "
                    "Więcej = dalszy zasięg od stroke'a, gładsze przejście na całym meshu"
    )

    # ── Ustawienia Instant Meshes ──────────────────────────────
    instant_meshes_path: bpy.props.StringProperty(
        name="Ścieżka do Instant Meshes",
        description="Pełna ścieżka do pliku wykonywalnego Instant Meshes",
        subtype='FILE_PATH',
        default=""
    )
    instant_meshes_faces: bpy.props.IntProperty(
        name="Target Faces",
        default=2000, min=100, max=50000,
        description="Docelowa liczba face'ów"
    )
    instant_meshes_crease: bpy.props.IntProperty(
        name="Crease Angle",
        default=30, min=0, max=90,
        description="Kąt w stopniach powyżej którego krawędź jest traktowana jako hard edge"
    )
    instant_meshes_smooth: bpy.props.IntProperty(
        name="Smooth Iterations",
        default=2, min=0, max=10,
        description="Liczba iteracji wygładzania siatki po remeshu"
    )
    instant_meshes_dominant: bpy.props.BoolProperty(
        name="Dominant Quads",
        default=False,
        description="Pozwala na trójkąty przy polach (dominant mode) — lepsze wyniki przy trudnej topologii"
    )
    instant_meshes_boundaries: bpy.props.BoolProperty(
        name="Align to Boundaries",
        default=False,
        description="Wyrównuje edge loopy do granicy otwartej siatki (-b). "
                    "Kluczowe przy retopo odciętych modeli: half-body, dłonie, elementy odzieży"
    )
    instant_meshes_deterministic: bpy.props.BoolProperty(
        name="Deterministyczny",
        default=False,
        description="Używa wolniejszego ale deterministycznego algorytmu (-d). "
                    "Ten sam model zawsze daje identyczny wynik — przydatne w pipeline produkcyjnym"
    )
    instant_meshes_threads: bpy.props.IntProperty(
        name="Wątki CPU",
        default=0, min=0, max=64,
        description="Liczba wątków CPU (-t). 0 = automatycznie (domyślne IM). "
                    "Zwiększ na maszynach wielordzeniowych dla przyspieszenia dużych meshów"
    )

    # ── Ustawienia QuadWild (#15) ──────────────────────────────
    quadwild_path: bpy.props.StringProperty(
        name="QuadWild Binary",
        description="Pełna ścieżka do pliku wykonywalnego QuadWild (quadwild-bimdf). "
                    "Używane gdy addon QRemeshify NIE jest zainstalowany",
        subtype='FILE_PATH',
        default=""
    )
    quadwild_faces: bpy.props.IntProperty(
        name="Target Faces",
        default=2000, min=100, max=50000,
        description="Docelowa liczba face'ów (tryb subprocess — gdy brak QRemeshify)"
    )
    quadwild_scale_fact: bpy.props.FloatProperty(
        name="Scale Factor",
        default=1.0, min=0.05, max=10.0,
        description="Rozmiar quadów: <1 = więcej detali (więcej poly), >1 = większe quady (mniej poly). "
                    "Używane przez QRemeshify addon (scaleFact)"
    )
    quadwild_sharp_angle: bpy.props.FloatProperty(
        name="Sharp Angle",
        default=30.0, min=1.0, max=180.0,
        subtype='ANGLE',
        description="Kąt powyżej którego krawędź jest traktowana jako ostra (przekazywany do QuadWild)"
    )

    # ── Mesh Healing (#18) ─────────────────────────────────────
    use_mesh_healing: bpy.props.BoolProperty(
        name="Mesh Healing",
        default=True,
        description="Przed remeshem: auto-naprawa siatki (Fill Holes, Remove Doubles, "
                    "Recalc Normals). Eliminuje główną przyczynę dziur po Voxel Remesh"
    )

    # ── Ustawienia Quadriflow ──────────────────────────────────
    quadriflow_faces: bpy.props.IntProperty(
        name="Target Faces",
        default=2000, min=100, max=50000,
        description="Docelowa liczba face'ów (przybliżona)"
    )
    quadriflow_use_curvature: bpy.props.BoolProperty(
        name="Uwzględnij krzywiznę",
        default=False,
        description="Zagęszcza siatkę tam gdzie krzywizna jest większa"
    )
    quadriflow_preserve_sharp: bpy.props.BoolProperty(
        name="Zachowaj Hard Edges",
        default=True,
        description="Wymusza edge loopy wzdłuż ostrych krawędzi (kluczowe dla hard-surface)"
    )
    quadriflow_preserve_boundary: bpy.props.BoolProperty(
        name="Zachowaj Granice",
        default=True,
        description="Wyrównuje edge loopy do granicy otwartej siatki"
    )
    quadriflow_use_symmetry: bpy.props.BoolProperty(
        name="Użyj Symetrii",
        default=False,
        description="Remeshuje jedną połowę i mirroruje — gwarantuje symetryczną topologię"
    )
    quadriflow_smooth_normals: bpy.props.BoolProperty(
        name="Wygładź Normale",
        default=False,
        description="Wygładza normale po remeshu"
    )

    # ── Hard Edge Detection ────────────────────────────────────
    use_hard_edge_prepass: bpy.props.BoolProperty(
        name="Hard Edge Pre-pass",
        default=False,
        description="Przed remeshem: oznacza krawędzie targetu jako creases wg kąta. "
                    "Respektowane przez Quadriflow (preserve_sharp) i Instant Meshes (--crease)"
    )
    hard_edge_angle: bpy.props.FloatProperty(
        name="Crease Angle",
        default=30.0, min=1.0, max=180.0,
        subtype='ANGLE',
        description="Krawędzie powyżej tego kąta będą oznaczone jako sharp/crease"
    )

    # ── Laplacian Smooth + Re-project ──────────────────────────
    use_smooth_reproject: bpy.props.BoolProperty(
        name="Smooth + Re-project",
        default=False,
        description="Po remeshu: iteracyjne Laplacian smooth + rzutowanie z powrotem "
                    "na high-poly. Wyrównuje rozkład wierzchołków i poprawia dopasowanie"
    )
    smooth_reproject_iterations: bpy.props.IntProperty(
        name="Iteracje",
        default=3, min=1, max=20,
        description="Liczba cykli smooth → re-project"
    )
    smooth_reproject_factor: bpy.props.FloatProperty(
        name="Smooth Factor",
        default=0.5, min=0.0, max=1.0,
        description="Siła Laplacian smooth per iterację"
    )

    # ── Ustawienia Voxel ───────────────────────────── (dodatkowe)
    voxel_adaptivity: bpy.props.FloatProperty(
        name="Adaptivity",
        default=0.0, min=0.0, max=1.0,
        description="Trianguluje płaskie obszary zmniejszając poly count. "
                    "Uwaga: wartość > 0 wyłącza Fix Poles"
    )

    # ── Curvature Density Map (#3) ─────────────────────────────
    use_curvature_density: bpy.props.BoolProperty(
        name="Curvature Pre-pass",
        default=False,
        description="Maluje krzywiznę Gaussa jako Vertex Colors na targecie "
                    "(analog Vertex Color Density Map z Quad Remeshera)"
    )

    # ── LOD Chain (#6) ─────────────────────────────────────────
    generate_lod: bpy.props.BoolProperty(
        name="Generuj LOD Chain",
        default=False,
        description="Po remeshu tworzy LOD0-LODn przez progressive Decimate "
                    "w dedykowanej kolekcji"
    )
    lod_levels: bpy.props.IntProperty(
        name="Poziomy LOD",
        default=3, min=2, max=4,
        description="Liczba poziomów: LOD0=full, LOD1=50%, LOD2=25%, LOD3=10%"
    )

    # ── Topology Quality Metrics (#8) ──────────────────────────
    compute_quality_metrics: bpy.props.BoolProperty(
        name="Metryki Jakości",
        default=False,
        description="Po remeshu oblicza: % quadów, poles, aspect ratio, "
                    "odchylenie od high-poly"
    )
    last_metrics_valid:      bpy.props.BoolProperty(default=False)
    last_metrics_quad_pct:   bpy.props.FloatProperty(default=0.0)
    last_metrics_poles:      bpy.props.IntProperty(default=0)
    last_metrics_avg_aspect: bpy.props.FloatProperty(default=0.0)
    last_metrics_avg_dist:   bpy.props.FloatProperty(default=0.0)
    last_metrics_avg_angle:  bpy.props.FloatProperty(default=0.0)

    # ── Stroke Symmetry (#9) ───────────────────────────────────
    stroke_use_symmetry: bpy.props.BoolProperty(
        name="Symetria",
        default=False,
        description="Tworzy lustrzany stroke po przeciwnej stronie wybranej osi"
    )
    stroke_symmetry_axis: bpy.props.EnumProperty(
        name="Oś",
        items=[
            ('X', "X", "Symetria względem osi X"),
            ('Y', "Y", "Symetria względem osi Y"),
            ('Z', "Z", "Symetria względem osi Z"),
        ],
        default='X'
    )

    # ── Shrinkwrap offset ──────────────────────────────────────
    shrinkwrap_offset: bpy.props.FloatProperty(
        name="Offset",
        default=0.001, min=0.0, max=0.1,
        description="Odległość od powierzchni oryginału"
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
# UIList – tylko stroke'i (filtruje Camera, Light itp.)
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
    """Zwraca True jeśli obiekt istnieje i jest powiązany z aktywną sceną.
    PointerProperty może trzymać referencję do orphan-obiektu (usuniętego
    klawiszem Delete w viewporcie) — ten helper odróżnia taki przypadek."""
    if obj is None:
        return False
    try:
        return bpy.context.scene.objects.get(obj.name) is obj
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# RAYCAST – przyklejanie linii do powierzchni
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
    Oblicza dwie miary krzywizny per vertex i zapisuje jako Vertex Colors:

    1. CurvatureDensity — krzywizna Gaussa (Gauss-Bonnet discrete):
         K = |2π - Σθⱼ| / Aᵢ   (Aᵢ = Voronoi area)
       Czerwony = duża krzywizna (ostre rogi), niebieski = płasko.

    2. MeanCurvature — krzywizna średnia (cotangent Laplacian):
         H = |Σ (cot α + cot β)(vⱼ - v)| / (2 Aᵢ)
       Lepiej wykrywa zagięcia i siodła (kąciki ust, łuk brwi).
       Czerwony = duże zagięcie, niebieski = płasko.

    Obie mapy są analogiem Vertex Color Density Map z Quad Remeshera.
    """
    import math

    bm = bmesh.new()
    bm.from_mesh(target_obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    # ── Warstwa 1: Gaussian curvature ──────────────────────────
    gauss_layer = bm.loops.layers.color.get("CurvatureDensity")
    if gauss_layer is None:
        gauss_layer = bm.loops.layers.color.new("CurvatureDensity")

    # ── Warstwa 2: Mean curvature ───────────────────────────────
    mean_layer = bm.loops.layers.color.get("MeanCurvature")
    if mean_layer is None:
        mean_layer = bm.loops.layers.color.new("MeanCurvature")

    # Cotangent weights per edge (dla mean curvature)
    cot_weights = {}
    for e in bm.edges:
        v0, v1 = e.verts
        w = 0.0
        for f in e.link_faces:
            opp_verts = [v for v in f.verts if v not in (v0, v1)]
            # Dla trójkąta: 1 wierzchołek naprzeciwko; dla quada: 2 → normalizuj
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
    Oblicza metryki jakości wynikowej siatki:
      - quad_pct        : % face'ów które są quadami          (cel: 100%)
      - n_poles         : vertices z valence != 4 (poza granicą) (cel: minimum)
      - avg_aspect      : średni aspect ratio face'ów          (cel: ~1.0)
      - avg_angle_score : min |sin θ| per quad (Scaled Jacobian)  (cel: ~1.0)
      - avg_dist        : średnie odchylenie od high-poly [m]  (cel: ~0.0)
    Zwraca dict lub {} przy pustej siatce.
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
        # Scaled Jacobian: min |sin θᵢ| po 4 kątach wewnętrznych quada
        # Idealny kwad: sin 90° = 1.0. Shear 30°/150°: sin 30° = 0.5
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
    Tworzy łańcuch LOD0–LODn przez progressive Decimate na kopiach result_obj.
    LOD0 = oryginał (bez zmian)
    LOD1 = 50%, LOD2 = 25%, LOD3 = 10% face'ów.
    Wszystkie trafiają do kolekcji 'LOD_{name}'.
    Zwraca kolekcję LOD.
    """
    base_name = result_obj.name
    col_name  = f"LOD_{base_name}"

    lod_col = bpy.data.collections.get(col_name)
    if not lod_col:
        lod_col = bpy.data.collections.new(col_name)
        context.scene.collection.children.link(lod_col)

    # Przenieś LOD0 do kolekcji
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
    Skanuje krawędzie target_obj i oznacza jako sharp + crease te, których
    kąt dwuścienny przekracza angle_deg. Respektowane przez:
    - Quadriflow: use_preserve_sharp
    - Instant Meshes: --crease parametr
    Zwraca liczbę oznaczonych krawędzi.
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
    Automatyczna naprawa siatki przed remeshem. Eliminuje najczęstsze przyczyny
    artefaktów (dziury po Voxel Remesh, odwrócone normale, zduplikowane verty).

    Operacje (w kolejności):
    1. Remove Doubles      — scala bliskie wierzchołki (dist=0.0001)
    2. Fill Holes          — wypełnia otwory w siatce (sides=4 = preferencja quadów)
    3. Recalc Face Normals — naprawia odwrócone normale

    Zwraca słownik z liczbą usuniętych/naprawionych elementów.
    """
    bm = bmesh.new()
    bm.from_mesh(target_obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    verts_before = len(bm.verts)

    # 1. Remove doubles
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0001)

    # 2. Fill holes — szuka otwartych krawędzi i próbuje zamknąć
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
    Jeden krok cotangent-weighted Laplacian smooth (czyste bmesh, bez Edit Mode).

    Przewaga nad uniform smooth (bpy.ops.mesh.vertices_smooth):
    - Nie powoduje skurczu geometrii (shrinkage bias) przy nieregularnej gęstości.
    - Krawędzie z małymi kątami naprzeciwko (cot→duże) mają większy wpływ —
      to odpowiada rzeczywistej geometrii siatki triangulated.
    - Bezpieczny dla siatek quadowych: quady są traktowane jak dwa trójkąty.

    Wzór: Lc(v) = Σⱼ wⱼ·(vⱼ - v) / Σⱼ wⱼ,   wⱼ = cot(αⱼ) + cot(βⱼ)
    """
    bm = bmesh.new()
    bm.from_mesh(result_obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    # Oblicz cotangent weight per edge
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
                    w += max(0.0, cot) / len(opp_verts)  # normalize dla quada
        cot_w[e.index] = w

    # Wyznacz nowe pozycje (wszystkie naraz, nie nadpisuj w locie)
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
    Iteracyjna pętla: Cotangent Laplacian smooth → rzutowanie z powrotem na BVH targetu.
    Cotangent smooth eliminuje shrinkage bias typowy dla uniform Laplacian —
    wierzchołki na gęstszych obszarach nie są nadmiernie przyciągane.
    """
    from mathutils.bvhtree import BVHTree

    depsgraph  = context.evaluated_depsgraph_get()
    eval_tgt   = target_obj.evaluated_get(depsgraph)
    target_bvh = BVHTree.FromObject(eval_tgt, depsgraph)

    mat_world = result_obj.matrix_world
    mat_inv   = mat_world.inverted()

    for _ in range(iterations):
        # Cotangent Laplacian smooth (bez Edit Mode — czyste bmesh)
        _cotangent_smooth_step(result_obj, factor)

        # Re-project — każdy wierzchołek z powrotem na powierzchnię targetu
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
    Post-process po remeshu: przyciąga wierzchołki wynikowej siatki do
    najbliższych punktów narysowanych stroke'ów, a następnie rzutuje je z
    powrotem na powierzchnię targetu (BVH).

    Efekt: wierzchołki blisko stroke'ów "przesuwają się" wzdłuż narysowanych
    linii, tworząc edge loopy które podążają za stroke'ami.

    Zwraca liczbę przyciągniętych wierzchołków (0 = brak stroke'ów w zasięgu).
    """
    from mathutils.kdtree import KDTree
    from mathutils.bvhtree import BVHTree

    props   = context.scene.retopo_props
    strokes = get_stroke_objects(context)
    if not strokes:
        return 0

    # ── Krok 1: sampling stroke'ów przez eval mesh ────────────────────────
    # Konwersja krzywej beziera → tymczasowy mesh daje punkty ze
    # wszystkimi interpolowanymi pozycjami (obsługuje resolution_u).
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

    # ── Krok 2: KD-Tree ze stroke'ów ─────────────────────────────────────
    kd = KDTree(len(stroke_points))
    for i, pt in enumerate(stroke_points):
        kd.insert(pt, i)
    kd.balance()

    # ── Krok 3: BVH targetu — do re-projekcji na powierzchnię ────────────
    eval_target = target_obj.evaluated_get(depsgraph)
    target_bvh  = BVHTree.FromObject(eval_target, depsgraph)

    # ── Krok 4: edycja wynikowej siatki przez BMesh ───────────────────────
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
        # Quadratic falloff × strength: siła=1 przy dist=0, siła=0 przy dist=snap_radius
        weight  = (1.0 - dist / snap_radius) ** 2 * props.stroke_snap_strength
        # Re-project pozycji stroke'a na powierzchnię high-poly
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
    Post-process po remeshu: wyrównuje kierunek krawędzi do tangenty
    najbliższego stroke'a (tryb Field / Approximate).

    Zamiast przyciągać wierzchołek DO linii stroke'a, redukuje składową
    wektora prostopadłą do tangenty stroke'a — wierzchołek przesuwa się
    WZDŁUŻ stroke'a, a nie NA niego. Efekt: przepływ quadów podąża za
    kierunkiem stroke'a bez tworzenia twardych edge loopów.

    Zwraca liczbę zmodyfikowanych wierzchołków.
    """
    from mathutils.kdtree import KDTree
    from mathutils.bvhtree import BVHTree

    props   = context.scene.retopo_props
    strokes = get_stroke_objects(context)
    if not strokes:
        return 0

    # ── Krok 1: sampling stroke'ów — zbierz pary (midpoint, tangent) ─────
    # Konwersja bezier → mesh daje sekwencję wierzchołków; tangent segmentu
    # to znormalizowana różnica między kolejnymi punktami.
    stroke_segments = []  # lista (p0, p1, tangent) — pełny segment
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

    # ── Krok 2: KD-Tree z midpointów segmentów (do wyszukiwania najbliższego) ──
    kd = KDTree(len(stroke_segments))
    for i, (p0, p1, _) in enumerate(stroke_segments):
        kd.insert((p0 + p1) * 0.5, i)
    kd.balance()

    # ── Krok 3: BVH targetu — do re-projekcji na powierzchnię ────────────
    eval_target = target_obj.evaluated_get(depsgraph)
    target_bvh  = BVHTree.FromObject(eval_target, depsgraph)

    # ── Krok 4: edycja wynikowej siatki przez BMesh ───────────────────────
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

        # Falloff liniowy: pełna siła przy dist=0, zerowa przy dist=field_radius
        weight = (1.0 - dist / field_radius) * strength

        # Closest point on segment (t ∈ [0,1]) — unika infinite-line artefaktów
        ab = seg_p1 - seg_p0
        t  = max(0.0, min(1.0, (world_co - seg_p0).dot(ab) / ab.dot(ab)))
        foot = seg_p0 + t * ab
        # perp = wektor od vertexa DO linii stroke'a (prostopadły do tangenty)
        perp = foot - world_co

        # Przesuń wierzchołek wzdłuż perp o weight
        new_co = world_co + perp * weight

        # Re-project na powierzchnię high-poly
        hit_loc, _, _, _ = target_bvh.find_nearest(new_co)
        if hit_loc:
            v.co = mat_inv @ hit_loc
            influenced += 1

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(result_obj.data)
    bm.free()
    result_obj.data.update()
    return influenced


def _rosy4_best(nb_t, ref, vn):
    """Zwraca tę rotację nb_t (0°/90°/180°/270° wokół vn) która najlepiej wyrównuje
    się z ref. Implementacja 4-RoSy alignment (Instant Meshes / Jakob et al. 2015).
    Zapobiega anulowaniu się przeciwnych tangentów podczas uśredniania w DIFFUSE."""
    c1 = vn.cross(nb_t)
    if c1.length < 1e-6:          # tangent równoległy do normalnej — tylko flip
        return nb_t if nb_t.dot(ref) >= 0.0 else -nb_t
    c1 = c1.normalized()
    best, best_d = nb_t, nb_t.dot(ref)
    for c in (c1, -nb_t, -c1):   # 90°, 180°, 270°
        d = c.dot(ref)
        if d > best_d:
            best, best_d = c, d
    return best


def apply_stroke_guidance_diffusion(context, result_obj, target_obj):
    """
    Post-process po remeshu: propaguje pole orientacji od stroke'ów przez krawędzie
    siatki (multi-hop diffusion) — efekt globalny jak w Instant Meshes 4-RoSy field.

    Algorytm trzystopniowy:
      1. SEED   — wierzchołki blisko stroke'a dostają wagę i tangent stroke'a
      2. DIFFUSE — N iteracji: waga i tangent propagują się przez adjacency grafu
                   (każdy wierzchołek = średnia ważona sąsiadów × decay)
      3. APPLY  — per-vertex: przesunięcie ⊥ do tangenty × propagowana_waga → re-project BVH

    Różnica vs FIELD: FIELD ma hard cutoff na promieniu → DIFFUSE dociera do całego
    meshu z wygaszaniem zależnym od odległości topologicznej (liczby krawędzi).
    """
    from mathutils.kdtree import KDTree
    from mathutils.bvhtree import BVHTree

    props   = context.scene.retopo_props
    strokes = get_stroke_objects(context)
    if not strokes:
        return 0

    # ── Krok 1: sampling stroke'ów ───────────────────────────────────────
    stroke_segments = []
    depsgraph = context.evaluated_depsgraph_get()
    for s in strokes:
        eval_s = s.evaluated_get(depsgraph)
        tmp = eval_s.to_mesh()
        if tmp and len(tmp.vertices) >= 2:
            mw  = s.matrix_world
            pts = [mw @ v.co for v in tmp.vertices]
            for i in range(len(pts) - 1):
                p0, p1 = pts[i], pts[i + 1]
                seg_dir = p1 - p0
                if seg_dir.length < 1e-6:
                    continue
                stroke_segments.append((p0, p1, seg_dir.normalized()))
        eval_s.to_mesh_clear()

    if not stroke_segments:
        return 0

    kd = KDTree(len(stroke_segments))
    for i, (p0, p1, _) in enumerate(stroke_segments):
        kd.insert((p0 + p1) * 0.5, i)
    kd.balance()

    eval_target = target_obj.evaluated_get(depsgraph)
    target_bvh  = BVHTree.FromObject(eval_target, depsgraph)

    # ── Krok 2: SEED — inicjalizacja pola przy stroke'ach ────────────────
    bm = bmesh.new()
    bm.from_mesh(result_obj.data)
    bm.verts.ensure_lookup_table()

    seed_radius = props.stroke_field_radius
    strength    = props.stroke_field_strength
    mat_world   = result_obj.matrix_world
    mat_inv     = mat_world.inverted()
    n_verts     = len(bm.verts)

    # field_tangent[i] = Vector tangent lub None
    # field_weight[i]  = float [0, 1]
    field_tangent = [None]  * n_verts
    field_weight  = [0.0]   * n_verts
    is_seed       = [False] * n_verts

    for v in bm.verts:
        world_co = mat_world @ v.co
        _, idx, dist = kd.find(world_co)
        if dist <= seed_radius:
            seg_p0, seg_p1, tangent = stroke_segments[idx]
            ab = seg_p1 - seg_p0
            t  = max(0.0, min(1.0, (world_co - seg_p0).dot(ab) / ab.dot(ab)))
            field_tangent[v.index] = tangent.copy()
            field_weight [v.index] = (1.0 - dist / seed_radius) * strength
            is_seed      [v.index] = True

    # ── Krok 3: DIFFUSE — propagacja przez adjacency ─────────────────────
    # decay ≈ 0.85 na krok → po N krokach: 0.85^N resztkowej wagi
    decay      = 0.85
    iterations = props.stroke_diffusion_iterations

    for _ in range(iterations):
        new_tangent = list(field_tangent)
        new_weight  = list(field_weight)

        for v in bm.verts:
            if is_seed[v.index]:
                continue  # seed zachowuje oryginalną wartość

            acc_t  = Vector((0.0, 0.0, 0.0))
            acc_w  = 0.0
            total  = 0.0
            # Normalna wierzchołka w przestrzeni świata (potrzebna do obrotów 4-RoSy)
            vn  = (mat_world.to_3x3() @ v.normal).normalized()
            ref = None  # referencja 4-RoSy — ustawi pierwszy sąsiad z wagą > 0

            for e in v.link_edges:
                nb   = e.other_vert(v)
                w_nb = field_weight[nb.index]
                nb_t = field_tangent[nb.index]
                if nb_t is not None and w_nb > 1e-8:
                    # 4-RoSy: wybierz obrót nb_t (0/90/180/270°) najbliższy ref
                    if ref is None:
                        ref     = nb_t      # pierwszy sąsiad → ustala referencję
                        aligned = nb_t
                    else:
                        aligned = _rosy4_best(nb_t, ref, vn)
                    acc_t += aligned * w_nb
                    acc_w += w_nb
                    if acc_t.length > 1e-8:  # aktualizuj ref do bieżącej średniej
                        ref = acc_t.normalized()
                total += 1.0

            if total > 0 and acc_t.length > 1e-8:
                new_tangent[v.index] = acc_t.normalized()
                new_weight [v.index] = (acc_w / total) * decay

        field_tangent = new_tangent
        field_weight  = new_weight

    # ── Krok 4: APPLY — przesunięcie wzdłuż pola + re-project ───────────
    influenced = 0
    for v in bm.verts:
        w = field_weight[v.index]
        if w < 1e-6 or field_tangent[v.index] is None:
            continue

        world_co = mat_world @ v.co
        _, idx, _ = kd.find(world_co)
        seg_p0, seg_p1, _ = stroke_segments[idx]
        ab  = seg_p1 - seg_p0
        t   = max(0.0, min(1.0, (world_co - seg_p0).dot(ab) / ab.dot(ab)))
        foot = seg_p0 + t * ab
        perp = foot - world_co          # kierunek do stroke'a

        new_co = world_co + perp * w
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
    """Maluje krzywiznę Gaussa jako Vertex Colors na High-Poly Target"""
    bl_idname  = "retopo.bake_curvature"
    bl_label   = "Bake Curvature Map"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.retopo_props
        if not _obj_in_scene(props.target_object):
            props.target_object = None
            self.report({'WARNING'}, "Wybierz High-Poly Target!")
            return {'CANCELLED'}
        layer = bake_curvature_density(props.target_object)
        mesh  = props.target_object.data
        if mesh.vertex_colors:
            mesh.vertex_colors.active = mesh.vertex_colors[layer]
        self.report({'INFO'}, f"✅ Curvature baked → warstwa '{layer}' "
                              f"(czerwony=gęsto, niebieski=rzadko)")
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────────────────
# OPERATOR: WYCZYŚĆ CREASES Z TARGETU
# ─────────────────────────────────────────────────────────────────────────────

class RETOPO_OT_ClearHardEdges(bpy.types.Operator):
    """Czyści oznaczenia crease/sharp z krawędzi High-Poly Target (cofnięcie Hard Edge Pre-pass)"""
    bl_idname  = "retopo.clear_hard_edges"
    bl_label   = "Wyczyść Creases z Targetu"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.retopo_props
        if not _obj_in_scene(props.target_object):
            props.target_object = None
            self.report({'WARNING'}, "Wybierz High-Poly Target!")
            return {'CANCELLED'}
        target = props.target_object

        bm = bmesh.new()
        bm.from_mesh(target.data)
        if hasattr(bm.edges.layers, 'crease'):
            crease_layer = bm.edges.layers.crease.verify()
        else:
            crease_layer = (bm.edges.layers.float.get("crease_edge") or
                            bm.edges.layers.float.new("crease_edge"))
        cleared = 0
        for e in bm.edges:
            if e[crease_layer] > 0.0 or not e.smooth:
                e[crease_layer] = 0.0
                e.smooth = True
                cleared += 1
        bm.to_mesh(target.data)
        bm.free()
        target.data.update()
        self.report({'INFO'}, f"Wyczyszczono {cleared} krawędzi (crease/sharp → reset)")
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────────────────
# OPERATOR: RYSOWANIE STROKE'A
# ─────────────────────────────────────────────────────────────────────────────

class RETOPO_OT_DrawStroke(bpy.types.Operator):
    """Trzymaj LMB i rysuj linię na modelu"""
    bl_idname  = "retopo.draw_stroke"
    bl_label   = "Narysuj Stroke"
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
                # Symetria: dodaj lustrzany punkt
                props = context.scene.retopo_props
                if props.stroke_use_symmetry and self.mirror_curve_obj:
                    mpt = self._mirror_pt(pt, props.stroke_symmetry_axis)
                    # Snap do powierzchni targetu jeśli dostępny
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
        # Inicjalizacja zmiennych instancji tutaj (nie w __init__) —
        # wymagane przez Blender 5.0 gdzie __setattr__ operatora jest
        # podpięty pod RNA jeszcze przed pełną inicjalizacją obiektu.
        self.stroke_points        = []
        self.curve_obj            = None
        self.is_mouse_down        = False
        self.min_distance         = 0.005
        self.mirror_curve_obj     = None
        self.mirror_stroke_points = []

        if context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "Uruchom w widoku 3D!")
            return {'CANCELLED'}
        props = context.scene.retopo_props
        if not _obj_in_scene(props.target_object):
            props.target_object = None
            self.report({'WARNING'}, "Wybierz High-Poly Target!")
            return {'CANCELLED'}
        props.is_drawing = True
        self.create_empty_curve(context)
        if props.stroke_use_symmetry:
            self._create_mirror_curve(context, props)
        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, "Trzymaj LMB i rysuj. Puść aby zakończyć.")
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
            self.report({'INFO'}, f"✅ {self.curve_obj.name} ({len(self.stroke_points)}pt)")
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
        mat.diffuse_color = (0.0, 0.8, 0.4, 1.0)   # zielony = lustrzany
        mat.use_nodes = False
        self.mirror_curve_obj.data.materials.append(mat)
        # przywróć focus na główny curve
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
# OPERATOR: USUŃ / WYCZYŚĆ STROKE'I
# ─────────────────────────────────────────────────────────────────────────────

class RETOPO_OT_DeleteStroke(bpy.types.Operator):
    bl_idname  = "retopo.delete_stroke"
    bl_label   = "Usuń Stroke"
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
        props.is_drawing = False  # reset flagi rysowania
        self.report({'INFO'}, f"Usunięto: {name}")
        return {'FINISHED'}


class RETOPO_OT_ClearStrokes(bpy.types.Operator):
    bl_idname  = "retopo.clear_strokes"
    bl_label   = "Wyczyść Wszystkie"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        strokes = get_stroke_objects(context)
        count   = len(strokes)
        for obj in strokes:
            bpy.data.objects.remove(obj, do_unlink=True)
        context.scene.retopo_props.stroke_counter = 0
        context.scene.retopo_props.is_drawing = False  # reset flagi
        self.report({'INFO'}, f"Usunięto {count} stroke'ów")
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────────────────
# OPERATOR: RETOPOLOGIA – trzy tryby
# ─────────────────────────────────────────────────────────────────────────────

class RETOPO_OT_ExecuteRetopo(bpy.types.Operator):
    """Uruchom retopologię wybraną metodą"""
    bl_idname  = "retopo.execute_retopo"
    bl_label   = "URUCHOM RETOPO"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props  = context.scene.retopo_props
        target = props.target_object

        if not _obj_in_scene(target):
            props.target_object = None
            self.report({'WARNING'}, "Target object nie istnieje — wybierz ponownie.")
            return {'CANCELLED'}

        # ── Pre-pass: Mesh Healing (#18) ───────────────────────
        if props.use_mesh_healing:
            h = heal_mesh(target)
            parts = []
            if h['merged_verts'] > 0:
                parts.append(f"{h['merged_verts']} verts scalonych")
            if h['holes_filled'] > 0:
                parts.append(f"{h['holes_filled']} dziur zamkniętych")
            if parts:
                self.report({'INFO'}, "Mesh Healing: " + ", ".join(parts))

        # ── Pre-pass: Curvature Density Map (#3) ───────────────
        if props.use_curvature_density:
            bake_curvature_density(target)

        # ── Pre-pass: Hard Edge Detection ──────────────────────
        if props.use_hard_edge_prepass:
            n = mark_hard_edges(target, props.hard_edge_angle)
            self.report({'INFO'}, f"Hard edges: {n} krawędzi oznaczonych jako crease")

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
            # Najpierw guidance — przesuwa wierzchołki ku stroke'om.
            if props.use_stroke_guidance and get_stroke_objects(context):
                if props.stroke_guidance_mode == 'FIELD':
                    snapped = apply_stroke_guidance_field(context, result, target)
                    if snapped:
                        self.report({'INFO'}, f"Field guidance: {snapped} wierzchołków wyrównanych")
                elif props.stroke_guidance_mode == 'DIFFUSE':
                    snapped = apply_stroke_guidance_diffusion(context, result, target)
                    if snapped:
                        self.report({'INFO'}, f"Diffuse guidance: {snapped} wierzchołków wyrównanych")
                else:
                    snapped = apply_stroke_guidance(context, result, target)
                    if snapped:
                        self.report({'INFO'}, f"Snap guidance: {snapped} wierzchołków przyciągniętych")

            # ── Post-pass: Laplacian Smooth + Re-project ────────
            # Po guidance — relaksuje rozciągnięte krawędzie między
            # wierzchołkami przy stroke'ach a tymi poza nimi,
            # jednocześnie rzutując z powrotem na powierzchnię high-poly.
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
                self.report({'INFO'}, f"LOD chain → kolekcja '{lod_col.name}'")
                # result został przemianowany wewnątrz generate_lod_chain
                result = bpy.data.objects.get(f"{result.name}_LOD0") or result

            bpy.ops.object.select_all(action='DESELECT')
            result.select_set(True)
            context.view_layer.objects.active = result
            v = len(result.data.vertices)
            f = len(result.data.polygons)
            self.report({'INFO'}, f"✅ Gotowe! {v} verts, {f} faces — [{mode}]")
            return {'FINISHED'}

        self.report({'ERROR'}, "Retopo nie powiodło się")
        return {'CANCELLED'}

    # ── TRYB 1: Voxel Remesh ───────────────────────────────────

    def retopo_voxel(self, context, props, target):
        """
        Duplikuj target → Voxel Remesh.
        Najszybszy tryb, automatyczna siatka na całym modelu.
        """
        # Tymczasowo pokaż obiekt jeśli ukryty (duplicate wymaga widoczności)
        was_hidden = target.hide_get()
        was_hidden_viewport = target.hide_viewport
        target.hide_set(False)
        target.hide_viewport = False

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target
        bpy.ops.object.duplicate(linked=False)
        result = context.active_object

        # Przywróć widoczność oryginału
        target.hide_set(was_hidden)
        target.hide_viewport = was_hidden_viewport

        mod = result.modifiers.new("VoxelRemesh", 'REMESH')
        mod.mode        = 'VOXEL'
        mod.voxel_size  = props.voxel_size
        mod.adaptivity  = props.voxel_adaptivity
        bpy.ops.object.modifier_apply(modifier="VoxelRemesh")

        self.report({'INFO'}, f"Voxel size: {props.voxel_size}")
        return result

    # ── TRYB 2: Remesh + Shrinkwrap ────────────────────────────

    def retopo_shrinkwrap(self, context, props, target):
        """
        Duplikuj target → Voxel Remesh (zgrubny) → Shrinkwrap z powrotem
        na oryginał → efekt: czysta siatka ściśle przylegająca do high-poly.
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

        # Krok 1: Remesh — zgrubna siatka
        mod_remesh = result.modifiers.new("Remesh", 'REMESH')
        mod_remesh.mode       = 'VOXEL'
        mod_remesh.voxel_size = props.voxel_size
        mod_remesh.adaptivity = props.voxel_adaptivity
        bpy.ops.object.modifier_apply(modifier="Remesh")

        # Krok 2: Shrinkwrap — dopasuj do oryginału
        mod_sw = result.modifiers.new("Shrinkwrap", 'SHRINKWRAP')
        mod_sw.target                 = target
        mod_sw.wrap_method            = 'NEAREST_SURFACEPOINT'
        mod_sw.use_negative_direction = True
        mod_sw.use_positive_direction = True
        mod_sw.offset                 = props.shrinkwrap_offset
        bpy.ops.object.modifier_apply(modifier="Shrinkwrap")

        # Krok 3: Smooth — wygładź wynik
        bpy.ops.object.shade_smooth()

        return result

    # ── TRYB 3: Decimate ───────────────────────────────────────

    def retopo_decimate(self, context, props, target):
        """
        Duplikuj target → Decimate.
        Zachowuje oryginalną topologię, tylko redukuje liczbę poly.
        Najlepszy gdy oryginał ma już dobrą topologię.
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

    # ── TRYB 4: Quadriflow ─────────────────────────────────────

    def retopo_quadriflow(self, context, props, target):
        """
        Duplikuj target → Quadriflow Remesh.
        Buduje czystą siatkę quadów z zachowaniem krzywizn — wolniejszy od
        Voxel, ale daje znacznie lepszą topologię nadającą się do animacji.
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
        self.report({'INFO'}, f"Quadriflow: {props.quadriflow_faces} faces docelowo")
        return result

    # ── TRYB 5: Instant Meshes ─────────────────────────────────

    def retopo_instant_meshes(self, context, props, target):
        """
        Eksportuje target do OBJ → uruchamia Instant Meshes jako subprocess
        → importuje wynik. Najlepsza automatyczna topologia z edge loopami.
        Wymaga zainstalowanej binarki Instant Meshes.
        """
        im_path = _get_im_path(props)
        if not im_path:
            self.report({'WARNING'},
                        "Podaj ścieżkę do Instant Meshes (pole Binarka) "
                        "lub ustaw domyślną w: Edit → Preferences → Add-ons → Retopo Stroke Tool")
            return None
        if not os.path.isfile(im_path):
            self.report({'ERROR'}, f"Nie znaleziono pliku: {im_path}")
            return None

        tmp_dir = tempfile.gettempdir()
        tmp_in  = os.path.join(tmp_dir, "retopo_im_input.obj")
        tmp_out = os.path.join(tmp_dir, "retopo_im_output.obj")

        # Eksport targetu do OBJ
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

        # Uruchom Instant Meshes
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
            self.report({'ERROR'}, f"Nie można uruchomić Instant Meshes: {e}")
            return None

        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "brak szczegółów")[:200]
            self.report({'ERROR'}, f"Instant Meshes błąd (kod {proc.returncode}): {msg}")
            return None

        if not os.path.isfile(tmp_out):
            self.report({'ERROR'}, "Instant Meshes nie zapisał pliku wyjściowego")
            return None

        # Import wyniku
        before = set(o.name for o in bpy.data.objects)
        try:
            # Blender 4.x
            bpy.ops.wm.obj_import(filepath=tmp_out)
        except AttributeError:
            # Blender 3.x
            bpy.ops.import_scene.obj(filepath=tmp_out)

        new_names = set(o.name for o in bpy.data.objects) - before
        if not new_names:
            self.report({'ERROR'}, "Import wyniku Instant Meshes nie powiódł się")
            return None

        result = bpy.data.objects[next(iter(new_names))]

        # Sprzątanie plików tymczasowych
        for f in (tmp_in, tmp_out):
            try:
                os.remove(f)
            except OSError:
                pass

        bpy.ops.object.shade_smooth()
        return result

    # ── TRYB 6: QuadWild ───────────────────────────────────────

    @staticmethod
    def _qremeshify_available():
        """Sprawdza czy addon QRemeshify jest zarejestrowany w Blenderze."""
        return (hasattr(bpy.ops, 'qremeshify') and
                hasattr(bpy.ops.qremeshify, 'remesh') and
                hasattr(bpy.types.Scene, 'quadwild_props'))

    def retopo_quadwild(self, context, props, target):
        """
        Tryb 6: QuadWild — najbliższy jakością ZRemesherowi open-source solver.

        Ścieżka A (priorytet): addon QRemeshify zainstalowany →
            bpy.ops.qremeshify.remesh() z bundlowaną binarką.
        Ścieżka B (fallback): ręczna ścieżka do quadwild-bimdf binary (subprocess).
        """
        import math

        if self._qremeshify_available():
            return self._retopo_quadwild_via_qremeshify(context, props, target)
        else:
            return self._retopo_quadwild_via_binary(context, props, target, math)

    def _retopo_quadwild_via_qremeshify(self, context, props, target):
        """Ścieżka A: wywołuje bpy.ops.qremeshify.remesh() gdy addon jest zainstalowany."""
        import math

        # Ustaw parametry w scene.quadwild_props (QRemeshify czyta stamtąd)
        qw_props = context.scene.quadwild_props
        qw_props.enableSharp  = True
        qw_props.sharpAngle   = math.degrees(props.quadwild_sharp_angle)
        qw_props.enableRemesh = True
        qw_props.enableSmoothing = True

        # scaleFact w quadpatches_props kontroluje rozmiar quadów
        context.scene.quadpatches_props.scaleFact = props.quadwild_scale_fact

        # Aktywuj target przed wywołaniem operatora
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
            self.report({'ERROR'}, f"QRemeshify błąd: {e}")
            target.hide_set(was_hidden)
            target.hide_viewport = was_hidden_viewport
            return None

        target.hide_set(was_hidden)
        target.hide_viewport = was_hidden_viewport

        if result_op == {'CANCELLED'}:
            self.report({'ERROR'}, "QRemeshify anulował operację — sprawdź selekcję i tryb obiektu")
            return None

        new_names = set(o.name for o in bpy.data.objects) - before
        if not new_names:
            self.report({'ERROR'}, "QRemeshify nie stworzył nowego obiektu")
            return None

        result = bpy.data.objects[next(iter(new_names))]
        self.report({'INFO'},
                    f"QuadWild via QRemeshify — scaleFact={props.quadwild_scale_fact:.2f}")
        return result

    def _retopo_quadwild_via_binary(self, context, props, target, math):
        """Ścieżka B: wywołuje quadwild-bimdf binary przez subprocess (fallback)."""
        qw_path = props.quadwild_path.strip()
        if not qw_path:
            self.report({'WARNING'},
                        "QuadWild: zainstaluj addon QRemeshify (github.com/ksami/QRemeshify) "
                        "LUB podaj ścieżkę do binarki quadwild-bimdf w polu poniżej")
            return None
        if not os.path.isfile(qw_path):
            self.report({'ERROR'}, f"QuadWild: nie znaleziono pliku: {qw_path}")
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
            self.report({'ERROR'}, "QuadWild: timeout (>300s) — spróbuj zmniejszyć Target Faces")
            return None
        except OSError as e:
            self.report({'ERROR'}, f"Nie można uruchomić QuadWild: {e}")
            return None

        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "brak szczegółów")[:200]
            self.report({'ERROR'}, f"QuadWild błąd (kod {proc.returncode}): {msg}")
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
                            "QuadWild nie zapisał pliku wyjściowego — "
                            "sprawdź czy to binarka quadwild-bimdf (nie stara wersja)")
                return None

        before = set(o.name for o in bpy.data.objects)
        try:
            bpy.ops.wm.obj_import(filepath=tmp_out)
        except AttributeError:
            bpy.ops.import_scene.obj(filepath=tmp_out)

        new_names = set(o.name for o in bpy.data.objects) - before
        if not new_names:
            self.report({'ERROR'}, "Import wyniku QuadWild nie powiódł się")
            return None

        result = bpy.data.objects[next(iter(new_names))]

        for f in (tmp_in, tmp_out):
            try:
                os.remove(f)
            except OSError:
                pass

        bpy.ops.object.shade_smooth()
        self.report({'INFO'}, f"QuadWild (binary): {props.quadwild_faces} faces docelowo")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# PANEL UI
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

        # ── Tryb retopo ────────────────────────────────────────
        box = layout.box()
        box.label(text="Metoda Retopo", icon='MOD_REMESH')
        box.prop(props, "retopo_mode", expand=True)

        layout.separator()

        # ── Preset gęstości ────────────────────────────────────
        box = layout.box()
        box.label(text="Gęstość Siatki", icon='MESH_GRID')
        box.prop(props, "density_preset", expand=True)

        # Parametry zależne od trybu
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
                qw_box.label(text="QRemeshify zainstalowany — binarka bundlowana", icon='CHECKMARK')
                qw_box.prop(props, "quadwild_scale_fact", slider=True)
            else:
                qw_box.label(text="QRemeshify nie wykryty — podaj binarke ręcznie", icon='INFO')
                qw_box.prop(props, "quadwild_path", text="Binarka (quadwild-bimdf)")
                if not props.quadwild_path.strip():
                    col = qw_box.column(align=False)
                    col.label(text="Binarka nie ustawiona", icon='ERROR')
                    col.label(text="Opcja 1: zainstaluj QRemeshify (brak potrzeby binarki)", icon='URL')
                    col.label(text="Opcja 2: pobierz quadwild-bimdf z github.com/nicopietroni", icon='URL')
                else:
                    qw_box.label(
                        text=f"Binary: {os.path.basename(props.quadwild_path.strip())}",
                        icon='CHECKMARK'
                    )

        if mode == 'INSTANT_MESHES':
            im_box = layout.box()
            im_box.label(text="Instant Meshes", icon='EXPORT')

            # Pole per-scena (opcjonalne — override preferencji)
            path_row = im_box.row(align=True)
            path_row.prop(props, "instant_meshes_path", text="Binarka")
            path_row.operator("retopo.save_im_path", text="", icon='BOOKMARKS')

            # Status efektywnej ścieżki
            effective = _get_im_path(props)
            if not effective:
                im_box.label(text="Brak ścieżki — ustaw wyżej lub w Preferencjach", icon='ERROR')
                im_box.label(text="Pobierz: meshlab.github.io/instant-meshes", icon='INFO')
            elif not props.instant_meshes_path.strip():
                im_box.label(text=f"Domyślna: {os.path.basename(effective)}", icon='CHECKMARK')

            col = im_box.column(align=True)
            col.prop(props, "instant_meshes_crease", slider=True)
            col.prop(props, "instant_meshes_smooth", slider=True)
            col.prop(props, "instant_meshes_dominant")
            col.separator()
            col.prop(props, "instant_meshes_boundaries")
            col.prop(props, "instant_meshes_deterministic")
            col.prop(props, "instant_meshes_threads")

        # Podgląd szacowanej liczby poly
        self._draw_poly_estimate(box, props)

        layout.separator()

        # ── Stroke'i (opcjonalne edge loops) — ukryte dla DECIMATE ─
        if mode != 'DECIMATE':
            box = layout.box()
            row = box.row()
            row.label(text=f"Edge Loops ({len(strokes)})", icon='CURVE_BEZCURVE')

            if not _obj_in_scene(props.target_object):
                box.label(text="Wybierz Target aby rysować", icon='INFO')
            elif props.is_drawing:
                box.label(text="Rysowanie aktywne...", icon='REC')
            else:
                btn = box.row()
                btn.scale_y = 1.4
                btn.operator("retopo.draw_stroke",
                             text="+ Narysuj Edge Loop",
                             icon='CURVE_BEZCURVE')
                # Symetria
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
                row.operator("retopo.delete_stroke",   text="Usuń",    icon='X')
                row.operator("retopo.clear_strokes",   text="Wyczyść", icon='TRASH')

                guidance_row = box.row()
                guidance_row.prop(
                    props, "use_stroke_guidance",
                    text="Użyj jako Guidance",
                    icon='FORCE_MAGNETIC',
                    toggle=True,
                )
                if props.use_stroke_guidance:
                    mode_row = box.row(align=True)
                    mode_row.prop(props, "stroke_guidance_mode", expand=True)
                    if props.stroke_guidance_mode == 'SNAP':
                        box.prop(props, "stroke_snap_radius",   slider=True)
                        box.prop(props, "stroke_snap_strength", slider=True)
                    elif props.stroke_guidance_mode == 'FIELD':
                        box.prop(props, "stroke_field_radius",   slider=True)
                        box.prop(props, "stroke_field_strength", slider=True)
                        if not props.use_smooth_reproject:
                            box.label(
                                text="↳ Zalecane: włącz Smooth+Reproject",
                                icon='INFO'
                            )
                    else:  # DIFFUSE
                        box.prop(props, "stroke_field_radius",          slider=True,
                                 text="Seed Radius")
                        box.prop(props, "stroke_field_strength",        slider=True,
                                 text="Seed Strength")
                        box.prop(props, "stroke_diffusion_iterations",  slider=True)
                        if not props.use_smooth_reproject:
                            box.label(
                                text="↳ Zalecane: włącz Smooth+Reproject",
                                icon='INFO'
                            )

        layout.separator()

        # ── Zaawansowane ───────────────────────────────────────
        box = layout.box()
        box.label(text="Zaawansowane", icon='SETTINGS')

        # Mesh Healing — zawsze
        col_heal = box.column(align=True)
        col_heal.prop(props, "use_mesh_healing", toggle=True, icon='TOOL_SETTINGS')

        # Curvature Density Map — ukryte dla DECIMATE
        if mode != 'DECIMATE':
            box.separator()
            col0 = box.column(align=True)
            row0 = col0.row(align=True)
            row0.prop(props, "use_curvature_density", toggle=True, icon='COLORSET_01_VEC')
            row0.operator("retopo.bake_curvature", text="Bake Now", icon='VPAINT_HLT')

        # Hard Edge Pre-pass — tylko QUADRIFLOW i INSTANT_MESHES
        if mode in ('QUADRIFLOW', 'INSTANT_MESHES'):
            box.separator()
            col = box.column(align=True)
            col.prop(props, "use_hard_edge_prepass", toggle=True, icon='EDGESEL')
            if props.use_hard_edge_prepass:
                col.prop(props, "hard_edge_angle", slider=True)
                col.operator("retopo.clear_hard_edges",
                             text="Wyczyść Creases z Targetu", icon='X')

        # Smooth + Re-project — ukryte dla DECIMATE i SHRINKWRAP
        if mode not in ('DECIMATE', 'SHRINKWRAP'):
            box.separator()
            col2 = box.column(align=True)
            col2.prop(props, "use_smooth_reproject", toggle=True, icon='MOD_SMOOTH')
            if props.use_smooth_reproject:
                col2.prop(props, "smooth_reproject_iterations", slider=True)
                col2.prop(props, "smooth_reproject_factor",     slider=True)

        box.separator()

        # LOD Chain — zawsze
        col3 = box.column(align=True)
        col3.prop(props, "generate_lod", toggle=True, icon='RENDERLAYERS')
        if props.generate_lod:
            col3.prop(props, "lod_levels", slider=True)

        box.separator()

        # Quality Metrics — zawsze
        col4 = box.column(align=True)
        col4.prop(props, "compute_quality_metrics", toggle=True, icon='VIEWZOOM')

        layout.separator()

        # ── GŁÓWNY PRZYCISK ────────────────────────────────────
        box = layout.box()

        # Status
        if not _obj_in_scene(props.target_object):
            box.label(text="Wybierz model powyżej", icon='ERROR')
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
                text=f"Tryb: {mode_labels[mode]}",
                icon='INFO'
            )

        btn = box.row()
        btn.scale_y = 2.2
        btn.enabled = props.target_object is not None and not props.is_drawing
        btn.operator("retopo.execute_retopo",
                     text="▶  URUCHOM RETOPO",
                     icon='MOD_REMESH')

        # ── Metryki jakości (wyświetlane po remeshu) ────────────
        if props.last_metrics_valid:
            mbox = layout.box()
            mbox.label(text="Metryki ostatniego remeshu", icon='VIEWZOOM')
            col = mbox.column(align=True)
            q = props.last_metrics_quad_pct
            q_icon = 'CHECKMARK' if q >= 95 else ('ERROR' if q < 80 else 'INFO')
            col.label(text=f"Quady:       {q:.1f}%",        icon=q_icon)
            col.label(text=f"Poles:       {props.last_metrics_poles}",
                      icon='VERTEXSEL')
            col.label(text=f"Aspect ratio: {props.last_metrics_avg_aspect:.2f}",
                      icon='FULLSCREEN_ENTER')
            a_score = props.last_metrics_avg_angle
            a_icon  = 'CHECKMARK' if a_score >= 0.85 else ('ERROR' if a_score < 0.5 else 'INFO')
            col.label(text=f"Kąt (Jacobian): {a_score:.2f}",
                      icon=a_icon)
            col.label(text=f"Dev. od HP:  {props.last_metrics_avg_dist*1000:.2f} mm",
                      icon='ARROW_LEFTRIGHT')

    def _draw_poly_estimate(self, layout, props):
        """Pokaż szacowaną liczbę polygonów dla wybranych ustawień"""
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
            est = f"~{int(r*100)}% oryginalnych face'ów"
        elif mode == 'QUADRIFLOW':
            est = f"~{props.quadriflow_faces} faces (quady)"
        elif mode == 'INSTANT_MESHES':
            est = f"~{props.instant_meshes_faces} faces (quady + edge loops)"
        else:
            est = ""

        if est:
            row = layout.row()
            row.label(text=est, icon='FUND')


# ─────────────────────────────────────────────────────────────────────────────
# REJESTRACJA
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# ADDON PREFERENCES — trwałe ustawienia poza sceną
# ─────────────────────────────────────────────────────────────────────────────

class RETOPO_AddonPreferences(bpy.types.AddonPreferences):
    """Ustawienia zapisywane w preferencjach Blendera (userpref.blend).
    Dostępne przez: Edit → Preferences → Add-ons → Retopo Stroke Tool."""
    bl_idname = __name__

    instant_meshes_path: bpy.props.StringProperty(
        name="Domyślna ścieżka do Instant Meshes",
        description="Ścieżka do binarki Instant Meshes — zapisywana globalnie, "
                    "wczytywana automatycznie w każdym nowym pliku",
        subtype='FILE_PATH',
        default=""
    )

    def draw(self, context):
        self.layout.prop(self, "instant_meshes_path")


def _get_im_path(props):
    """Zwraca efektywną ścieżkę do binarki Instant Meshes.
    Priorytet: (1) ścieżka w bieżącej scenie → (2) domyślna z AddonPreferences."""
    scene_path = props.instant_meshes_path.strip()
    if scene_path:
        return scene_path
    try:
        prefs = bpy.context.preferences.addons[__name__].preferences
        return prefs.instant_meshes_path.strip()
    except (KeyError, AttributeError):
        return ""


class RETOPO_OT_SaveImPath(bpy.types.Operator):
    """Zapisuje bieżącą ścieżkę do binarki Instant Meshes jako domyślną w preferencjach addona."""
    bl_idname  = "retopo.save_im_path"
    bl_label   = "Zapisz jako domyślną"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        props = context.scene.retopo_props
        path  = props.instant_meshes_path.strip()
        if not path:
            self.report({'WARNING'}, "Pole ścieżki jest puste — najpierw wpisz ścieżkę.")
            return {'CANCELLED'}
        try:
            prefs = context.preferences.addons[__name__].preferences
            prefs.instant_meshes_path = path
            bpy.ops.wm.save_userpref()
            self.report({'INFO'}, f"Zapisano domyślną ścieżkę: {path}")
        except (KeyError, AttributeError):
            self.report({'ERROR'}, "Nie można zapisać — addon musi być zainstalowany (nie tylko uruchomiony jako skrypt).")
            return {'CANCELLED'}
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────────────────

classes = [
    RETOPO_AddonPreferences,
    RetopoPipelineProps,
    RETOPO_UL_StrokeList,
    RETOPO_OT_BakeCurvatureMap,
    RETOPO_OT_ClearHardEdges,
    RETOPO_OT_DrawStroke,
    RETOPO_OT_DeleteStroke,
    RETOPO_OT_ClearStrokes,
    RETOPO_OT_SaveImPath,
    RETOPO_OT_ExecuteRetopo,
    RETOPO_PT_MainPanel,
]


@bpy.app.handlers.persistent
def _retopo_cleanup_handler(scene, depsgraph):
    """Po każdej zmianie sceny sprawdza czy target_object nadal istnieje
    w aktywnej scenie. Jeśli nie (obiekt usunięty Delete w viewporcie)
    — czyści referencję, żeby uniknąć exception przy kolejnym użyciu toola."""
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