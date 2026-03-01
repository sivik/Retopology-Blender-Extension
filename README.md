# Retopo Stroke Tool

A Blender addon for semi-automatic retopology with 6 remesh modes, edge loop drawing, stroke guidance, curvature maps, LOD generation, and topology quality metrics.

**Blender:** 3.0 +  &nbsp;|&nbsp; **Platform:** Windows / macOS / Linux

---

## Files

| File | Description |
|---|---|
| `retopology_tool.py` | Addon — Polish UI |
| `retopology_tool_en.py` | Addon — English UI |
| `INSTRUKCJA.md` | Full user documentation (Polish) |
| `RETOPO_INSTRUCTIONS_EN.md` | Full user documentation (English) |

> **Do not install both language versions at the same time** — they register the same `scene.retopo_props` property and will conflict.

---

## Installation

1. Open Blender → **Edit › Preferences › Add-ons › Install…**
2. Select `retopology_tool_en.py` (English) or `retopology_tool.py` (Polish)
3. Enable the checkbox next to **Retopo Stroke Tool**
4. The panel appears in the **N-Panel** (`N` key in 3D Viewport) → **Retopo Tool** tab

---

## External Dependencies

The addon has **3 modes that require external software**. The table below shows what to download and where.

---

### Instant Meshes &nbsp;·&nbsp; required for mode: **Instant Meshes**

> High-quality automatic quad remesher with excellent edge loops. Open-source, cross-platform.

| | |
|---|---|
| **Download** | https://github.com/wjakob/instant-meshes |
| **File to get** | Pre-built binary from the **Releases** page (`Instant Meshes-xxx.exe` on Windows) |
| **How to set path** | In the addon panel → select **Instant Meshes** mode → paste full path into the **Binary** field. Click the bookmark icon to save it globally (persists across Blender sessions). |
| **License** | BSD 3-Clause |

**Direct release link:**
`https://github.com/wjakob/instant-meshes/releases`

---

### QRemeshify &nbsp;·&nbsp; required for mode: **QuadWild** *(recommended)*

> Blender addon that bundles the QuadWild solver. **No separate binary needed** — everything is included. This is the easiest way to use QuadWild.

| | |
|---|---|
| **Download** | https://github.com/ksami/QRemeshify |
| **File to get** | Click **Code › Download ZIP**, then install the ZIP as a Blender Extension |
| **How to install** | Blender → **Edit › Preferences › Add-ons › Install…** → select the ZIP → enable **QRemeshify** |
| **How it connects** | When QRemeshify is detected, the Retopo Tool panel shows **"QRemeshify installed — binary bundled ✓"** and calls it automatically. No path configuration needed. |
| **License** | GPL-3.0 |

**Controls exposed in Retopo Tool when QRemeshify is active:**
- **Scale Factor** — quad size (`< 1` = more detail, `> 1` = fewer polygons)
- **Sharp Angle** — threshold for hard edge detection

---

### QuadWild-BIMDF &nbsp;·&nbsp; required for mode: **QuadWild** *(fallback — only if QRemeshify is NOT installed)*

> The standalone QuadWild binary. Use this only if you prefer not to install the QRemeshify addon.

| | |
|---|---|
| **Download** | https://github.com/nicopietroni/quadwild-bimdf |
| **File to get** | Pre-built binary from the **Releases** page. Make sure it's `quadwild-bimdf`, **not** the older `quadwild` (different CLI, incompatible). |
| **How to set path** | In the addon panel → select **QuadWild** mode → paste full path into the **Binary (quadwild-bimdf)** field |
| **License** | GPL-3.0 |

---

## Dependency Summary

| Mode | External requirement | Status if missing |
|---|---|---|
| Voxel Remesh | — (built-in) | Always works |
| Remesh + Shrinkwrap | — (built-in) | Always works |
| Decimate | — (built-in) | Always works |
| Quadriflow | — (built-in) | Always works |
| **Instant Meshes** | Instant Meshes binary | Warning — binary not set |
| **QuadWild** | QRemeshify addon **or** quadwild-bimdf binary | Warning — install one of the two |

---

## Quick Decision Guide

```
Need retopology?
│
├─ Fast, no setup needed?
│   └─► Quadriflow  (best built-in quality)
│
├─ Best possible automatic quads?
│   └─► QuadWild  →  install QRemeshify first
│
├─ Hard-surface / mechanical?
│   └─► Instant Meshes  →  download binary first
│        + enable Hard Edge Pre-pass in Advanced
│
├─ Just reduce poly count, keep topology?
│   └─► Decimate
│
└─ Quick base mesh for sculpting?
    └─► Voxel Remesh
```

---

## Version History

| Session | Changes |
|---|---|
| 1–2 | Quadriflow params, Instant Meshes CLI flags, Voxel Adaptivity, Hard Edge Pre-pass, Laplacian Smooth+Reproject, LOD Chain, Topology Metrics, Symmetric Strokes, Stroke Field Guidance |
| 3 | Curvature Pre-pass (Gaussian + Mean), math fixes (#11–#14): Voronoi area normalization, Scaled Jacobian, closest-point-on-segment, quadratic snap falloff |
| 4–5 | QuadWild mode (subprocess), Mesh Healing pre-pass, Cotangent Laplacian smooth |
| 6 | QRemeshify integration (auto-detect, bundled binary), mode-specific Advanced panel visibility, Blender 4.0+ crease layer fix, English addon + documentation |

---

## License

This addon is provided as-is for personal use.
External tools have their own licenses — see links above.
