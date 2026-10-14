"""Render docs/demo.gif: a top-down animation of the idea.

The fan is driven by the add-on's real controller (smoothing, deadband,
5 degree steps, at most one move every 2 s) fed with simulated FP2 readings
every 0.75 s, so the lag and the stepping are what the real thing does.

  python3 make_demo_gif.py [--out ../docs/demo.gif]
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

from fan_tracker.controller import Tracker, TrackerSettings  # noqa: E402
from fan_tracker.fp2 import Target  # noqa: E402
from fan_tracker.geometry import FanPose  # noqa: E402

SS = 2                     # supersampling factor
W, H = 760, 480            # output size
FPS = 12.5
U = 800.0 / 7.0            # FP2 raw units per metre

ROOM_W, ROOM_H = 3.4, 4.1  # metres
ORIGIN = (30, 34)          # room top-left in output pixels
PX_PER_M = 102

FP2 = (0.45, 0.13)
FAN = (0.24, 0.40)
WAYPOINTS = [(1.6, 1.0), (1.9, 2.5), (2.75, 3.35), (1.05, 3.45), (0.85, 1.75)]
PAUSES = {3: 2.0, 0: 1.4}  # waypoint index -> seconds standing still
SPEED = 0.55               # m/s, an indoor walking pace
SLEW = 40.0                # fan head deg/s
READING_DT = 0.75          # FP2 report interval

C = dict(bg=(255, 255, 255), floor=(247, 245, 240), wall=(58, 58, 60), window=(142, 201, 240),
         furn=(228, 225, 218), furn_edge=(204, 200, 191), label=(150, 146, 138),
         fp2=(47, 111, 222), air=(41, 182, 197), fan=(43, 45, 49), person=(240, 140, 46),
         head=(214, 112, 26), text=(34, 34, 36), muted=(110, 110, 116), hl=(66, 52, 180))


def font(size: int, bold: bool = False):
    names = (["Arial Bold.ttf", "DejaVuSans-Bold.ttf"] if bold else ["Arial.ttf", "DejaVuSans.ttf"])
    for n in names:
        for d in ("/System/Library/Fonts/Supplemental/", "/usr/share/fonts/truetype/dejavu/", ""):
            try:
                return ImageFont.truetype(d + n, size * SS)
            except OSError:
                pass
    return ImageFont.load_default(size * SS)


def px(p):
    """Room metres -> supersampled pixels."""
    return ((ORIGIN[0] + p[0] * PX_PER_M) * SS, (ORIGIN[1] + p[1] * PX_PER_M) * SS)


def rgba(c, a):
    return (*c, a)


# ------------------------------------------------------------------ the walk

def catmull_rom(pts, n=60):
    out = []
    k = len(pts)
    for i in range(k):
        p0, p1, p2, p3 = pts[(i - 1) % k], pts[i], pts[(i + 1) % k], pts[(i + 2) % k]
        for j in range(n):
            t = j / n
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * (2 * p1[d] + (-p0[d] + p2[d]) * t + (2 * p0[d] - 5 * p1[d] + 4 * p2[d] - p3[d]) * t2
                                    + (-p0[d] + 3 * p1[d] - 3 * p2[d] + p3[d]) * t3) for d in (0, 1)))
    return out, n


def walk_timeline():
    """List of (t, x, y, heading) at frame rate for one loop."""
    pts, n = catmull_rom(WAYPOINTS)
    seg = [math.dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    frames, t, dt = [], 0.0, 1.0 / FPS
    i, along = 0, 0.0
    heading = 0.0
    while i < len(pts):
        if i % n == 0 and along == 0.0 and (i // n) in PAUSES:
            for _ in range(int(PAUSES[i // n] * FPS)):
                frames.append((t, *pts[i], heading, False)); t += dt
        step = SPEED * dt
        while step > 0 and i < len(pts):
            room = seg[i] - along
            if step < room:
                along += step; step = 0
            else:
                step -= room; i += 1; along = 0.0
                if i < len(pts) and i % n == 0 and (i // n) in PAUSES:
                    break
        if i >= len(pts):
            break
        a, b = pts[i], pts[(i + 1) % len(pts)]
        f = along / seg[i] if seg[i] else 0
        x, y = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        heading = math.atan2(b[1] - a[1], b[0] - a[0])
        frames.append((t, x, y, heading, True)); t += dt
    return frames


# ------------------------------------------------------------------ simulation

def simulate(loops: int = 2):
    walk = walk_timeline()
    loop_t = walk[-1][0] + 1.0 / FPS
    pose = FanPose(FAN[0] * U, FAN[1] * U, heading_deg=90.0, mirror=-1)
    tr = Tracker(pose, TrackerSettings(pan_limits=(0.0, 85.0), tilt_mode="fixed", fixed_tilt_deg=5,
                                       units_per_meter=U))
    rng = random.Random(4)
    head, cmd, next_read = None, None, 0.0
    last_read, last_cmd_t, reading = -9.0, -9.0, None
    out = []
    for k in range(loops):
        for (t0, x, y, hd, moving) in walk:
            t = t0 + k * loop_t
            if t >= next_read:
                next_read += READING_DT
                rx, ry = x + rng.gauss(0, 0.03), y + rng.gauss(0, 0.03)
                reading = (rx, ry)
                last_read = t
                c = tr.update(t, [Target("1", rx * U, ry * U)])
                if c is not None:
                    cmd, last_cmd_t = c.pan, t
                    if head is None:
                        head = float(cmd)
            if head is not None and cmd is not None:
                d = cmd - head
                head += max(-SLEW / FPS, min(SLEW / FPS, d))
            out.append(dict(t=t, k=k, x=x, y=y, hd=hd, moving=moving, head=head, cmd=cmd,
                            reading=reading, since_read=t - last_read, since_cmd=t - last_cmd_t))
    return [f for f in out if f["k"] == loops - 1]


# ------------------------------------------------------------------ drawing

def room_mask():
    m = Image.new("L", (W * SS, H * SS), 0)
    x0, y0 = px((0, 0)); x1, y1 = px((ROOM_W, ROOM_H))
    ImageDraw.Draw(m).rectangle([x0, y0, x1, y1], fill=255)
    return m


def base_image(fonts):
    im = Image.new("RGB", (W * SS, H * SS), C["bg"])
    d = ImageDraw.Draw(im)
    x0, y0 = px((0, 0)); x1, y1 = px((ROOM_W, ROOM_H))
    d.rectangle([x0, y0, x1, y1], fill=C["floor"])
    for (a, b, label) in [((2.25, 0.15), (3.3, 2.05), "bed"), ((0.05, 2.75), (0.6, 4.0), "desk"),
                          ((0.05, 1.05), (0.35, 2.2), "shelf")]:
        d.rounded_rectangle([*px(a), *px(b)], radius=6 * SS, fill=C["furn"], outline=C["furn_edge"], width=SS)
        cx, cy = px(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
        d.text((cx, cy), label, fill=C["label"], font=fonts["small"], anchor="mm")
    d.rectangle([x0, y0, x1, y1], outline=C["wall"], width=4 * SS)
    wx0, _ = px((0.15, 0)); wx1, _ = px((2.1, 0))
    d.line([wx0, y0, wx1, y0], fill=C["window"], width=6 * SS)
    d.text(((wx0 + wx1) / 2, y0 - 12 * SS), "window", fill=C["label"], font=fonts["small"], anchor="mm")
    return im


def draw_frame(f, base, mask, fonts):
    im = base.copy().convert("RGBA")

    # FP2 field of view
    lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    cx, cy = px(FP2); r = 6.0 * PX_PER_M * SS
    d.pieslice([cx - r, cy - r, cx + r, cy + r], 52 - 60, 52 + 60, fill=rgba(C["fp2"], 7))
    for edge in (52 - 60, 52 + 60):
        e = math.radians(edge)
        d.line([(cx, cy), (cx + r * math.cos(e), cy + r * math.sin(e))], fill=rgba(C["fp2"], 45), width=SS)
    lay.putalpha(ImageChops.multiply(lay.getchannel("A"), mask))
    im.alpha_composite(lay)

    # airflow cone and puffs
    if f["head"] is not None:
        lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        fx, fy = px(FAN); L = 3.6 * PX_PER_M * SS; h = f["head"]
        d.pieslice([fx - L, fy - L, fx + L, fy + L], h - 9, h + 9, fill=rgba(C["air"], 46))
        for kk in range(8):
            dist = ((f["t"] * 1.7 + kk * 0.45) % 3.6) * PX_PER_M * SS
            if dist < 20 * SS:
                continue
            alpha = int(150 * (1 - dist / L))
            d.arc([fx - dist, fy - dist, fx + dist, fy + dist], h - 7, h + 7, fill=rgba(C["air"], alpha), width=3 * SS)
        lay.putalpha(ImageChops.multiply(lay.getchannel("A"), mask))
        im.alpha_composite(lay)

    d = ImageDraw.Draw(im)

    # reading: dotted line from the FP2 and a ping ring
    if f["reading"] is not None and f["since_read"] < 0.45:
        a = 1 - f["since_read"] / 0.45
        lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        dl = ImageDraw.Draw(lay)
        sx, sy = px(FP2); rx, ry = px((f["x"], f["y"]))
        n = int(math.dist((sx, sy), (rx, ry)) / (10 * SS))
        for i in range(0, n, 2):
            p0 = (sx + (rx - sx) * i / n, sy + (ry - sy) * i / n)
            p1 = (sx + (rx - sx) * (i + 1) / n, sy + (ry - sy) * (i + 1) / n)
            dl.line([p0, p1], fill=rgba(C["fp2"], int(190 * a)), width=2 * SS)
        rr = (16 + 12 * (1 - a)) * SS
        dl.ellipse([rx - rr, ry - rr, rx + rr, ry + rr], outline=rgba(C["fp2"], int(230 * a)), width=3 * SS)
        im.alpha_composite(lay)
        d = ImageDraw.Draw(im)

    # FP2 and fan
    sx, sy = px(FP2)
    d.rounded_rectangle([sx - 9 * SS, sy - 7 * SS, sx + 9 * SS, sy + 7 * SS], radius=3 * SS, fill=(255, 255, 255),
                        outline=C["fp2"], width=2 * SS)
    d.ellipse([sx - 3 * SS, sy - 3 * SS, sx + 3 * SS, sy + 3 * SS], fill=C["fp2"])
    d.text((sx + 13 * SS, sy + 2 * SS), "FP2", fill=C["fp2"], font=fonts["tiny_b"], anchor="lm")
    fx, fy = px(FAN)
    d.ellipse([fx - 15 * SS, fy - 15 * SS, fx + 15 * SS, fy + 15 * SS], fill=C["fan"])
    if f["head"] is not None:
        h = math.radians(f["head"])
        tip = (fx + 21 * SS * math.cos(h), fy + 21 * SS * math.sin(h))
        d.line([(fx, fy), tip], fill=C["fan"], width=10 * SS)
        d.ellipse([fx - 7 * SS, fy - 7 * SS, fx + 7 * SS, fy + 7 * SS], fill=(150, 154, 160))
    d.text((fx, fy + 24 * SS), "fan", fill=C["fan"], font=fonts["tiny_b"], anchor="mm")

    # person (a standard head-and-shoulders icon, bobbing while walking)
    pxl, pyl = px((f["x"], f["y"]))
    bob = abs(math.sin(f["t"] * 7)) * 2 * SS if f["moving"] else 0
    pyl -= bob
    d.pieslice([pxl - 15 * SS, pyl - 3 * SS, pxl + 15 * SS, pyl + 25 * SS], 180, 360, fill=C["person"])
    d.ellipse([pxl - 8 * SS, pyl - 19 * SS, pxl + 8 * SS, pyl - 3 * SS], fill=C["head"])
    on_you = False
    if f["head"] is not None:
        true = math.degrees(math.atan2(f["y"] - FAN[1], f["x"] - FAN[0]))
        on_you = abs(true - f["head"]) < 9
        if on_you:
            h = math.radians(f["head"])
            for kk in (-1, 0, 1):
                off = (-math.sin(h) * kk * 9 * SS, math.cos(h) * kk * 9 * SS)
                base_pt = (pxl + off[0] + math.cos(h) * 18 * SS, pyl + off[1] + math.sin(h) * 18 * SS)
                wob = math.sin(f["t"] * 14 + kk) * 3 * SS
                d.line([base_pt, (base_pt[0] + math.cos(h) * (12 * SS + wob), base_pt[1] + math.sin(h) * (12 * SS + wob))],
                       fill=C["air"], width=2 * SS)

    # right panel
    X0 = 410 * SS
    d.text((X0, 40 * SS), "Fan Tracker", fill=C["text"], font=fonts["title"], anchor="ls")
    d.text((X0, 62 * SS), "the fan you own follows you around the room", fill=C["muted"], font=fonts["small"], anchor="ls")
    rd = f["reading"]
    boxes = [
        (C["fp2"], "1  Aqara FP2 sees you",
         f"you are at x {rd[0]:.1f} m, y {rd[1]:.1f} m" if rd else "looking...", f["since_read"] < 0.35),
        (C["hl"], "2  Fan Tracker add-on",
         f"aim the fan at {f['cmd']}°" if f["cmd"] is not None else "waiting", f["since_cmd"] < 0.6),
        (C["air"], "3  Fan turns to follow",
         ("air on you" if on_you else f"turning to {f['cmd']}°") if f["head"] is not None else "",
         f["head"] is not None and f["cmd"] is not None and abs(f["cmd"] - f["head"]) > 0.5),
    ]
    y = 86 * SS
    for i, (col, title, line, lit) in enumerate(boxes):
        fill = tuple(int(255 - (255 - c) * 0.16) for c in col) if lit else (250, 250, 250)
        d.rounded_rectangle([X0, y, X0 + 320 * SS, y + 70 * SS], radius=10 * SS, fill=fill, outline=col, width=2 * SS)
        d.text((X0 + 16 * SS, y + 25 * SS), title, fill=col, font=fonts["head"], anchor="ls")
        d.text((X0 + 16 * SS, y + 52 * SS), line, fill=C["text"], font=fonts["body"], anchor="ls")
        y += 70 * SS
        if i < 2:
            ax = X0 + 160 * SS
            d.line([(ax, y + 4 * SS), (ax, y + 22 * SS)], fill=C["muted"], width=2 * SS)
            d.polygon([(ax - 6 * SS, y + 18 * SS), (ax + 6 * SS, y + 18 * SS), (ax, y + 26 * SS)], fill=C["muted"])
            y += 30 * SS
    notes = ["Fan moves are simulated with the project's own",
             "controller: 6° deadband, 5° steps, at most one",
             "move every 2 s, FP2 readings every 0.75 s."]
    for j, line in enumerate(notes):
        d.text((X0, (H - 54 + 16 * j) * SS), line, fill=C["muted"], font=fonts["tiny"], anchor="ls")

    return im.convert("RGB").resize((W, H), Image.LANCZOS)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(ROOT / "docs" / "demo.gif"))
    p.add_argument("--frames", type=int, default=0, help="render only the first N frames (preview)")
    a = p.parse_args()
    fonts = dict(title=font(24, True), head=font(15, True), body=font(14), small=font(12),
                 tiny=font(11), tiny_b=font(11, True))
    sim = simulate()
    if a.frames:
        sim = sim[:a.frames]
    base, mask = base_image(fonts), room_mask()
    frames = [draw_frame(f, base, mask, fonts) for f in sim]
    sample = Image.new("RGB", (W, H * 4))
    for i, fr in enumerate(frames[:: max(1, len(frames) // 4)][:4]):
        sample.paste(fr, (0, H * i))
    pal = sample.quantize(colors=160, method=Image.Quantize.MEDIANCUT)
    q = [fr.quantize(palette=pal, dither=Image.Dither.NONE) for fr in frames]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    q[0].save(out, save_all=True, append_images=q[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    print(f"{out}: {len(q)} frames, {len(q) / FPS:.1f} s, {out.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
