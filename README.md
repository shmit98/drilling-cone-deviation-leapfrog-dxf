# Drill Hole Deviation Cone Generator

A desktop tool for underground mine drilling — generates 3D cone surfaces around drill holes to visualise the zone of potential breakthrough based on survey deviation uncertainty.

Output is a DXF file (3DFACE triangulated mesh) that can be imported directly into **Leapfrog Geo**, **Surpac**, or any other mining software that accepts DXF.

---

## What it does

Drill holes are never perfectly straight. Survey error accumulates with depth, meaning the deeper the hole, the further it could be from its planned path. This tool wraps each hole in a cone that represents the worst-case deviation envelope, plus an additional standoff buffer.

The cone radius at depth `d` along the hole:

```
radius(d) = standoff + d × tan(deviation_angle × d / reference_distance)
```

The half-angle of the cone grows linearly with depth — at `reference_distance` metres the cone has deviated `deviation_angle` degrees, and this rate continues to accumulate beyond that point.

**Example** — 5° over 50 m, 10 m standoff:

| Depth | Half-angle | Radius |
|-------|-----------|--------|
| 0 m   | 0°        | 10.0 m |
| 50 m  | 5°        | 14.4 m |
| 100 m | 10°       | 27.6 m |
| 150 m | 15°       | 50.2 m |

---

## Usage

1. Run `DrillConeGenerator.exe`
2. Browse to your input DXF (drill holes exported from Leapfrog, Surpac, etc.)
3. Set your deviation parameters and standoff distance
4. Click **Generate Cones**
5. Import the output DXF into your modelling software and check for intersections with stopes, drives, or other infrastructure

### Parameters

| Parameter | Description |
|-----------|-------------|
| **Deviation (°)** | Angular deviation at the reference depth |
| **Over distance (m)** | Reference depth for the above angle |
| **Standoff distance (m)** | Minimum radius at the collar — buffer added on top of the cone |
| **Circle segments** | Polygon resolution of each ring (16 is a good default) |
| **Sample interval (m)** | Spacing of cross-section rings along the hole |

The live preview at the bottom of the form shows the resulting radii at the collar, reference depth, and double the reference depth so you can sanity-check your inputs before generating.

---

## Input format

The input DXF should contain drill holes as **3D POLYLINE** or **LINE** entities, one per hole, on separate layers named by hole ID. This is the default export format from Leapfrog Geo and Surpac.

---

## Output format

- **Format:** ASCII DXF (R2000)
- **Entities:** `3DFACE` triangles — compatible with all major mining and CAD packages
- **Layers:** One layer per hole, named `CONE_<hole_id>`

---

## Building from source

Requires Python 3.12+ and the packages in the venv:

```powershell
# Create venv and install dependencies
python -m venv .venv
.\.venv\Scripts\pip install ezdxf numpy pyinstaller

# Build the EXE
.\build_exe.ps1
```

The standalone EXE will be output to `dist\DrillConeGenerator.exe`.

---

## Made by

**Jacob Smith** — [github.com/shmit98](https://github.com/shmit98)
