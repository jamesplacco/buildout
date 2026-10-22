"""Write the Buildout mark, the Today desk's guilloche rosette (the green lotus) exactly as views.js draws it, as an
SVG symbol (site/src/logo.html) and the page icon (site/src/favicon.svg). Same curves, same colours, same hairlines.

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


def rosette(steps_in: int = 700, steps_out: int = 450) -> str:
    """The Today desk's rosette exactly (views.js drawRosette): on a 330 by 330 field centred at 165, 18
    hypotrochoids (R 120, r 45, pen 36 + 2.2k, turned k pi / 54) in the accent at half opacity, inside 10
    epitrochoids (R 140, r 10, pen 6 + 0.6k, turned 0.05k) in the muted ink at 0.35; hairlines of 0.6 pixels at
    every size, as the canvas draws them."""
    inner = " ".join(path(hypo(120, 45, 36 + k * 2.2, k * math.pi / 54, steps=steps_in), 1.0, 165.0) for k in range(18))
    outer = " ".join(path(epi(140, 10, 6 + k * 0.6, k * 0.05, steps=steps_out), 1.0, 165.0) for k in range(10))
    vs = 'vector-effect="non-scaling-stroke"'
    # the hairline and its opacity are the canvas's (0.6 px at 0.5 and 0.35); a page may thicken them for a small
    # rendering through --lotus-w and --lotus-o, which reach inside the symbol because custom properties inherit
    return (f'<path d="{inner}" fill="none" stroke="currentColor" style="stroke-width: var(--lotus-w, 0.6px); opacity: var(--lotus-o, 0.5)" {vs}/>'
            f'<path d="{outer}" fill="none" stroke="var(--muted, #6f7c76)" style="stroke-width: var(--lotus-w, 0.6px); opacity: calc(var(--lotus-o, 0.5) * 0.7)" {vs}/>')


def main() -> None:
    ro = rosette()
    (ROOT / "site" / "src" / "logo.html").write_text(
        '<svg class="sprite" width="0" height="0" aria-hidden="true" focusable="false" style="position:absolute;width:0;height:0;overflow:hidden">'
        f'<symbol id="lotus" viewBox="0 0 330 330">{ro}</symbol></svg>\n')
    fav = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 330 330" color="#1d5b49">{rosette(200, 130).replace("var(--muted, #6f7c76)", "#6f7c76")}</svg>'
    (ROOT / "site" / "src" / "favicon.svg").write_text(fav)
    print("logo.html", len(ro), "bytes; favicon", len(fav))


if __name__ == "__main__":
    main()
