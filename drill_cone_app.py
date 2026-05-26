"""
Drill Hole Deviation Cone Generator
Wraps each drill hole in a 3-D cone representing the zone of potential
breakthrough, based on an angular deviation rate and a standoff buffer.

Cone radius at depth d:
    radius(d) = standoff + d * tan(deviation_deg * d / deviation_dist)

This grows quadratically with depth: the half-angle of the cone equals
deviation_deg at exactly deviation_dist metres, and doubles by 2*deviation_dist.
"""

import math
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import ezdxf
import numpy as np


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _perp_vectors(direction: np.ndarray):
    """Two orthonormal vectors perpendicular to `direction`."""
    d = direction / np.linalg.norm(direction)
    ref = np.array([1.0, 0.0, 0.0]) if abs(d[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    v1 = np.cross(d, ref)
    v1 /= np.linalg.norm(v1)
    v2 = np.cross(d, v1)
    v2 /= np.linalg.norm(v2)
    return v1, v2


def _circle_pts(centre: np.ndarray, direction: np.ndarray, radius: float, n: int):
    """Return n equally-spaced points on a circle centred at `centre`,
    lying in the plane perpendicular to `direction`."""
    v1, v2 = _perp_vectors(direction)
    pts = []
    for i in range(n):
        theta = 2 * math.pi * i / n
        pts.append(centre + radius * (math.cos(theta) * v1 + math.sin(theta) * v2))
    return pts


# ---------------------------------------------------------------------------
# DXF reading
# ---------------------------------------------------------------------------

def _collect_holes(msp):
    """Return list of (layer_name, [np.ndarray, ...]) from LINE / POLYLINE."""
    holes = []
    for ent in msp:
        layer = getattr(ent.dxf, 'layer', '0')
        etype = ent.dxftype()

        if etype == 'POLYLINE':
            pts = []
            for v in ent.vertices:
                loc = v.dxf.location
                pts.append(np.array([loc.x, loc.y, loc.z], dtype=float))
            if len(pts) >= 2:
                holes.append((layer, pts))

        elif etype == 'LINE':
            s, e = ent.dxf.start, ent.dxf.end
            holes.append((layer, [
                np.array([s.x, s.y, s.z], dtype=float),
                np.array([e.x, e.y, e.z], dtype=float),
            ]))
    return holes


# ---------------------------------------------------------------------------
# Cone generation
# ---------------------------------------------------------------------------

def generate_cones(
    input_path: str,
    output_path: str,
    deviation_deg: float,
    deviation_dist: float,
    standoff: float,
    n_segments: int,
    sample_interval: float,
    progress_cb=None,
):
    doc = ezdxf.readfile(input_path)
    holes = _collect_holes(doc.modelspace())

    out_doc = ezdxf.new('R2000')
    out_msp = out_doc.modelspace()

    rate = deviation_deg / deviation_dist  # deg / m

    def radius_at(d: float) -> float:
        angle_rad = math.radians(min(rate * d, 89.0))
        return standoff + d * math.tan(angle_rad)

    def v3(pt) -> tuple:
        return (float(pt[0]), float(pt[1]), float(pt[2]))

    total = len(holes)
    for hi, (layer_name, pts) in enumerate(holes):
        if progress_cb:
            progress_cb(hi, total, layer_name)

        cone_layer = f"CONE_{layer_name}"
        try:
            out_doc.layers.new(cone_layer)
        except ezdxf.lldxf.const.DXFTableEntryError:
            pass

        attribs = {'layer': cone_layer}

        # Sample points along the full hole path
        samples = []   # (centre, direction, cumulative_depth)
        cum_depth = 0.0

        for i in range(len(pts) - 1):
            seg_vec = pts[i + 1] - pts[i]
            seg_len = float(np.linalg.norm(seg_vec))
            if seg_len < 1e-6:
                continue
            seg_dir = seg_vec / seg_len

            t = 0.0
            while t < seg_len:
                samples.append((pts[i] + t * seg_dir, seg_dir, cum_depth + t))
                t += sample_interval

            cum_depth += seg_len

        # Always include the toe
        toe_dir = pts[-1] - pts[-2]
        toe_dir /= np.linalg.norm(toe_dir)
        samples.append((pts[-1], toe_dir, cum_depth))

        if len(samples) < 2:
            continue

        # Build cross-section circles at each sample
        circles = [
            _circle_pts(c, d, radius_at(dep), n_segments)
            for c, d, dep in samples
        ]

        n = n_segments

        # Lateral faces: each quad between adjacent rings → 2 triangles (3DFACE)
        for ci in range(len(circles) - 1):
            c0, c1 = circles[ci], circles[ci + 1]
            for si in range(n):
                nsi = (si + 1) % n
                p0, p1 = v3(c0[si]),  v3(c0[nsi])
                p2, p3 = v3(c1[nsi]), v3(c1[si])
                out_msp.add_3dface([p0, p1, p2, p2], dxfattribs=attribs)
                out_msp.add_3dface([p0, p2, p3, p3], dxfattribs=attribs)

        # Collar end cap
        collar = v3(samples[0][0])
        for si in range(n):
            p0 = v3(circles[0][si])
            p1 = v3(circles[0][(si + 1) % n])
            out_msp.add_3dface([collar, p0, p1, p1], dxfattribs=attribs)

        # Toe end cap
        toe_pt = v3(samples[-1][0])
        last = circles[-1]
        for si in range(n):
            p0 = v3(last[si])
            p1 = v3(last[(si + 1) % n])
            out_msp.add_3dface([toe_pt, p1, p0, p0], dxfattribs=attribs)

    if progress_cb:
        progress_cb(total, total, "Done")

    out_doc.saveas(output_path)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

_PAD = {'padx': 8, 'pady': 4}
_EW = 14   # entry width for numeric fields


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Drill Hole Deviation Cone Generator")
        self.resizable(False, False)
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        f = ttk.Frame(self, padding=14)
        f.grid(sticky='nsew')
        row = 0

        # File paths
        ttk.Label(f, text="Input DXF:").grid(row=row, column=0, sticky='e', **_PAD)
        self.v_input = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_input, width=44).grid(row=row, column=1, **_PAD)
        ttk.Button(f, text="Browse…", command=self._pick_input).grid(row=row, column=2, **_PAD)
        row += 1

        ttk.Label(f, text="Output DXF:").grid(row=row, column=0, sticky='e', **_PAD)
        self.v_output = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_output, width=44).grid(row=row, column=1, **_PAD)
        ttk.Button(f, text="Browse…", command=self._pick_output).grid(row=row, column=2, **_PAD)
        row += 1

        ttk.Separator(f, orient='horizontal').grid(
            row=row, column=0, columnspan=3, sticky='ew', pady=10)
        row += 1

        # Cone parameters
        ttk.Label(f, text="Cone parameters", font=('TkDefaultFont', 9, 'bold')).grid(
            row=row, column=0, columnspan=3, sticky='w', padx=8)
        row += 1

        def param_row(label, var, hint=''):
            nonlocal row
            ttk.Label(f, text=label).grid(row=row, column=0, sticky='e', **_PAD)
            ttk.Entry(f, textvariable=var, width=_EW).grid(row=row, column=1, sticky='w', **_PAD)
            if hint:
                ttk.Label(f, text=hint, foreground='gray').grid(
                    row=row, column=2, sticky='w', **_PAD)
            row += 1

        self.v_deg = tk.DoubleVar(value=5.0)
        self.v_dist = tk.DoubleVar(value=50.0)
        self.v_standoff = tk.DoubleVar(value=10.0)

        param_row("Deviation (°):", self.v_deg, "angular deviation")
        param_row("Over distance (m):", self.v_dist, "reference depth for above angle")
        param_row("Standoff distance (m):", self.v_standoff, "min radius at collar")

        ttk.Separator(f, orient='horizontal').grid(
            row=row, column=0, columnspan=3, sticky='ew', pady=10)
        row += 1

        ttk.Label(f, text="Mesh quality", font=('TkDefaultFont', 9, 'bold')).grid(
            row=row, column=0, columnspan=3, sticky='w', padx=8)
        row += 1

        self.v_segs = tk.IntVar(value=16)
        self.v_interval = tk.DoubleVar(value=5.0)

        param_row("Circle segments:", self.v_segs, "≥ 8 recommended")
        param_row("Sample interval (m):", self.v_interval, "along-hole spacing of rings")

        # Live preview of radii
        self.v_info = tk.StringVar()
        ttk.Label(f, textvariable=self.v_info, foreground='#0066aa').grid(
            row=row, column=0, columnspan=3, padx=8, pady=2)
        row += 1

        for v in (self.v_deg, self.v_dist, self.v_standoff):
            v.trace_add('write', lambda *_: self._refresh_preview())
        self._refresh_preview()

        ttk.Separator(f, orient='horizontal').grid(
            row=row, column=0, columnspan=3, sticky='ew', pady=10)
        row += 1

        ttk.Button(
            f, text="  Generate Cones  ", command=self._run
        ).grid(row=row, column=0, columnspan=3, pady=6)
        row += 1

        self.v_status = tk.StringVar(value="Ready.")
        ttk.Label(f, textvariable=self.v_status).grid(
            row=row, column=0, columnspan=3, padx=8)
        row += 1

        self.bar = ttk.Progressbar(f, length=480, mode='determinate')
        self.bar.grid(row=row, column=0, columnspan=3, padx=8, pady=6)

    # ------------------------------------------------------------------
    def _refresh_preview(self):
        try:
            deg = self.v_deg.get()
            dist = self.v_dist.get()
            so = self.v_standoff.get()
            if dist <= 0:
                return
            rate = deg / dist

            def r(d):
                return so + d * math.tan(math.radians(min(rate * d, 89.0)))

            self.v_info.set(
                f"Radius preview  →  collar: {so:.1f} m  |  "
                f"{dist:.0f} m: {r(dist):.1f} m  |  "
                f"{2*dist:.0f} m: {r(2*dist):.1f} m"
            )
        except Exception:
            pass

    def _pick_input(self):
        p = filedialog.askopenfilename(
            title="Select drill hole DXF",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")])
        if p:
            self.v_input.set(p)
            base = os.path.splitext(p)[0]
            self.v_output.set(f"{base}_cones.dxf")

    def _pick_output(self):
        p = filedialog.asksaveasfilename(
            title="Save cone DXF as",
            defaultextension=".dxf",
            filetypes=[("DXF files", "*.dxf")])
        if p:
            self.v_output.set(p)

    def _run(self):
        inp = self.v_input.get().strip()
        out = self.v_output.get().strip()

        if not inp or not os.path.isfile(inp):
            messagebox.showerror("Error", "Select a valid input DXF file.")
            return
        if not out:
            messagebox.showerror("Error", "Specify an output file path.")
            return

        try:
            deg = float(self.v_deg.get())
            dist = float(self.v_dist.get())
            so = float(self.v_standoff.get())
            segs = int(self.v_segs.get())
            interval = float(self.v_interval.get())
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        if dist <= 0 or interval <= 0 or segs < 3:
            messagebox.showerror("Invalid input",
                "Distance and interval must be > 0; segments must be ≥ 3.")
            return

        self.bar['value'] = 0
        self.v_status.set("Processing…")
        self.update()

        def on_progress(current, total, name):
            pct = 100 * current / total if total else 100
            self.after(0, lambda p=pct, c=current, t=total, n=name:
                self._set_progress(p, c, t, n))

        def worker():
            try:
                generate_cones(inp, out, deg, dist, so, segs, interval, on_progress)
                self.after(0, lambda: self._on_done(out))
            except Exception as exc:
                self.after(0, lambda e=exc: self._on_error(e))

        threading.Thread(target=worker, daemon=True).start()

    def _set_progress(self, pct, current, total, name):
        self.bar['value'] = pct
        self.v_status.set(f"Hole {current} / {total}  —  {name}")

    def _on_done(self, out_path):
        self.bar['value'] = 100
        self.v_status.set(f"Done  →  {os.path.basename(out_path)}")
        messagebox.showinfo(
            "Complete",
            f"Cones generated successfully!\n\nSaved to:\n{out_path}")

    def _on_error(self, exc):
        self.bar['value'] = 0
        self.v_status.set(f"Error: {exc}")
        messagebox.showerror("Error", str(exc))


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    App().mainloop()
