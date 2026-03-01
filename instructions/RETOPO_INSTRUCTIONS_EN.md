# Retopo Stroke Tool — User Instructions

**Version:** 2.0
**Blender:** 5.0 +
**Location:** View3D › N-Panel › Retopo Tool

---

## Installation

1. Download `retopology_tool_en.py` (English) **or** `retopology_tool.py` (Polish).
   Do **not** install both at the same time — they register the same scene property.
2. In Blender: **Edit › Preferences › Add-ons › Install…**
3. Select the `.py` file → click **Install Add-on**.
4. Enable the checkbox next to **"Retopo Stroke Tool (EN)"**.
5. The panel appears in the **N-Panel** (press `N` in the 3D Viewport) under the **Retopo Tool** tab.

---

## Quick Start

1. Select your high-poly sculpt or reference mesh.
2. Open the **Retopo Tool** N-panel.
3. Set **High-Poly** to your mesh.
4. Choose a **Retopo Mode** (see below).
5. Select a **Mesh Density** preset.
6. (Optional) Draw edge loop guides.
7. Press **▶ RUN RETOPO**.

The result appears as a new object named `Retopo_<target>_<MODE>`.

---

## Retopo Modes

| Mode | Description | Best for |
|---|---|---|
| **Voxel Remesh** | Instant isotropic remesh via voxel grid | Quick base mesh, sculpt base |
| **Remesh + Shrinkwrap** | Voxel remesh snapped tightly to original surface | Clean wrap over complex surfaces |
| **Decimate** | Reduces poly count while preserving original topology | Already clean topology, game assets |
| **Quadriflow** | Blender's built-in quad remesher with edge flow | Animation-ready topology, characters |
| **Instant Meshes** | External tool (requires binary) — excellent edge loops | Hard-surface, mechanical parts |
| **QuadWild** | Open-source solver closest in quality to ZRemesher | Best automatic quads |

---

## Mesh Density Presets

| Preset | Approx. Face Count | Use Case |
|---|---|---|
| **Game** | ~500–1 000 | Real-time, mobile |
| **Medium** | ~1 000–3 000 | General purpose |
| **High** | ~3 000–6 000 | Cinematic, rendering |
| **Custom** | Manual | Full control |

Switching presets auto-fills Voxel Size, Decimate Ratio, and Target Faces for all modes.

---

## Mode-Specific Settings

### Voxel Remesh / Remesh + Shrinkwrap
- **Voxel Size** — smaller = more polygons (0.001–1.0 m)
- **Offset** (Shrinkwrap only) — distance from the original surface
- **Adaptivity** — triangulates flat areas to reduce poly count; values > 0 disable Fix Poles

### Decimate
- **Decimate Ratio** — 1.0 = no change, 0.1 = 10 % of original faces

### Quadriflow
- **Target Faces** — approximate desired face count
- **Preserve Hard Edges** — forces edge loops along sharp edges (key for hard-surface)
- **Preserve Boundaries** — aligns edge loops to open mesh boundaries
- **Use Symmetry** — remeshes one half and mirrors it
- **Smooth Normals** — smooths normals after remesh

### Instant Meshes
- **Target Faces** — desired face count
- **Crease Angle** — edges above this angle are treated as hard edges (passed as `-c`)
- **Smooth Iterations** — post-remesh smoothing passes (`-S`)
- **Dominant Quads** — allows triangles near poles for difficult topology (`-D`)
- **Align to Boundaries** — aligns edge loops to open mesh boundaries (`-b`)
- **Deterministic** — slower but reproducible result (`-d`)
- **CPU Threads** — `0` = automatic; increase on multi-core machines (`-t`)

