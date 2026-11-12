// Opens a built page, visits every desk it carries and reports what each rendered (v0.43). Used by
// scripts/prune_core.py to decide what the core page can leave out, and by the tests to check the core page.
//   node site/tests/core_probe.js PATH [--width=1280] [--views=a,b]
const { chromium } = require("playwright");
const path = require("path");
(async () => {
  const file = path.resolve(process.argv[2]);
  const arg = (k, d) => { const a = process.argv.find((x) => x.startsWith(`--${k}=`)); return a ? a.split("=")[1] : d; };
  const width = Number(arg("width", "1280"));
  // parts left out of the comparison between pages: the ones the core page cuts on purpose, and the glossary, which lists only the terms of the page it is on
  const CUT = arg("cut", "") ? arg("cut", "").split(",") : [];
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
  const errs = [];
  p.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 240)); });
  p.on("pageerror", (e) => errs.push("PAGEERROR " + String(e).slice(0, 240)));
  await p.addInitScript(() => { const t = Date.UTC(2026, 10, 12, 15, 0, 0); const D = Date; class F extends D { constructor(...a) { super(...(a.length ? a : [t])); } static now() { return t; } } window.Date = F; Math.random = () => 0.5; });
  await p.goto("file://" + file + "#home", { waitUntil: "load" });
  await p.waitForTimeout(1500);
  const views = arg("views", "") ? arg("views", "").split(",") : await p.evaluate(() => [...document.querySelectorAll("section.view")].map((v) => v.id.slice(5)));
  const out = { file, bytes: require("fs").statSync(file).size, views: {}, errs, overflow: [] };
  for (const v of views) {
    await p.evaluate((h) => { location.hash = h; }, v);
    await p.waitForTimeout(Number(arg("wait", "700")));
    out.views[v] = await p.evaluate(([v, cut]) => {
      const e = document.querySelector("#view-" + v);
      if (!e) return null;
      const hashOf = (t) => { let h = 0; for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) | 0; return h; };
      const txt = (e.textContent || "").replace(/\s+/g, " ").trim(), h = hashOf(txt);
      // the desk without the guide card and the way on, which name the page's own groups and so differ between pages
      const body = () => { const c = e.cloneNode(true); c.querySelectorAll(":scope > .dguide, :scope > .dnext").forEach((x) => x.remove()); cut.forEach((id) => { const x = c.querySelector("#" + id); if (x) x.remove(); }); return hashOf((c.textContent || "").replace(/\s+/g, " ").trim()); };
      return { shown: !e.hidden, chars: txt.length, hash: h, body_hash: body(), errors: [...e.querySelectorAll(".empty.error")].map((x) => x.textContent.slice(0, 120)), svgs: e.querySelectorAll("svg").length, rows: e.querySelectorAll("tr").length };
    }, [v, CUT]);
    // then use the desk: open what folds, move every slider, change every select, press every toggle, and read it again
    out.views[v].used = await p.evaluate(([v, cut]) => {
      const e = document.querySelector("#view-" + v);
      e.querySelectorAll("details").forEach((d) => { d.open = true; });
      e.querySelectorAll('input[type="range"]').forEach((r) => { const lo = Number(r.min || 0), hi = Number(r.max || 100); r.value = String(lo + (hi - lo) * 0.25); r.dispatchEvent(new Event("input", { bubbles: true })); });
      e.querySelectorAll("select").forEach((x) => { if (x.options.length > 1) { x.selectedIndex = x.options.length - 1; x.dispatchEvent(new Event("change", { bubbles: true })); x.dispatchEvent(new Event("input", { bubbles: true })); } });
      [...e.querySelectorAll('button[aria-pressed="false"]')].slice(0, 20).forEach((x) => { try { x.click(); } catch (err) { /* a toggle that navigates away is not this desk's */ } });
      const hashOf = (t) => { let h = 0; for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) | 0; return h; };
      const txt = (e.textContent || "").replace(/\s+/g, " ").trim();
      const c = e.cloneNode(true); c.querySelectorAll(":scope > .dguide, :scope > .dnext").forEach((x) => x.remove());
      cut.forEach((id) => { const x = c.querySelector("#" + id); if (x) x.remove(); });
      return { chars: txt.length, hash: hashOf(txt), body_hash: hashOf((c.textContent || "").replace(/\s+/g, " ").trim()), errors: e.querySelectorAll(".empty.error").length, marks: e.querySelectorAll("svg *").length };
    }, [v, CUT]);
    const ow = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (ow > 1) out.overflow.push([v, ow]);
  }
  // the things every page needs whatever it carries: search, the map of desks, the group links
  out.search = await p.evaluate(() => { const o = document.querySelector("#search-open"); if (!o) return null; o.click(); const q = document.querySelector("#palette-q"); q.value = "drawdown"; q.dispatchEvent(new Event("input", { bubbles: true })); const n = document.querySelectorAll("#palette-list li, #palette [role=option]").length; return n; });
  out.nav = await p.evaluate(() => [...document.querySelectorAll(".tabs a")].map((a) => [a.textContent.trim(), a.getAttribute("href")]));
  out.skipped = await p.evaluate(() => 0);
  console.log(JSON.stringify(out));
  await b.close();
})();
