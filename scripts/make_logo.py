"""Write the Buildout mark, the guilloche lotus of the Today desk's rosette, as SVG symbols (site/src/logo.html) and a
favicon. The curves are the rosette's own: hypotrochoids with R = 120 and r = 45 (five petals over three turns),
nudged in pen offset and rotation, inside a ring of epitrochoids. A small cut with fewer, bolder curves stays legible
at 16 to 32 pixels; the full cut is for 48 pixels and up.

    python scripts/make_logo.py
"""
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def hypo(R, r, d, rot, turns=3, steps=420):
    k = (R - r) / r
    pts = []
    for i in range(steps + 1):
        t = i / steps * 2 * math.pi * turns
        x = (R - r) * math.cos(t) + d * math.cos(k * t)
        y = (R - r) * math.sin(t) - d * math.sin(k * t)
        pts.append((x * math.cos(rot) - y * math.sin(rot), x * math.sin(rot) + y * math.cos(rot)))
    return pts


def epi(R, r, d, rot, steps=360):
    pts = []
    for i in range(steps + 1):
        t = i / steps * 2 * math.pi
        x = (R + r) * math.cos(t) - d * math.cos((R + r) / r * t)
        y = (R + r) * math.sin(t) - d * math.sin((R + r) / r * t)
        pts.append((x * math.cos(rot) - y * math.sin(rot), x * math.sin(rot) + y * math.cos(rot)))
    return pts


def path(pts, scale, c=50.0):
    return "M" + "L".join(f"{c + x * scale:.1f} {c + y * scale:.1f}" for x, y in pts) + "Z"


def build(cut: str) -> str:
    """Hairlines that stay hairlines at every size (non-scaling strokes), as the canvas rosette draws them. The small
    cut keeps three curves so the five loops read at 16 to 32 pixels; the middle cut eight; the full cut all 18."""
    scale = 46.0 / 162.0                                         # the outer ring's reach (150 + a pen of 11.4) to 46 units
    n = {"sm": 3, "md": 8, "lg": 18}[cut]
    inner = " ".join(path(hypo(120, 45, 36 + (k * 17 / max(1, n - 1)) * 2.2, (k * 17 / max(1, n - 1)) * math.pi / 54, steps=240 if cut == "sm" else 420), scale) for k in range(n))
    vs = 'vector-effect="non-scaling-stroke"'
    if cut == "sm":
        ring = f'<circle cx="50" cy="50" r="47" fill="none" stroke="currentColor" stroke-width="1" opacity="0.45" {vs}/>'
        return ring + f'<path d="{inner}" fill="none" stroke="currentColor" stroke-width="1.1" {vs}/>'
    if cut == "md":
        ring = f'<circle cx="50" cy="50" r="47.5" fill="none" stroke="currentColor" stroke-width="0.8" opacity="0.4" {vs}/>'
        return ring + f'<path d="{inner}" fill="none" stroke="currentColor" stroke-width="0.8" opacity="0.85" {vs}/>'
    rr = " ".join(path(epi(140, 10, 6 + k * 0.6, k * 0.05), scale) for k in range(10))
    return (f'<path d="{rr}" fill="none" stroke="var(--muted, #6f7c76)" stroke-width="0.6" opacity="0.4" {vs}/>'
            f'<path d="{inner}" fill="none" stroke="currentColor" stroke-width="0.6" opacity="0.6" {vs}/>')


def main() -> None:
    sm, md, lg = build("sm"), build("md"), build("lg")
    (ROOT / "site" / "src" / "logo.html").write_text(
        '<svg class="sprite" width="0" height="0" aria-hidden="true" focusable="false" style="position:absolute;width:0;height:0;overflow:hidden">'
        f'<symbol id="lotus-sm" viewBox="0 0 100 100">{sm}</symbol><symbol id="lotus-md" viewBox="0 0 100 100">{md}</symbol>'
        f'<symbol id="lotus" viewBox="0 0 100 100">{lg}</symbol></svg>\n')
    fav = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" color="#1d5b49">{sm}</svg>'
    (ROOT / "site" / "src" / "favicon.svg").write_text(fav)
    print("logo.html", len(sm) + len(md) + len(lg), "bytes; favicon", len(fav))


if __name__ == "__main__":
    main()
