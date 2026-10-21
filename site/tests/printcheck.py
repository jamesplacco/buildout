"""Print-layout checks on a PDF of the page: text drawn on top of text, and pages that came out empty.

Uses pdftotext from poppler-utils (apt install poppler-utils; brew install poppler). Page breaks
inside nested CSS grids can misplace the rows after them, which only shows up in print; this finds
it from the word boxes instead of by eye.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from html import unescape

WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
LINE = re.compile(r'<line xMin="[\d.]+" yMin="[\d.]+" xMax="[\d.]+" yMax="[\d.]+">(.*?)</line>', re.S)


def available() -> bool:
    return shutil.which("pdftotext") is not None


def pages(pdf: str) -> list[list[list[tuple[float, float, float, float, str]]]]:
    """Per page, per text line, the words with their boxes."""
    out = subprocess.run(["pdftotext", "-bbox-layout", pdf, "-"], capture_output=True, text=True, check=True).stdout
    return [[[(float(a), float(b), float(c), float(d), unescape(t)) for a, b, c, d, t in WORD.findall(ln.group(1))]
             for ln in LINE.finditer(pg.group(1))]
            for pg in re.finditer(r"<page[^>]*>(.*?)</page>", out, re.S)]


def overlaps(pdf: str, min_width_share: float = 0.35) -> list[tuple[int, str, str]]:
    """(page, word, other word) for words from different lines whose boxes share most of their height
    and a real part of their width. Stacked lines with tight leading touch; they do not share height."""
    found = []
    for pno, lines in enumerate(pages(pdf), 1):
        flat = [(li, w) for li, ws in enumerate(lines) for w in ws]
        for i, (li, (x0, y0, x1, y1, t)) in enumerate(flat):
            for lj, (a0, b0, a1, b1, u) in flat[i + 1:]:
                if li == lj:
                    continue
                ix, iy = min(x1, a1) - max(x0, a0), min(y1, b1) - max(y0, b0)
                if ix <= 0 or iy <= 0:
                    continue
                hmin, wmin = min(y1 - y0, b1 - b0), min(x1 - x0, a1 - a0)
                if hmin > 0 and wmin > 0 and iy / hmin >= 0.5 and ix / wmin >= min_width_share:
                    found.append((pno, t, u))
    return found


def empty_pages(pdf: str) -> list[int]:
    return [i for i, lines in enumerate(pages(pdf), 1) if not any(lines)]
