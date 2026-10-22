  /* =====================================================================================
     keys.js (v0.15): Vim and Emacs on the page. Pick a key mode in the shortcuts dialog (?) or type :set keys=vim.
     Vim:   j k scroll, d u half a page, gg G top and bottom, ]] [[ next and previous section, gt gT next and previous
            desk, / search, : command line, yy copy this desk's link, Esc close.
     Emacs: C-n C-p scroll, C-v M-v a page, M-< M-> top and bottom, C-s search, M-x command line, C-x o next desk, C-g quit.
     The command line (: or M-x) takes: think <question>, whatif <condition>, go <desk>, triage <sharpe> <years> [tries],
     erp <cash yield %> <growth %>, set keys=vim|emacs|default, math, help, q.
     ===================================================================================== */
  const KY = { mode: "default", buf: "", t: 0, hist: [], hi: -1, ret: null };
  try { const m = localStorage.getItem("buildout.keys"); if (m === "vim" || m === "emacs") KY.mode = m; } catch (e) { /* storage blocked */ }
  const KY_CMDS = ["think", "whatif", "go", "triage", "erp", "set keys=vim", "set keys=emacs", "set keys=default", "math", "help", "q"];
  function kySetMode(m) {
    KY.mode = m;
    try { localStorage.setItem("buildout.keys", m); } catch (e) { /* storage blocked */ }
    const badge = $("#ky-badge");
    if (badge) { badge.hidden = m === "default"; badge.textContent = m === "vim" ? "NORMAL" : m === "emacs" ? "Emacs keys" : ""; }
    document.querySelectorAll("#ky-mode button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.m === m ? "true" : "false"));
  }
  function kyScroll(dy) { window.scrollBy({ top: dy, behavior: "auto" }); }
  function kySection(dir) {
    const hs = [...document.querySelectorAll(`#view-${current} h2`)].filter((x) => x.offsetParent);
    const y = window.scrollY + 90;
    const t = dir > 0 ? hs.find((x) => x.getBoundingClientRect().top + window.scrollY > y + 4) : hs.reverse().find((x) => x.getBoundingClientRect().top + window.scrollY < y - 4);
    if (t) window.scrollTo({ top: t.getBoundingClientRect().top + window.scrollY - 80 });
  }
  function kyDesk(dir) {
    const i = VIEWS.indexOf(current), v = VIEWS[(i + dir + VIEWS.length) % VIEWS.length];
    location.hash = v;
  }
  function kyFlash(msg) { const s = $("#ky-msg"); if (!s) return; s.textContent = msg; s.hidden = false; clearTimeout(KY.t2); KY.t2 = setTimeout(() => { s.hidden = true; }, 3200); }
  function kyOpen(prompt) {
    const bar = $("#ky-bar");
    KY.ret = document.activeElement;
    $("#ky-prompt").textContent = prompt;
    bar.hidden = false;
    const q = $("#ky-q"); q.value = ""; KY.hi = -1; q.focus();
  }
  function kyClose() { $("#ky-bar").hidden = true; if (KY.ret && document.contains(KY.ret)) KY.ret.focus(); KY.ret = null; }
  function kyThink(q) {
    MDK.pending = q;
    if (current === "mind") renderMindDesk(); else location.hash = "mind";
  }
  function kyRun(line) {
    const t = line.trim();
    if (!t) return;
    KY.hist.unshift(t);
    const [cmd, ...rest] = t.split(/\s+/), arg = rest.join(" ");
    const c = cmd.replace(/^:/, "").toLowerCase();
    if (c === "think" || c === "ask") { if (arg) kyThink(arg); else kyFlash("think needs a question: think Is AI a bubble?"); }
    else if (c === "whatif" || c === "what-if") { if (arg) kyThink("What if " + arg); else kyFlash("whatif needs a condition: whatif oil spikes, what happens to the book"); }
    else if (c === "go" || c === "e" || c === "b") {
      const k = arg.toLowerCase().replace(/^#/, "");
      const v = VIEWS.find((x) => x === k) || VIEWS.find((x) => (TAB_NAME[x] || "").toLowerCase() === k) || VIEWS.find((x) => (TAB_NAME[x] || "").toLowerCase().startsWith(k) || x.startsWith(k));
      if (v) location.hash = v; else kyFlash(`No desk called "${arg}". Try: ${VIEWS.slice(0, 8).join(", ")}…`);
    }
    else if (c === "triage") {
      const [sr, yrs, n] = rest.map(Number);
      if (![sr, yrs].every(fin)) { kyFlash("triage <sharpe> <years> [tries], e.g. triage 1.2 8 40"); return; }
      location.hash = "reality";
      setTimeout(() => { if ($("#rt-sr")) { $("#rt-sr").value = sr; $("#rt-yrs").value = yrs; if (fin(n)) $("#rt-n").value = n; $("#rt-sr").dispatchEvent(new Event("input")); $("#rt-triage-title").scrollIntoView({ block: "start" }); } }, 60);
    }
    else if (c === "erp") {
      const [cy, g] = rest.map(Number);
      if (![cy, g].every(fin)) { kyFlash("erp <cash yield %> <growth %>, e.g. erp 3.5 6"); return; }
      location.hash = "edge";
      setTimeout(() => { if ($("#ed-erp-cy")) { $("#ed-erp-cy").value = cy; $("#ed-erp-g").value = g; $("#ed-erp-cy").dispatchEvent(new Event("input")); $("#ed-erp-title").scrollIntoView({ block: "start" }); } }, 60);
    }
    else if (c === "set") { const m = (arg.match(/keys\s*=\s*(vim|emacs|default)/) || [])[1]; if (m) { kySetMode(m); kyFlash(`Key mode: ${m}`); } else kyFlash("set keys=vim, set keys=emacs or set keys=default"); }
    else if (c === "math") toggleMath();
    else if (c === "help" || c === "h") { palReturn = document.activeElement; $("#keys").hidden = false; $("#keys-close").focus(); }
    else if (c === "q" || c === "quit") { ["#palette", "#keys"].forEach((id) => { if (!$(id).hidden) closeDialog($(id)); }); }
    else kyFlash(`Unknown command "${c}". Commands: ${KY_CMDS.join(", ")}`);
  }
  function kyCopyLink() {
    const url = `#${current}`;
    const done = () => kyFlash(`Copied the link to this desk: add ${url} to the page's address`);
    try { navigator.clipboard.writeText(url).then(done, () => kyFlash(`This desk's link ends in ${url}`)); } catch (e) { kyFlash(`This desk's link ends in ${url}`); }
  }
  function wireKeys() {
    const q = $("#ky-q");
    if (!q) return;
    q.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); const v = (KY.goMode ? "go " : "") + q.value; KY.goMode = false; kyClose(); kyRun(v); }
      else if (e.key === "Escape" || (e.ctrlKey && (e.key === "g" || e.key === "c"))) { e.preventDefault(); KY.goMode = false; kyClose(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); KY.hi = Math.min(KY.hist.length - 1, KY.hi + 1); if (KY.hi >= 0) q.value = KY.hist[KY.hi]; }
      else if (e.key === "ArrowDown") { e.preventDefault(); KY.hi = Math.max(-1, KY.hi - 1); q.value = KY.hi >= 0 ? KY.hist[KY.hi] : ""; }
      else if (e.key === "Tab") { e.preventDefault(); const m = KY_CMDS.find((c) => c.startsWith(q.value.trim().toLowerCase()) && c !== q.value.trim()); if (m) q.value = m + (["think", "whatif", "go", "triage", "erp"].includes(m) ? " " : ""); }
    });
    const seg = $("#ky-mode");
    if (seg) seg.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => kySetMode(b.dataset.m)));
    kySetMode(KY.mode);
    document.addEventListener("keydown", (e) => {
      const typing = e.target.closest && e.target.closest("input, textarea, select, [contenteditable]");
      if (typing || !$("#palette").hidden || !$("#keys").hidden || !$("#ky-bar").hidden) return;
      const stop = () => { e.preventDefault(); e.stopImmediatePropagation(); };
      if (e.key === ":" && !e.ctrlKey && !e.metaKey) { stop(); kyOpen(":"); return; }
      if (KY.mode === "vim" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const now = Date.now(), prev = now - KY.t < 800 ? KY.buf : "";
        KY.t = now;
        const k = e.key, seq = prev + k;
        const H = window.innerHeight;
        const act = { j: () => kyScroll(80), k: () => kyScroll(-80), d: () => kyScroll(H / 2), u: () => kyScroll(-H / 2), G: () => window.scrollTo({ top: document.body.scrollHeight }),
          gg: () => window.scrollTo({ top: 0 }), "]]": () => kySection(1), "[[": () => kySection(-1), gt: () => kyDesk(1), gT: () => kyDesk(-1), yy: kyCopyLink, n: () => kySection(1), N: () => kySection(-1) };
        if (act[seq]) { stop(); KY.buf = ""; act[seq](); return; }
        if (["g", "]", "[", "y"].includes(k)) { stop(); KY.buf = k; return; }
        KY.buf = "";
        if (act[k] && k !== "g") { stop(); act[k](); }
        return;
      }
      if (KY.mode === "emacs") {
        const H = window.innerHeight * 0.85;
        if (e.ctrlKey && !e.metaKey) {
          const pre = Date.now() - KY.t < 1200 && KY.buf === "C-x";
          KY.buf = ""; KY.t = Date.now();
          if (e.key === "x") { stop(); KY.buf = "C-x"; kyFlash("C-x-"); return; }
          const m = { n: () => kyScroll(60), p: () => kyScroll(-60), v: () => kyScroll(H), s: openPalette, g: () => { ["#palette", "#keys"].forEach((id) => { if (!$(id).hidden) closeDialog($(id)); }); kyFlash("Quit"); } };
          if (m[e.key]) { stop(); m[e.key](); }
          return;
        }
        if (Date.now() - KY.t < 1200 && KY.buf === "C-x") {
          KY.buf = "";
          if (e.key === "o") { stop(); kyDesk(1); return; }
          if (e.key === "b") { stop(); kyOpen("Switch to desk: "); KY.goMode = true; return; }
        }
        if (e.altKey && !e.ctrlKey && !e.metaKey) {
          const k = e.code === "KeyX" ? "x" : e.code === "KeyV" ? "v" : e.key;
          if (k === "x") { stop(); kyOpen("M-x "); return; }
          if (k === "v") { stop(); kyScroll(-H); return; }
          if (k === "<" || (e.code === "Comma" && e.shiftKey)) { stop(); window.scrollTo({ top: 0 }); return; }
          if (k === ">" || (e.code === "Period" && e.shiftKey)) { stop(); window.scrollTo({ top: document.body.scrollHeight }); return; }
        }
      }
    }, true);
  }
