"""v0.46: a layout a first-time reader can find their way around.

Three changes, each to where things sit and none to what they say. A desk's sections ride beside it in a rail on a
wide screen (and fold to one line on a narrow one), so the first figure is on the first screen and the reader can
see where they are in a desk that runs to seventy screens. Desk headlines are smaller. On Today's call the six
readings behind the call sit beside the three steps. These tests pin the structure; site/tests/stress.py checks it
in a browser (the rail's lines against the page's headings, a folded section opened from the rail, the fold at
900 px).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"


def _css():
    head = (SRC / "head.html").read_text()
    return head[head.index("/* v0.46: THE SHELL."):]


def test_the_rail_is_one_element_filled_from_the_page():
    body, guide, boot = ((SRC / f).read_text() for f in ("body.html", "guide.js", "boot.js"))
    assert body.count('<aside class="rail" id="rail" aria-label="On this desk" hidden></aside>') == 1
    main = body[body.index('<main class="page" id="main"'):]
    assert main.index('id="rail"') < main.index('<section class="view"'), "the rail comes before the desks in reading order"
    # built after the desk has rendered and folded, from the page's own sections in the page's order
    assert 'guard("Rail", () => { railFor(view); guideHere(); });' in boot
    assert boot.index('guard("Fold", () => foldDesk(view));') < boot.index('guard("Rail"')
    fn = guide[guide.index("function railFor(v) {"):guide.index("function railMark(cur) {")]
    assert 'el.matches("section.section")' in fn and 'el.matches("details.desk-more")' in fn, "folded sections are listed too"
    assert "if (!more) n += 1;" in fn, "the number is the one the page prints over the section"
    assert "const on = rows.length >= 2;" in fn and 'page.classList.toggle("has-rail", on);' in fn and "rail.hidden = !on;" in fn
    assert 'a.dataset.for = r.h2.id;' in fn and 'a.href = "#" + r.h2.id;' in fn
    # a label that says nothing alone falls back to the heading
    assert r'!/^tool\b/i.test(r.short)' in fn and "seen[r.short.toLowerCase()] === 1" in fn


def test_the_section_being_read_is_marked():
    guide = (SRC / "guide.js").read_text()
    here = guide[guide.index("function guideHere() {"):guide.index("const RAIL = ")]
    assert "x.offsetParent !== null && x.getBoundingClientRect().top < 140" in here, "a heading in a closed fold is not on the page"
    assert here.index("railMark(cur);") < here.index("if (!here) return;"), "the rail is marked whether or not the band shows the name"
    mark = guide[guide.index("function railMark(cur) {"):]
    mark = mark[:mark.index("\n  }\n") + 5]
    assert 'a.setAttribute("aria-current", "location")' in mark and 'a.removeAttribute("aria-current")' in mark
    assert "scrollIntoView" not in mark, "keeping the line in sight must not move the page"
    # the headings are read again in the page's order once the desk has folded
    assert guide.count(":scope > details.desk-more > .section > .section-head h2") == 2


def test_the_shell_and_the_fold_on_a_narrow_screen():
    css, views = _css(), (SRC / "views.js").read_text()
    assert ".topbar-inner, .subtabs, .page { max-width: 1352px; }" in css
    wide = css[css.index("@media screen and (min-width: 1200px) {"):]
    wide = wide[:wide.index("\n}\n")]
    for rule in (".page.has-rail { display: grid; grid-template-columns: minmax(0, 1fr) 232px;",
                 ".page.has-rail > .view { grid-column: 1; grid-row: 1; max-width: none; min-width: 0; }",
                 ".page.has-rail > .view > .toc { display: none; }",
                 "position: sticky; top: 132px;", "overflow-y: auto;"):
        assert rule in wide, rule
    # the rail never prints, and nothing here reaches print: these rules sit last in the sheet and would outrank it
    head = (SRC / "head.html").read_text()
    every = head[head.index("/* v0.46 (all media):"):head.index("/* v0.46: THE SHELL.")]
    assert ".rail { display: none; }" in every and every.rstrip().endswith("@media screen {")
    assert [line for line in every.splitlines() if line.startswith(".")] == [line for line in every.splitlines() if line.startswith((".rail {", ".toc-toggle {", ".toc-n {"))]
    assert head.rstrip().endswith("}\n}\n</style>") or head.rstrip().endswith("}\n</style>")
    narrow = css[css.index("@media screen and (max-width: 1199.98px) {"):]
    narrow = narrow[:narrow.index("\n}\n")]
    assert ".view > .toc:not(.open) > a { display: none; }" in narrow
    # the label over the list is the button that opens it
    assert 'h("button", "flabel toc-toggle")' in views and 'b.setAttribute("aria-expanded", "false");' in views
    assert 'b.setAttribute("aria-expanded", String(nav.classList.toggle("open")))' in views


def test_desk_heads_are_smaller_and_the_call_shows_its_readings():
    css = _css()
    assert ".vhead h1 { font-size: clamp(1.9rem, 3.3vw, 2.75rem);" in css
    assert ".view { gap: 56px; padding-block: 28px 72px; }" in css and ".view > .dguide { margin-top: -30px;" in css
    call = css[css.index("/* v0.46: TODAY'S CALL."):]
    for rule in (".t7 > .t7-head { display: contents; }", ".t7 > .t7-head > .t7-answer { grid-column: 1; grid-row: 3; }",
                 ".t7 > .call-board { grid-column: 2; grid-row: 3;"):
        assert rule in call, rule
    assert call.index("@media screen and (min-width: 1200px) {") < call.index(".t7 > .t7-head { display: contents; }")
    body = (SRC / "body.html").read_text()
    desk = body[body.index('id="view-desk"'):]
    assert desk.index('class="t7-head"') < desk.index('id="call-board"'), "the reading order is still the call, then the board"


def test_the_node_graphs_stack_by_their_own_width():
    # the causal map and the knowledge graph place labels for the width they get; beside a rail two columns left them
    # too narrow and two labels collided (the print run found it), so the choice is made on their own box
    css = _css()
    assert ".hero-brain, #view-brain > .section { container-type: inline-size; }" in css
    assert "@container (max-width: 1100px) { .hero-grid, .brain-lab { grid-template-columns: minmax(0, 1fr); } }" in css


def test_version_and_notes():
    import buildout
    assert buildout.__version__ >= "0.46.0"
    assert '["v0.46", "Nov 16, 2026"' in (SRC / "reference.js").read_text() and "Version 0.46:" in (ROOT / "CHANGELOG.md").read_text()
    for p in ("tests/test_v46.py", "site/src/guide.js", "site/src/views.js"):
        low = (ROOT / p).read_text().lower()
        for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
            assert b not in low, (p, b)
    assert not re.search(r"DATABENTO_API_KEY=", (SRC / "head.html").read_text())