**Binary setup:**
Enter the full path to the Instant Meshes executable in the **Binary** field,
or click the bookmark icon to save it as the global default
(**Edit › Preferences › Add-ons › Retopo Stroke Tool**).
Download: [github.com/wjakob/instant-meshes](https://github.com/wjakob/instant-meshes)

### QuadWild
- **Scale Factor** *(QRemeshify mode)* — controls quad size: < 1 = more detail, > 1 = fewer quads
- **Target Faces** *(binary mode)* — desired face count
- **Sharp Angle** — angle threshold for hard edge detection

**Two ways to use QuadWild:**

**Option A — QRemeshify addon (recommended, no manual binary needed):**
Install **QRemeshify** from [github.com/ksami/QRemeshify](https://github.com/ksami/QRemeshify).
When detected, the panel shows "QRemeshify installed — binary bundled ✓"
and calls `bpy.ops.qremeshify.remesh()` automatically.

**Option B — Manual binary (fallback):**
Download `quadwild-bimdf` from [github.com/nicopietroni/quadwild-bimdf](https://github.com/nicopietroni/quadwild-bimdf)
and enter the path to the executable in the **Binary** field.

---

## Edge Loop Guides (Strokes)

Draw bezier curves directly on the model surface to guide edge loop placement.

### Drawing
1. Set a **High-Poly** target.
2. Click **+ Draw Edge Loop**.
3. **Hold LMB** and drag across the surface.
4. **Release LMB** to finish the stroke.
5. Press **ESC** to cancel.

Strokes appear as blue bezier curves in the viewport.

### Symmetry
Enable **Symmetry** before drawing to automatically mirror each stroke across the **X / Y / Z** axis.
Mirror strokes appear in green.

### Stroke Guidance *(not available for Decimate)*
After remesh, vertices near strokes are pulled toward the drawn lines.

| Mode | Effect |
|---|---|
| **Snap** | Vertices jump directly onto the stroke line → hard edge loops |
| **Field** | Edge flow aligns with the stroke tangent → soft directional guidance |

**Snap settings:**
- **Snap Radius** — influence radius; vertices outside are unaffected

**Field settings:**
- **Influence Radius** — how far from the stroke the field has effect
- **Strength** — how strongly edges align with the stroke direction (0 = none, 1 = full)

> **Tip:** Run Stroke Guidance before Smooth + Re-project for best results. The smooth pass will then relax any stretched edges while keeping vertices on the surface.

---

## Advanced Options

These options appear only for modes where they are relevant.

### Mesh Healing *(all modes)*
Pre-pass on the target mesh before remeshing:
- Merges duplicate vertices (threshold: 0.1 mm)
- Fills open boundary holes
- Recalculates face normals

Eliminates the most common cause of artifacts in Voxel Remesh.
The Info bar reports how many vertices were merged and holes filled.

### Curvature Pre-pass *(all modes except Decimate)*
Bakes **Gaussian curvature** and **Mean curvature** as vertex color layers onto the target:
- `CurvatureDensity` — Gauss-Bonnet discrete: red = high curvature (sharp corners), blue = flat
- `MeanCurvature` — cotangent Laplacian: better detects bends and saddles (lips, brow arch)

Use these as a visual reference for placing strokes where curvature is highest.
Click **Bake Now** to update the maps without running a full retopo.

### Hard Edge Pre-pass *(Quadriflow and Instant Meshes only)*
Scans all edges of the target and marks those whose dihedral angle exceeds **Crease Angle** as **sharp + crease**.
- Quadriflow respects these via `Preserve Hard Edges`
- Instant Meshes uses them via the `--crease` flag

### Smooth + Re-project *(Voxel, Quadriflow, Instant Meshes, QuadWild)*
Iterative post-process after remesh:
1. **Cotangent Laplacian smooth** — relaxes vertex distribution without geometric shrinkage
2. **BVH re-projection** — snaps every vertex back onto the high-poly surface

Repeat **N** times. Use after Stroke Guidance to remove stretched edges near stroke lines.
- **Iterations** — number of smooth → re-project cycles (1–20)
- **Smooth Factor** — strength of each smooth step (0.0–1.0)

> **Cotangent vs. uniform Laplacian:** uniform smooth causes shrinkage on irregular meshes. The cotangent-weighted version respects mesh geometry and avoids this bias.

### Generate LOD Chain *(all modes)*
After remesh, creates a collection of progressively decimated meshes:

| Level | Faces |
|---|---|
| LOD0 | 100 % (full resolution) |
| LOD1 | 50 % |
| LOD2 | 25 % |
| LOD3 | 10 % |

All objects land in a collection named `LOD_<object_name>`.
Set **LOD Levels** (2–4) to control how many levels are generated.

### Quality Metrics *(all modes)*
After remesh, computes and displays:

| Metric | Target | Meaning |
|---|---|---|
| **Quads %** | ≥ 95 % | Percentage of quad faces |
| **Poles** | Minimum | Vertices with valence ≠ 4 (non-boundary) |
| **Aspect Ratio** | ~1.0 | max\_edge / min\_edge per face |
| **Angle (Jacobian)** | ~1.0 | min \|sin θ\| per quad (Scaled Jacobian — detects shear) |
| **HP Deviation** | ~0 mm | Average distance from result vertices to high-poly surface |

Icons: ✓ = good, ⚠ = acceptable, ✗ = poor.

---

## Tips & Tricks

**For characters / organic models:**
- Use **Quadriflow** or **QuadWild** for best automatic edge flow.
- Draw strokes along major muscle lines (eye socket, lip corners, brow) before running.
- Enable **Stroke Guidance: Snap** for hard edge loops, **Field** for soft directional influence.
- Set **Symmetry** axis to X before drawing for symmetric topology.

**For hard-surface / mechanical parts:**
- Use **Instant Meshes** with a moderate **Crease Angle** (25–35°).
- Enable **Hard Edge Pre-pass** with the same angle.
- Enable **Preserve Hard Edges** if also running Quadriflow.

**For game assets:**
- Set preset to **Game**, run **Voxel Remesh** for a quick base.
- Then enable **Generate LOD Chain** (3 levels) to get LOD0–LOD2 in one click.

**For large dense meshes:**
- Increase **CPU Threads** in Instant Meshes to use all cores.
- Enable **Deterministic** mode when reproducibility matters (pipeline automation).

**Reducing voxel blockiness:**
- After Voxel Remesh, enable **Smooth + Re-project** with 3–5 iterations.
- Increase **Adaptivity** slightly to reduce flat-area polygon count.

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| Holes in Voxel result | Non-manifold input mesh | Enable **Mesh Healing** |
| Instant Meshes timeout | Too many faces or complex mesh | Reduce **Target Faces**, disable **Deterministic** |
| QRemeshify cancelled | Wrong object mode | Make sure the target is a Mesh in Object Mode |
| QuadWild no output file | Wrong binary (old quadwild, not bimdf) | Ensure the binary is `quadwild-bimdf` |
| Hard Edge Pre-pass error on Blender 4.x | Old crease API | Fixed in current version (uses `crease_edge` float attribute) |
| Stroke Guidance has no effect | No strokes drawn, or radius too small | Draw strokes first; increase Snap/Field Radius |
| Result mesh is far from original | Smooth + Re-project iterations too high | Reduce iterations or smooth factor |

---

## Algorithm Notes

### Curvature Maps
- **Gaussian curvature:** angle deficit normalized by Voronoi area — `K = |2π − Σθ| / A` (Gatzke & Grimm 2004)
- **Mean curvature:** cotangent-weighted Laplacian magnitude — standard industry formula

### Smooth + Re-project
Uses **cotangent-weighted Laplacian** (not uniform), which avoids the shrinkage bias that uniform Laplacian produces on irregular meshes (ETH Zurich "Laplacian Mesh Optimization").

### Stroke Guidance — Field Mode
Projects each result vertex onto the nearest stroke segment (closest-point-on-segment, `t ∈ [0,1]`) and reduces the perpendicular component of the displacement vector, weighted by a linear falloff within the influence radius (ACM SIGGRAPH 2021 "Reliable Feature-Line Driven Quad-Remeshing").

### Stroke Guidance — Snap Mode
Projects the nearest stroke point onto the high-poly BVH surface, then interpolates the vertex toward that projected position using a **quadratic falloff** `(1 − d/r)²` — eliminating the step discontinuity of a hard distance cutoff.

---

## Compatibility

| Feature | Blender 3.x | Blender 4.x |
|---|---|---|
| Voxel / Shrinkwrap / Decimate | ✓ | ✓ |
| Quadriflow | ✓ | ✓ |
| Instant Meshes (subprocess) | ✓ | ✓ |
| QuadWild via QRemeshify | ✓ | ✓ |
| OBJ export/import | `export_scene.obj` | `wm.obj_export` (auto-detected) |
| BMesh crease layer | `layers.crease` | `layers.float["crease_edge"]` (auto-detected) |

---

*Retopo Stroke Tool is open-source. Logic based on: Bommes et al. SIGGRAPH 2009, Pietroni et al. 2021 (QuadWild), Instant Meshes (Jakob et al. 2015).*
