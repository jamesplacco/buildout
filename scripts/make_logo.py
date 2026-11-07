"""Write the Buildout mark, the Today desk's guilloche rosette (the green lotus) exactly as views.js draws it, as an
SVG symbol (site/src/logo.html) and the page icon (site/src/favicon.svg, and the 64 px favicon.png the page embeds). Same curves, same colours, same hairlines.

    python scripts/make_logo.py
"""
from __future__ import annotations

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


def simplify(pts, tol):
    """Ramer-Douglas-Peucker: drop points within tol of the chord. At the 120 px the mark is drawn at most, 0.25 of
    its 330 units is 0.09 px, below what a screen shows; the page loses most of the logo's bytes (v0.40.1)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        n = math.hypot(dx, dy) or 1e-12
        far, idx = 0.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / n if n > 1e-9 else math.hypot(px - ax, py - ay)
            if d > far:
                far, idx = d, i
        if far > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def _num(v):
    t = f"{v:.1f}".rstrip("0").rstrip(".")
    t = t.replace("0.", ".", 1) if t.startswith("0.") else t.replace("-0.", "-.", 1)
    return "0" if t in ("", "-0", "-") else t


def path(pts, scale, c=50.0, tol=0.25):
    """Absolute first point, then relative steps between the rounded points, so rounding never accumulates."""
    q = [(round((c + x * scale) * 10), round((c + y * scale) * 10)) for x, y in simplify(pts, tol / scale)]
    out = [f"M{_num(q[0][0] / 10)} {_num(q[0][1] / 10)}"]
    for (x0, y0), (x1, y1) in zip(q, q[1:]):
        dx, dy = _num((x1 - x0) / 10), _num((y1 - y0) / 10)
        out.append(f"l{dx}{dy if dy.startswith('-') else ' ' + dy}")
    return "".join(out) + "Z"


def rosette(steps_in: int = 700, steps_out: int = 450) -> str:
    """The Today desk's rosette exactly (views.js drawRosette): on a 330 by 330 field centred at 165, 18
    hypotrochoids (R 120, r 45, pen 36 + 2.2k, turned k pi / 54) in the accent at half opacity, inside 10
    epitrochoids (R 140, r 10, pen 6 + 0.6k, turned 0.05k) in the muted ink at 0.35; hairlines of 0.6 pixels at
    every size, as the canvas draws them."""
    inner = " ".join(path(hypo(120, 45, 36 + k * 2.2, k * math.pi / 54, steps=steps_in), 1.0, 165.0) for k in range(18))
    outer = " ".join(path(epi(140, 10, 6 + k * 0.6, k * 0.05, steps=steps_out), 1.0, 165.0) for k in range(10))
    # the canvas draws 0.6 px lines on a rosette about 260 px across: 0.76 units of this 330-unit field, scaling with
    # the mark so a small rendering is the same drawing shrunk; --lotus-w and --lotus-o let a very small rendering
    # thicken it a little (custom properties inherit into the symbol)
    return (f'<path d="{inner}" fill="none" stroke="currentColor" style="stroke-width: var(--lotus-w, 0.76); opacity: var(--lotus-o, 0.5)"/>'
            f'<path d="{outer}" fill="none" stroke="var(--muted, #6f7c76)" style="stroke-width: var(--lotus-w, 0.76); opacity: calc(var(--lotus-o, 0.5) * 0.7)"/>')


def main() -> None:
    ro = rosette()
    (ROOT / "site" / "src" / "logo.html").write_text(
        '<svg class="sprite" width="0" height="0" aria-hidden="true" focusable="false" style="position:absolute;width:0;height:0;overflow:hidden">'
        f'<symbol id="lotus" viewBox="0 0 330 330">{ro}</symbol></svg>\n')
    fav = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 330 330" color="#1d5b49">{rosette(200, 130).replace("var(--muted, #6f7c76)", "#6f7c76").replace("var(--lotus-w, 0.76)", "3.2").replace("var(--lotus-o, 0.5)", "0.85")}</svg>'
    (ROOT / "site" / "src" / "favicon.svg").write_text(fav)
    png = favicon_png(fav)
    if png:
        (ROOT / "site" / "src" / "favicon.png").write_bytes(png)
    print("logo.html", len(ro), "bytes; favicon", len(fav), "svg,", len(png or b""), "png")


def favicon_png(svg: str, size: int = 64) -> bytes | None:
    """The tab icon as a 64 px PNG: a browser draws it at 16 to 32 px, where the vector adds bytes and nothing else."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page(viewport={"width": size, "height": size})
        p.set_content(f'<body style="margin:0;background:transparent">{svg.replace("<svg ", f"<svg width=\"{size}\" height=\"{size}\" ", 1)}</body>')
        out = p.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": size, "height": size})
        b.close()
    return out


if __name__ == "__main__":
    main()
