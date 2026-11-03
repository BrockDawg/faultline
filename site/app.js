// faultline live page. Vanilla JS, no framework, no third-party URL.
// Reads data/index.json, data/racing.json and data/shift.json; data/clips/<id>.json on tap.
// Calls the worker API (api/...). Any worker failure falls back to the stored ruling.
// The CSP forbids inline style: every visual state is a class.
"use strict";

(function () {
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const SVGNS = "http://www.w3.org/2000/svg";
  const DATA = "data/";
  const API = "api/";
  const COPY = {};
  $$("#copy [data-copy]").forEach((n) => { COPY[n.dataset.copy] = n.textContent; });
  const t = (k) => (k in COPY ? COPY[k] : k);

  const S = {
    index: null, racing: null, racingMedia: null, shift: null,
    clips: {}, byId: {}, sel: null, protest: null, running: false,
  };

  // ---------------------------------------------------------------- helpers
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function sv(tag, attrs, cls) {
    const n = document.createElementNS(SVGNS, tag);
    for (const k in attrs || {}) n.setAttribute(k, attrs[k]);
    if (cls) n.setAttribute("class", cls);
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); return n; }
  function short(h) { return h ? String(h).slice(0, 8) + "…" : "·"; }
  function words(n) { return ({ 1: "one", 2: "two", 3: "three", 4: "four", 5: "five" })[n] || String(n); }
  async function getJSON(path) {
    const r = await fetch(path, { cache: "no-cache" });
    if (!r.ok) throw new Error(path + " " + r.status);
    return r.json();
  }
  function stamp(verdict, flat) {
    const s = el("span", "stamp v-" + verdict + (flat ? " flat" : ""), t("verdict." + verdict));
    return s;
  }
  function dots(stamps) {
    const d = el("span", "dots");
    d.setAttribute("aria-hidden", "true");
    Object.keys(stamps || {}).forEach((k) => d.appendChild(el("span", "dot v-" + stamps[k])));
    return d;
  }
  function modelBy(w) { return w.where === "Baseten" ? w.model + " on Baseten" : w.model + " (" + w.where + ")"; }
  function tick(ok, words) {
    const s = el("span", "tick" + (ok ? "" : " bad"));
    const g = sv("svg", { viewBox: "0 0 20 20", "aria-hidden": "true" });
    g.appendChild(sv("path", ok
      ? { d: "M4 10.5 L8.2 14.5 L16 6", fill: "none", stroke: "currentColor", "stroke-width": "2.4", "stroke-linecap": "round", "stroke-linejoin": "round" }
      : { d: "M5 5 L15 15 M15 5 L5 15", fill: "none", stroke: "currentColor", "stroke-width": "2.4", "stroke-linecap": "round" }));
    s.appendChild(g);
    s.appendChild(document.createTextNode(words != null ? words : t(ok ? "seal.match" : "seal.nomatch")));
    return s;
  }
  const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------------------------------------------------------------- numbers from the JSON
  function fillNumbers(attr, needsAttr, numbers) {
    $$("[" + attr + "]").forEach((n) => {
      const v = (numbers || {})[n.getAttribute(attr)];
      if (v && v.text != null) { n.textContent = v.text; if (v.readme_line) n.title = "README line " + v.readme_line; }
    });
    $$("[" + needsAttr + "]").forEach((n) => {
      const keys = n.getAttribute(needsAttr).split(/\s+/);
      if (keys.some((k) => !(numbers || {})[k])) n.hidden = true;
    });
    // the fallback wording shows only when the number it stands in for is absent
    const unless = needsAttr === "data-needs" ? "data-unless" : "data-unless-r";
    $$("[" + unless + "]").forEach((n) => {
      const keys = n.getAttribute(unless).split(/\s+/);
      n.hidden = keys.every((k) => (numbers || {})[k]);
    });
  }

  // A readable name from a clip id: "blind_corner_no_vest_07" -> "Blind corner, no vest".
  function humanise(id) {
    const w = String(id).split(/[_-]/).filter((x) => x && !/^\d+$/.test(x) && x !== "cctv");
    const out = w.map((x, i) => (i > 0 && x === "no" ? ", no" : (i ? " " : "") + x)).join("");
    return out ? out.charAt(0).toUpperCase() + out.slice(1) : String(id);
  }
  // The raw id, breakable only after an underscore.
  function idNode(id, cls) {
    const s = el("span", cls);
    String(id).split("_").forEach((part, i, all) => {
      s.appendChild(document.createTextNode(part + (i < all.length - 1 ? "_" : "")));
      if (i < all.length - 1) s.appendChild(document.createElement("wbr"));
    });
    return s;
  }

  // ---------------------------------------------------------------- forklift picker
  function posterSpan(src) {
    const p = el("span", "poster");
    if (src) {
      const img = el("img");
      img.alt = "";
      img.decoding = "async";
      img.addEventListener("error", () => p.classList.add("missing"));
      img.src = DATA + src;
      p.appendChild(img);
    } else p.classList.add("missing");
    return p;
  }
  function clipTile(c) {
    const b = el("button", "tile");
    b.type = "button";
    b.dataset.clip = c.id;
    b.setAttribute("aria-pressed", "false");
    const p = posterSpan(c.poster);
    p.appendChild(dots(c.stamps));
    b.appendChild(p);
    b.appendChild(el("span", "tile-title", c.title || clipTitle(c.id)));
    b.appendChild(idNode(c.id, "tile-name"));
    b.appendChild(el("span", "tile-hint h-" + c.hint, t("hint." + c.hint)));
    b.addEventListener("click", () => select({ kind: "clip", id: c.id }, true));
    return b;
  }
  function clipRow(c) {
    const li = el("li");
    const b = el("button", "row");
    b.type = "button";
    b.dataset.clip = c.id;
    b.setAttribute("aria-pressed", "false");
    b.appendChild(idNode(c.id, "mono"));
    b.appendChild(dots(c.stamps));
    b.addEventListener("click", () => select({ kind: "clip", id: c.id }, true));
    li.appendChild(b);
    return li;
  }
  function drawer(btn, box) {
    btn.addEventListener("click", () => {
      const open = btn.getAttribute("aria-expanded") !== "true";
      $$(".more-btn").forEach((x) => x.setAttribute("aria-expanded", "false"));
      $$(".drawer").forEach((x) => { x.hidden = true; });
      btn.setAttribute("aria-expanded", String(open));
      box.hidden = !open;
    });
  }

  // Picking a case opens its case file at once; the button then checks nobody changed it.
  function select(sel, scroll) {
    if (S.running) return;
    S.sel = sel;
    $$("[aria-pressed][data-clip]").forEach((n) => n.setAttribute("aria-pressed", String(sel.kind === "clip" && n.dataset.clip === sel.id)));
    $("#pick-protest").setAttribute("aria-pressed", String(sel.kind === "protest"));
    $("#pick-limits").setAttribute("aria-pressed", String(sel.kind === "limits"));
    barFor(sel);
    openCase(sel, scroll);
  }
  function barFor(sel) {
    const go = $("#go");
    go.disabled = false;
    const what = $("#go-what");
    if (sel.kind === "clip") { $("#sel-name").textContent = clipTitle(sel.id); go.textContent = t("go.clip"); what.textContent = t("what.clip"); }
    if (sel.kind === "protest") {
      const p = protestById(sel.id);
      $("#sel-name").textContent = t("sel.protest") + " · " + (p ? p.label : sel.id);
      go.textContent = t("go.protest");
      what.textContent = t("what.protest");
    }
    if (sel.kind === "limits") {
      $("#sel-name").textContent = t("sel.limits");
      go.textContent = limitsWord();
      what.textContent = t("what." + limitsMode());
    }
  }

  // ---------------------------------------------------------------- the case file
  // Each case opens as an incident: what happened, the rulings, who acts on them.
  // Featured clips use sentences from the film script; every other clip's sentences are
  // built from its own record's rulings, never from a model's words.
  function clipTitle(id) { const k = "case.title." + id; return k in COPY ? COPY[k] : humanise(id); }
  function listWords(xs) { return xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " " + t("and") + " " + xs[xs.length - 1]; }
  function uniq(xs) { return xs.filter((x, i) => x && xs.indexOf(x) === i); }
  function cap(x) { return x ? x.charAt(0).toUpperCase() + x.slice(1) : x; }
  // The fact an unable ruling needed. Shown bare it reads as the opposite of the truth
  // ("a camera held still…"), so it is only ever shown behind the "It needs:" label.
  function lacksOf(r) { const lk = typeof r.lacks === "object" && r.lacks ? r.lacks.words : r.lacks; return lk || r.missing_fact || ""; }
  // A fact whose words name what was missing, not what was needed, carries its own needs line.
  function needsLine(r) {
    const own = "needs." + (r.missing_fact || "");
    if (own in COPY) return COPY[own];
    const lk = lacksOf(r);
    return lk ? t("needs") + " " + lk.replace(/\.$/, "") + "." : "";
  }
  // Why it could not rule, from the record: the first sentence of the ruling's measurement.
  // A sentence ends at a full stop after a letter, so "0.89 m" is never cut.
  function whySentence(r) {
    const m = String(r.measurement || "").trim();
    if (!m) return "";
    const end = m.search(/[^\d\s]\.(\s|$)/);
    let s = end >= 0 ? m.slice(0, end + 2) : m;
    const semi = s.indexOf(";");
    if (s.length > 180 && semi > 0) s = s.slice(0, semi) + ".";
    return s;
  }
  // The same reason as a short clause, for lines that join several rulings.
  function whyShort(r) {
    const s = whySentence(r);
    const cut = s.search(/[;:]|[^\d\s]\.(\s|$)/);
    let x = cut < 0 ? s : s.slice(0, s[cut] === ";" || s[cut] === ":" ? cut : cut + 1);
    x = x.replace(/\.$/, "").trim();
    // a long clause keeps its opening words, cut before a bracket or a comma
    if (x.length > 90) { const c = x.slice(0, 90).search(/ \(|, (?=[^,]*$)/); x = c > 30 ? x.slice(0, c) : x.slice(0, x.lastIndexOf(" ", 88)) + "…"; }
    return x ? x.charAt(0).toLowerCase() + x.slice(1) : needsLine(r).replace(/\.$/, "");
  }
  // The needs line repeats nothing: skipped when the reason already says it.
  function needsAdds(r) { const lk = lacksOf(r).toLowerCase().replace(/\.$/, ""); return !!lk && !whySentence(r).toLowerCase().startsWith(lk); }
  function byVerdict(rs, v) { return (rs || []).filter((r) => r.verdict === v); }
  function clipStory(clip) {
    const own = "case.story." + clip.id;
    if (own in COPY) return [COPY[own]];
    const rs = clip.rulings || [];
    const br = byVerdict(rs, "breach"), un = byVerdict(rs, "unable_to_rule");
    const out = [];
    if ((S.byId[clip.id] || {}).group === "real") out.push(t("case.real"));
    if (br.length) out.push(t("story.breach") + " " + listWords(br.map((r) => "“" + (r.title || r.rule) + "”")) + ".");
    else out.push(t(un.length ? "story.nobreach" : "story.allclear"));
    if (un.length) out.push(t("story.unable") + " " + words(un.length) + " " + t(un.length === 1 ? "story.rule" : "story.rules") + ": " + uniq(un.map(whyShort)).join("; ") + ".");
    return out;
  }
  function clipFor(rs) {
    const br = byVerdict(rs, "breach"), un = byVerdict(rs, "unable_to_rule");
    const lines = [];
    lines.push([t("for.lead"), br.length
      ? cap(words(br.length)) + " " + t(br.length === 1 ? "for.item" : "for.items") + " " + listWords(br.map((r) => r.title || r.rule)) + "."
      : t("for.lead.none")]);
    lines.push([t("for.insurer"), t(br.length ? "for.insurer.breach" : "for.insurer.none")]);
    if (un.length) lines.push([t("for.person"), t("for.unable") + " " + words(un.length) + " " + t(un.length === 1 ? "story.rule" : "story.rules") + ": " + uniq(un.map(whyShort)).join("; ") + ". " + t(un.length === 1 ? "for.person.b" : "for.person.bs")]);
    return lines;
  }
  function protestStory(p) {
    const w = p.window || {};
    if (w.lap == null) return t("story.protest.nolap");
    return t("story.protest") + " " + w.lap + (w.label ? ", " + t("story.in") + " " + w.label : "") + ".";
  }
  function renderCase(c) {
    $("#run").hidden = false;
    $("#run-kicker").textContent = c.kicker;
    $("#run-h").textContent = c.title;
    const st = clear($("#story"));
    (c.story || []).forEach((x) => st.appendChild(el("p", null, x)));
    const fl = clear($("#for"));
    (c.forLines || []).forEach((pair) => {
      const d = el("div");
      d.appendChild(el("dt", null, pair[0]));
      d.appendChild(el("dd", null, pair[1]));
      fl.appendChild(d);
    });
    fl.hidden = !(c.forLines || []).length;
    $("#why-text").textContent = t("why." + c.why);
    $("#prog-run").hidden = true;
    $("#busy").hidden = true;
    $("#seal").hidden = true;
    clear($("#out"));
  }
  function clipCase(clip) {
    const real = (S.byId[clip.id] || {}).group === "real";
    return { kicker: t(real ? "kicker.real" : "kicker.clip"), title: clipTitle(clip.id), story: clipStory(clip), forLines: clipFor(clip.rulings), why: "clip" };
  }
  function protestCase(p) {
    return { kicker: t("kicker.protest"), title: p.label, story: [protestStory(p)], forLines: [[t("for.steward"), t("for.steward.what")]], why: "racing" };
  }
  function showLimitsCase() {
    renderCase({ kicker: t("kicker.limits"), title: t("sel.limits"), story: [t("story.limits")], forLines: [[t("for.stewards"), t("for.stewards.what")]], why: "limits" });
    const copy = $("#limits-table").closest(".table-scroll").cloneNode(true);
    copy.querySelector("table").removeAttribute("id");
    $$("td.col-live", copy).forEach((td) => { td.className = "col-live mono"; td.textContent = ""; });
    $("#out").appendChild(copy);
    return copy;
  }
  let openTok = 0;
  async function openCase(sel, scroll) {
    const tok = ++openTok;
    if (sel.kind === "clip") {
      let clip;
      try { clip = await loadClip(sel.id); } catch (e) {
        renderCase({ kicker: t("kicker.clip"), title: clipTitle(sel.id), story: [t("load.fail")], why: "clip" });
        return;
      }
      if (tok !== openTok) return;
      renderCase(clipCase(clip));
      renderRulings(clip);
    } else if (sel.kind === "protest") {
      const p = protestById(sel.id);
      if (!p) return;
      renderCase(protestCase(p));
      $("#out").appendChild(evidencePack(p, false));
    } else if (sel.kind === "limits") showLimitsCase();
    if (scroll) {
      const r = $("#run").getBoundingClientRect();
      if (r.top < 0 || r.top > window.innerHeight * 0.55) $("#run").scrollIntoView({ behavior: still() ? "auto" : "smooth", block: "start" });
    }
  }

  // ---------------------------------------------------------------- the progress panel
  // A worker `stage` event names a step the code has just passed (start: the process is up,
  // record: the entry is read, rebuild: the judge returned, seal: the hash compared), so the
  // step after it is the one now running. Queue position 0 means the job holds a slot.
  // The clock counts real time since the press; nothing here advances on a timer.
  const STAGES = ["queued", "start", "record", "rebuild", "seal"];
  function progress(id, kind) {
    const box = clear($("#" + id));
    box.classList.remove("off", "done");
    box.hidden = false;
    const head = el("div", "prog-head");
    const hk = "prog.head." + kind;
    const title = hk in COPY ? COPY[hk] : t("prog.head");
    head.appendChild(el("p", "prog-title", title));
    const clock = el("p", "prog-clock");
    const lbl = el("span", null, t("prog.running"));
    const secs = el("span", "prog-secs", "0.0");
    clock.appendChild(lbl);
    clock.appendChild(document.createTextNode(" "));
    clock.appendChild(secs);
    clock.appendChild(document.createTextNode(" " + t("prog.unit")));
    head.appendChild(clock);
    box.appendChild(head);
    const ol = el("ol", "stages");
    ol.setAttribute("aria-label", title);
    const pos = el("span", "stage-pos");
    const items = STAGES.map((name) => {
      const li = el("li");
      li.appendChild(el("span", "pip"));
      const body = el("div", "stage-body");
      const nm = el("p", "stage-name", t("st." + name));
      if (name === "queued") { nm.appendChild(document.createTextNode(" ")); nm.appendChild(pos); }
      body.appendChild(nm);
      const own = "st." + name + ".what." + kind;
      body.appendChild(el("p", "stage-what", own in COPY ? COPY[own] : t("st." + name + ".what")));
      li.appendChild(body);
      ol.appendChild(li);
      return li;
    });
    box.appendChild(ol);
    const say = el("p", "sr");
    say.setAttribute("role", "status");
    box.appendChild(say);
    const t0 = performance.now();
    const show = () => { secs.textContent = ((performance.now() - t0) / 1000).toFixed(1); };
    const iv = setInterval(show, 100);
    let cur = -1, over = false;
    function at(i) {
      if (over || i <= cur) return;
      cur = i;
      items.forEach((li, j) => {
        li.classList.toggle("done", j < i);
        li.classList.toggle("on", j === i);
        if (j === i) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
      });
      if (i > 0) pos.textContent = "";
      if (i < STAGES.length) say.textContent = t("st." + STAGES[i]);
    }
    at(0);
    return {
      queued(p) {
        if (p > 0) { at(0); pos.textContent = "#" + p + " " + t("st.inline"); }
        else { pos.textContent = ""; at(1); }
      },
      stage(name) { const i = STAGES.indexOf(name); if (i >= 0) at(i + 1); },
      finish(ok) {
        if (over) return;
        if (ok) at(STAGES.length);
        over = true;
        clearInterval(iv);
        show();
        lbl.textContent = t(ok ? "prog.done" : "prog.stopped");
        items.forEach((li) => { li.classList.remove("on"); li.removeAttribute("aria-current"); });
        box.classList.add(ok ? "done" : "off");
        say.textContent = lbl.textContent + " " + secs.textContent + " " + t("prog.unit");
      },
    };
  }
  // Scroll only when the panel is off screen, so the button and the panel stay in view.
  function bringIntoView(node, anchor) {
    const r = node.getBoundingClientRect();
    const bar = $("#actionbar").getBoundingClientRect();
    const floor = Math.min(window.innerHeight, bar.top > 0 ? bar.top : window.innerHeight);
    if (r.top < 0 || r.top > floor - 140) (anchor || node).scrollIntoView({ behavior: still() ? "auto" : "smooth", block: "start" });
  }
  // One quiet status line on a card: checking, unchanged, changed, or not checked this time.
  function cardState(c, state, words) {
    let st = c.querySelector(".cardstate");
    if (!st) { st = el("p", "cardstate"); c.insertBefore(st, c.children[1] || null); }
    clear(st);
    c.classList.remove("wait", "same", "differs", "stored");
    c.classList.add(state);
    if (state === "wait") { st.appendChild(el("span", "cs-pip")); st.appendChild(el("span", null, words)); }
    else if (state === "same" || state === "differs") st.appendChild(tick(state === "same", words));
    else st.appendChild(el("span", null, words));
  }
  // The check runs below the case file: bring the dispute line and the panel into view.
  function showCheck() {
    const why = $("#why");
    const r = why.getBoundingClientRect();
    const bar = $("#actionbar").getBoundingClientRect();
    const floor = bar.top > 0 && bar.top < window.innerHeight ? bar.top : window.innerHeight;
    if (r.top < 0 || r.top > floor - 220) why.scrollIntoView({ behavior: still() ? "auto" : "smooth", block: "start" });
    $("#run").focus({ preventScroll: true });
  }
  function setRunning(on) {
    S.running = on;
    const go = $("#go");
    go.disabled = on;
    if (on) go.textContent = t("go.busy");
    else if (S.sel) barFor(S.sel);
  }

  // ---------------------------------------------------------------- worker calls
  // h: {queued(pos), stage(name), line(d), result(d), fallback()}
  async function job(path, body, h, limitMs) {
    let done = false;
    const finish = (fn, arg) => { if (done) return; done = true; clearTimeout(timer); if (es) es.close(); fn(arg); };
    let es = null;
    const timer = setTimeout(() => finish(h.fallback), limitMs || 150000);
    let r;
    try {
      r = await fetch(API + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
    } catch (e) { finish(h.fallback); return; }
    if (!r.ok) { finish(h.fallback); return; }
    let j;
    try { j = await r.json(); } catch (e) { finish(h.fallback); return; }
    if (!j || !j.job) { finish(h.fallback); return; }
    if (h.queued) h.queued(j.position);
    try { es = new EventSource(API + "jobs/" + encodeURIComponent(j.job)); } catch (e) { finish(h.fallback); return; }
    const on = (name, fn) => es.addEventListener(name, (ev) => {
      let d = {};
      try { d = JSON.parse(ev.data || "{}"); } catch (e) { d = {}; }
      fn(d);
    });
    on("queued", (d) => h.queued && h.queued(d.position));
    on("stage", (d) => h.stage && h.stage(d.name));
    on("line", (d) => h.line && h.line(d));
    on("result", (d) => finish(h.result, d));
    on("error", (d) => finish(h.fallback, d));
    es.onerror = () => finish(h.fallback);
  }
  function showBusy(words) { $("#busy").textContent = words; $("#busy").hidden = false; }

  // ---------------------------------------------------------------- forklift: one clip
  async function loadClip(id) {
    if (!S.clips[id]) S.clips[id] = await getJSON(DATA + "clips/" + encodeURIComponent(id) + ".json");
    return S.clips[id];
  }
  async function ruleClip(id) {
    setRunning(true);
    let clip;
    try { clip = await loadClip(id); } catch (e) {
      showBusy(t("load.fail")); setRunning(false); return;
    }
    // the case file's stored rulings show at once, each marked as being checked
    renderCase(clipCase(clip));
    renderRulings(clip);
    $$("#out .rcard").forEach((c) => cardState(c, "wait", t("card.wait")));
    const pg = progress("prog-run", "clip");
    showCheck();
    job("rule", { id: id }, {
      queued: pg.queued,
      stage: pg.stage,
      result: (d) => {
        pg.finish(true);
        sealLive(clip.record, d, "clip");
        const live = {};
        (d.rulings || []).forEach((r) => { live[r.rule] = r.verdict; });
        flipCards(live, d.match === true);
        setRunning(false);
      },
      fallback: () => {
        pg.finish(false);
        showBusy(t("busy.clip"));
        sealStored(clip.record);
        $$("#out .rcard").forEach((c) => cardState(c, "stored", t("card.stored")));
        setRunning(false);
      },
    }, 120000);
  }
  // The result says what it means first; the record hashes sit in one small detail line.
  function sealHead(s, ok, kind, d) {
    const n = kind === "rerule" || kind === "checked" ? "all" : "one";
    const h = el("p", "seal-head");
    h.appendChild(tick(ok, t(ok ? "seal.same." + n : "seal.diff." + n)));
    s.appendChild(h);
    s.appendChild(el("p", "seal-sub", ok ? t("seal.how." + kind) : (d.why || t("nomatch.why"))));
  }
  // "record c82ca137… published · c82ca137… rebuilt · 18.0 s on our server"
  function sealDetail(s, shipped, rebuilt, seconds, prefix, ok) {
    const line = el("p", "seal-detail");
    if (prefix) line.appendChild(document.createTextNode(prefix + " · "));
    line.appendChild(document.createTextNode(t("seal.record") + " "));
    line.appendChild(hashCode(shipped));
    line.appendChild(document.createTextNode(" " + t("seal.pub") + " · "));
    if (rebuilt) {
      line.appendChild(hashCode(rebuilt));
      line.appendChild(document.createTextNode(" " + t("seal.reb")));
    } else line.appendChild(document.createTextNode(t("seal.notrun")));
    if (typeof seconds === "number") line.appendChild(document.createTextNode(" · " + seconds.toFixed(1) + " " + t("seal.secs")));
    if (ok != null) { line.appendChild(document.createTextNode(" ")); line.appendChild(tick(ok, "")); }
    s.appendChild(line);
  }
  function sealLive(shipped, d, kind) {
    const s = clear($("#seal"));
    const ok = d.match === true;
    s.className = "seal press" + (ok ? "" : " bad");
    sealHead(s, ok, kind, d);
    if (shipped) sealDetail(s, shipped, typeof d.record_rebuilt === "string" ? d.record_rebuilt : null, d.seconds);
    else if (typeof d.seconds === "number") s.appendChild(el("p", "seal-detail", d.seconds.toFixed(1) + " " + t("seal.secs")));
    s.hidden = false;
  }
  function sealStored(shipped) {
    const s = clear($("#seal"));
    s.className = "seal stored";
    sealDetail(s, shipped, null);
    s.hidden = false;
  }
  function hashCode(h) {
    const c = el("code", "hash", short(h));
    if (h) c.title = h;
    return c;
  }

  function renderRulings(clip) {
    const out = clear($("#out"));
    (clip.rulings || []).forEach((r) => out.appendChild(ruleCard(r)));
  }
  // The rebuilt rulings land at once; each card flips in turn so the eye can follow.
  function flipCards(live, ok) {
    const gap = still() ? 0 : 120;
    $$("#out .rcard").forEach((c, i) => {
      const go = () => {
        const has = Object.prototype.hasOwnProperty.call(live, c.dataset.rule);
        const same = has && live[c.dataset.rule] === c.dataset.verdict;
        if (same && ok) cardState(c, "same", t("live.same"));
        else cardState(c, "differs", t(!has ? "live.missing" : same ? "live.samev" : "live.diff"));
      };
      if (gap) setTimeout(go, i * gap); else go();
    });
  }
  function ruleCard(r) {
    const c = el("article", "rcard");
    c.dataset.rule = r.rule;
    c.dataset.verdict = r.verdict;
    const head = el("div", "rcard-head");
    head.appendChild(el("h3", null, r.title || r.rule));
    head.appendChild(stamp(r.verdict));
    c.appendChild(head);
    c.appendChild(framesBlock(r));
    if (r.verdict === "breach" && r.decided_by) {
      c.appendChild(el("p", "label", t("decided")));
      c.appendChild(el("p", "decided", r.decided_by));
    }
    if (r.verdict === "unable_to_rule") {
      const pw = r.pack_words || (typeof r.lacks === "object" && r.lacks ? r.lacks.pack : null);
      c.appendChild(el("p", "label", t("why.unable")));
      c.appendChild(el("p", "why-line", whySentence(r) || needsLine(r)));
      if (whySentence(r) && needsAdds(r)) c.appendChild(el("p", "needs", needsLine(r)));
      if (pw) c.appendChild(el("p", "packwords", t("pack") + ": “" + pw + "”"));
    }
    // an unable card already led with the measurement's first sentence; the rest follows
    const meas = r.verdict === "unable_to_rule" ? String(r.measurement || "").trim().slice(whySentence(r).length).trim() : r.measurement || "";
    if (meas || r.verdict !== "unable_to_rule") {
      c.appendChild(el("p", "label", t("measurement")));
      c.appendChild(el("p", "evidence", meas));
    }
    const w = r.words;
    if (w && (w.note || w.reads)) {
      const box = el("div", "words");
      box.appendChild(el("p", "words-head", t("beside")));
      if (w.note && w.note.text) {
        box.appendChild(el("p", "byline", modelBy(w.note) + " " + t("wrote")));
        box.appendChild(el("blockquote", "note", w.note.text));
      }
      if (w.reads) box.appendChild(readLine(w.reads, "forklift", w.reads.agreed));
      c.appendChild(box);
    }
    return c;
  }
  function readLine(rd, kind, agreed) {
    const p = el("p", "readline");
    const lbl = modelBy(rd) + ", " + (rd.runs === 3 ? t("reads." + kind) : words(rd.runs) + " " + t("reads." + kind).split(" ").slice(1).join(" "));
    p.appendChild(el("b", null, lbl + " "));
    if (rd.no_text) p.appendChild(document.createTextNode(t("reads.notext")));
    else if (agreed) {
      p.appendChild(document.createTextNode(t("reads.agreed") + " "));
      p.appendChild(el("span", "v-" + agreed, t("verdict." + agreed) !== "verdict." + agreed ? t("verdict." + agreed) : agreed));
    } else p.appendChild(document.createTextNode(t("reads.none")));
    return p;
  }
  function framesBlock(r) {
    const wrap = el("div");
    const fr = (r.frames || []).slice(0, 3);
    if (!fr.length) { wrap.appendChild(el("p", "noframe", t("frames.none"))); return wrap; }
    wrap.appendChild(el("p", "frames-cap", t("frames." + (r.frames_source || "ruling"))));
    const g = el("div", "frames");
    fr.forEach((f) => {
      const fig = el("figure");
      const b = el("button", "frame-btn");
      b.type = "button";
      const cap = t("frame") + " " + f.n + " · " + Number(f.t_s).toFixed(2) + " s";
      b.setAttribute("aria-label", cap);
      if (f.src) {
        const img = el("img");
        img.loading = "lazy";
        img.decoding = "async";
        img.alt = cap;
        img.addEventListener("error", () => { b.classList.add("missing"); b.setAttribute("aria-label", cap + " · " + t("frames.missing")); });
        img.src = DATA + f.src;
        b.appendChild(img);
        b.addEventListener("click", () => { if (!b.classList.contains("missing")) enlarge(DATA + f.src, cap); });
      } else b.classList.add("missing");
      fig.appendChild(b);
      fig.appendChild(el("figcaption", null, cap));
      g.appendChild(fig);
    });
    wrap.appendChild(g);
    return wrap;
  }
  function enlarge(src, cap) {
    const d = $("#lightbox");
    $("#lightbox-img").src = src;
    $("#lightbox-img").alt = cap;
    $("#lightbox-cap").textContent = cap;
    if (d.showModal) d.showModal();
  }

  // ---------------------------------------------------------------- racing
  function protestById(id) { return ((S.racing || {}).protests || []).find((p) => p.id === id); }
  function limitsMode() { return ((S.racing || {}).limits_mode === "rerule") ? "rerule" : "checked"; }
  function limitsWord() { return t("go." + limitsMode()); }

  function protestTimeline(p) {
    // The window on a strip: the feed seconds it spans, the steward's moment, one dot per car in the closed set.
    const W = 240, H = 68;
    const g = sv("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": (p.window || {}).label || p.label });
    const fs = (p.window || {}).feed_s || [];
    const a = Number(fs[0]), b = Number(fs[1]);
    const pad = 16, y = 30;
    g.appendChild(sv("line", { x1: pad, y1: y, x2: W - pad, y2: y, "stroke-width": "2" }, "tl-axis"));
    if (isFinite(a) && isFinite(b) && b > a) {
      const span = b - a, lo = a - span * 0.6, hi = b + span * 0.6;
      const x = (v) => pad + ((v - lo) / (hi - lo)) * (W - 2 * pad);
      g.appendChild(sv("rect", { x: x(a), y: y - 9, width: Math.max(2, x(b) - x(a)), height: 18, rx: 3 }, "tl-win"));
      const m = (p.window || {}).moment_feed_s;
      if (m != null && isFinite(Number(m))) g.appendChild(sv("line", { x1: x(Number(m)), y1: y - 15, x2: x(Number(m)), y2: y + 15, "stroke-width": "2.5" }, "tl-moment"));
    }
    const cars = p.candidates || [];
    cars.forEach((c, i) => {
      const cx = W / 2 + (i - (cars.length - 1) / 2) * 22;
      g.appendChild(sv("circle", { cx: cx, cy: 56, r: 5 }, "tl-car"));
    });
    return g;
  }
  function limitsBars(rows) {
    const cars = rows.filter((r) => Number.isInteger(r.incidents) && Number.isInteger(r.limit));
    if (cars.length) return carBars(cars);
    // No counts in the bundle: one bar per session, how many cars the feed put over the limit.
    const by = [];
    const idx = {};
    rows.forEach((r) => {
      if (!(r.label in idx)) { idx[r.label] = by.length; by.push({ label: r.label, n: 0 }); }
      if (r.verdict === "breach") by[idx[r.label]].n += 1;
    });
    const W = 240, H = 68, pad = 10;
    const g = sv("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": t("sel.limits") });
    const max = Math.max(1, ...by.map((s) => s.n));
    const bw = by.length ? (W - 2 * pad) / by.length : 0;
    g.appendChild(sv("line", { x1: pad, y1: H - 8, x2: W - pad, y2: H - 8, "stroke-width": "1.5" }, "tl-axis"));
    by.forEach((s, i) => {
      const h = s.n ? 6 + (s.n / max) * (H - 26) : 2;
      g.appendChild(sv("rect", { x: pad + i * bw + bw * 0.18, y: H - 8 - h, width: Math.max(2, bw * 0.64), height: h, rx: 2 }, s.n ? "bar-over" : "bar-none"));
    });
    return g;
  }
  function carBars(rows) {
    // One bar per car: its incidents against its session's limit, the limit drawn as a line.
    const W = 240, H = 68, pad = 10, base = H - 8, top = 8;
    const g = sv("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": t("sel.limits") });
    const max = Math.max(1, ...rows.map((r) => Math.max(r.incidents, r.limit)));
    const y = (v) => base - (v / max) * (base - top);
    const bw = (W - 2 * pad) / rows.length;
    g.appendChild(sv("line", { x1: pad, y1: base, x2: W - pad, y2: base, "stroke-width": "1.5" }, "tl-axis"));
    rows.forEach((r, i) => {
      const x = pad + i * bw;
      const over = r.incidents >= r.limit;
      g.appendChild(sv("rect", { x: x + bw * 0.2, y: y(r.incidents), width: Math.max(1.5, bw * 0.6), height: Math.max(1, base - y(r.incidents)), rx: 1 }, over ? "bar-over" : "bar-under"));
      g.appendChild(sv("line", { x1: x, y1: y(r.limit), x2: x + bw, y2: y(r.limit), "stroke-width": "1.5" }, "bar-limit"));
    });
    return g;
  }

  function evidencePack(p, withStory) {
    const box = el("article", "evpack");
    box.appendChild(el("h4", null, p.label + " · " + t("r.rule") + " " + (p.rule || "")));
    if (withStory !== false) box.appendChild(el("p", "pack-story", protestStory(p)));
    if (p.clause) box.appendChild(el("p", "clause", p.clause));
    const media = (S.racingMedia || {}).protests && (S.racingMedia.protests[String(p.id)] || null);
    if (media && media.video) {
      const fig = el("figure", "race-media");
      const v = el("video");
      v.controls = true;
      v.muted = true;
      v.playsInline = true;
      v.preload = "metadata";
      v.setAttribute("playsinline", "");
      v.setAttribute("muted", "");
      v.setAttribute("aria-label", "Race footage for " + p.label);
      if (media.poster) v.poster = DATA + media.poster;
      v.src = DATA + media.video;
      fig.appendChild(v);
      fig.appendChild(el("figcaption", null, "Real race footage, reconstructed from the stored review frames. Silent by design. The steward's ruling is shown below; model reads never decide it."));
      box.appendChild(fig);
    }
    box.appendChild(protestTimeline(p));
    const w = p.window || {};
    box.appendChild(el("p", "label", t("r.window")));
    const fs = w.feed_s || [];
    box.appendChild(el("p", "evidence", [w.label, w.lap != null ? t("r.lap") + " " + w.lap : null, fs.length === 2 ? t("r.feed") + " " + fs[0] + "-" + fs[1] : null].filter(Boolean).join(" · ")));
    box.appendChild(el("p", "label", t("r.set")));
    const ul = el("ul", "cars");
    (p.candidates || []).forEach((c) => ul.appendChild(el("li", null, c)));
    box.appendChild(ul);
    if ((p.facts || []).length) {
      box.appendChild(el("p", "label", t("r.facts")));
      const f = el("ul");
      p.facts.forEach((x) => f.appendChild(el("li", null, x)));
      box.appendChild(f);
    }
    if (p.evidence) { box.appendChild(el("p", "label", t("measurement"))); box.appendChild(el("p", "evidence", p.evidence)); }
    box.appendChild(el("p", "label", t("r.steward")));
    box.appendChild(el("p", "decided", p.steward_ruling || ""));
    const arms = el("div", "words");
    arms.appendChild(el("p", "words-head", t("beside")));
    (p.reads || []).forEach((rd) => {
      const line = readLine(rd, "racing", null);
      if (!rd.no_text) {
        clear(line);
        line.appendChild(el("b", null, modelBy(rd) + ", " + (rd.runs === 3 ? t("reads.racing") : words(rd.runs) + " " + t("reads.racing").split(" ").slice(1).join(" ")) + " "));
        line.appendChild(document.createTextNode(rd.agreed && rd.offender ? t("reads.agreed") + " " + rd.offender : t("reads.none")));
      }
      arms.appendChild(line);
    });
    box.appendChild(arms);
    if (p.frames_checked != null) box.appendChild(el("p", "fine", p.frames_checked + " " + t("r.frames")));
    if (p.honesty && (p.honesty.lines || []).length) {
      const h = el("div", "honesty");
      p.honesty.lines.forEach((x) => h.appendChild(el("p", null, x)));
      box.appendChild(h);
    }
    return box;
  }
  function showProtest(id) {
    S.protest = id;
    $$("#protest-chips .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.id === id)));
    const p = protestById(id);
    clear($("#protest-pack"));
    clear($("#protest-result"));
    if (!S.running) $("#prog-protest").hidden = true;
    if (p) $("#protest-pack").appendChild(evidencePack(p));
  }
  function protestSeal(target, p, d, live) {
    const ok = d.match === true;
    const s = el("div", "seal" + (live ? " press" + (ok ? "" : " bad") : " stored"));
    if (live) sealHead(s, ok, "protest", d);
    const rec = p.record || {};
    ["arm1", "arm2"].forEach((arm, i) => {
      const ln = (d.lines || []).find((x) => x.arm === i + 1);
      const rb = live ? (d.record_rebuilt || {})[arm] : null;
      sealDetail(s, rec[arm], rb, null, t("r.arm") + " " + (i + 1), live ? (ln ? ln.match === true : ok) : null);
    });
    if (live && typeof d.seconds === "number") s.appendChild(el("p", "seal-detail", d.seconds.toFixed(1) + " " + t("seal.secs")));
    target.appendChild(s);
  }
  function checkProtest(id, where) {
    const p = protestById(id);
    if (!p) return;
    const inRun = where === "run";
    let pack;
    if (inRun) {
      renderCase(protestCase(p));
      pack = evidencePack(p, false);
      $("#out").appendChild(pack);
    } else {
      clear($("#protest-result"));
      pack = $("#protest-pack .evpack");
    }
    const pg = progress(inRun ? "prog-run" : "prog-protest", "protest");
    if (inRun) showCheck();
    else bringIntoView($("#prog-protest"), $("#check-protest").closest(".race-action"));
    if (pack) cardState(pack, "wait", t("pack.wait"));
    setRunning(true);
    const btn = $("#check-protest");
    btn.disabled = true;
    const place = (box) => {
      if (inRun) { const s = clear($("#seal")); s.className = "seal-wrap"; s.appendChild(box.firstChild); s.hidden = false; }
      else $("#protest-result").appendChild(box);
    };
    job("racing/protest", { id: id }, {
      queued: pg.queued,
      stage: pg.stage,
      result: (d) => {
        pg.finish(true);
        if (pack) cardState(pack, d.match === true ? "same" : "differs", t(d.match === true ? "pack.same" : "pack.diff"));
        const box = el("div");
        protestSeal(box, p, d, true);
        place(box);
        btn.disabled = false; setRunning(false);
      },
      fallback: () => {
        pg.finish(false);
        if (pack) cardState(pack, "stored", t("pack.stored"));
        if (inRun) showBusy(t("busy.racing"));
        else $("#protest-result").appendChild(el("p", "busy", t("busy.racing")));
        const box = el("div");
        protestSeal(box, p, {}, false);
        place(box);
        btn.disabled = false; setRunning(false);
      },
    }, 120000);
  }

  function limitsTable() {
    const tb = clear($("#limits-table tbody"));
    ((S.racing || {}).limits || []).forEach((r) => {
      const tr = el("tr");
      tr.dataset.label = r.label;
      tr.appendChild(el("th", "mono", r.label)).setAttribute("scope", "row");
      tr.appendChild(el("td", "mono", r.offender || t("r.na")));
      const v = el("td");
      v.appendChild(stamp(r.verdict, true));
      tr.appendChild(v);
      tr.appendChild(el("td", null, r.ruling_on_record == null ? t("r.na") : t(r.ruling_on_record ? "r.yes" : "r.no")));
      tr.appendChild(el("td", "col-live mono", ""));
      tb.appendChild(tr);
    });
  }
  function checkLimits(where) {
    const inRun = where === "run";
    const mode = limitsMode();
    const tableClone = inRun ? showLimitsCase() : null;
    const summary = inRun ? $("#out") : null;
    const pg = progress(inRun ? "prog-run" : "prog-limits", mode);
    if (inRun) showCheck();
    else bringIntoView($("#prog-limits"), $("#check-limits").closest(".race-action"));
    setRunning(true);
    const btn = $("#check-limits");
    btn.disabled = true;
    const roots = () => [document.getElementById("limits-table")].concat(tableClone ? [tableClone] : []);
    // every stored row shows at once, its check column waiting for the server's line
    roots().forEach((root) => $$("td.col-live", root).forEach((td) => { td.textContent = t("live.wait"); td.className = "col-live mono live-wait"; }));
    clear($("#limits-sum"));
    const mark = (d) => {
      roots().forEach((root) => {
        $$("tr", root).filter((tr) => tr.dataset.label === d.id).forEach((tr) => {
          const td = tr.querySelector("td.col-live");
          td.className = "col-live mono";
          clear(td).appendChild(tick(d.match === true));
        });
      });
    };
    const unmarked = (words) => roots().forEach((root) => {
      $$("td.live-wait", root).forEach((td) => { td.className = "col-live mono"; td.textContent = words; });
    });
    job("racing/limits", {}, {
      queued: pg.queued,
      stage: pg.stage,
      line: mark,
      result: (d) => {
        pg.finish(true);
        unmarked(t("r.na"));
        const ok = d.match === true;
        const txt = (d.matched != null && d.sessions != null ? d.matched + " / " + d.sessions + " " : "") + t("r.lines." + (d.mode || mode));
        const sum = clear($("#limits-sum"));
        sum.appendChild(tick(ok, t(ok ? "seal.same.all" : "seal.diff.all")));
        sum.appendChild(el("span", "race-sum-n", " " + txt));
        if (inRun) {
          summary.appendChild(el("p", "race-sum", txt));
          sealLive(d.record_shipped, d, d.mode || mode);
        }
        btn.disabled = false; setRunning(false);
      },
      fallback: () => {
        pg.finish(false);
        unmarked(t("live.stored"));
        if (inRun) showBusy(t("busy.racing"));
        else $("#limits-sum").textContent = t("busy.racing");
        btn.disabled = false; setRunning(false);
      },
    }, 200000);
  }

  function renderRacing() {
    const R = S.racing;
    if (!R) { $("#pick-racing").hidden = true; $("#racing-panel").hidden = true; return; }
    fillNumbers("data-rnum", "data-needs-r", R.numbers);
    const ps = R.protests || [];
    const first = ps.find((p) => p.honesty) || ps[0];
    if (first) {
      clear($("#poster-protest")).appendChild(protestTimeline(first));
      $("#pick-protest").addEventListener("click", () => select({ kind: "protest", id: S.protest || first.id }, true));
    } else $("#pick-protest").hidden = true;
    clear($("#poster-limits")).appendChild(limitsBars(R.limits || []));
    $("#pick-limits").addEventListener("click", () => select({ kind: "limits" }, true));
    const chips = clear($("#protest-chips"));
    ps.forEach((p) => {
      const c = el("button", "chip", p.label);
      c.type = "button";
      c.dataset.id = p.id;
      c.addEventListener("click", () => { showProtest(p.id); if (S.sel && S.sel.kind === "protest") select({ kind: "protest", id: p.id }); });
      chips.appendChild(c);
    });
    if (first) showProtest(first.id);
    $("#check-protest").addEventListener("click", () => { if (!S.running && S.protest) checkProtest(S.protest, "panel"); });
    $("#check-limits").textContent = limitsWord();
    $("#limits-fine").textContent = t("r.fine." + limitsMode());
    $("#check-limits").addEventListener("click", () => { if (!S.running) checkLimits("panel"); });
    limitsTable();
    const tb = clear($("#rboard tbody"));
    (R.scoreboard || []).forEach((r) => {
      const tr = el("tr");
      tr.appendChild(el("th", null, r.mark)).setAttribute("scope", "row");
      tr.appendChild(el("td", null, r.result));
      tr.appendChild(el("td", null, r.pass_mark));
      tr.appendChild(el("td", r.verdict === "pass" ? "pass" : r.verdict === "fail" ? "fail" : null, r.verdict));
      tb.appendChild(tr);
    });
  }

  // ---------------------------------------------------------------- shift
  // Master-detail: a short list of windows (the ones to review first), and one detail panel.
  // A list row holds only a title, the window's place in the shift and its verdict dots;
  // every rule's detail lives in the one panel, never inside a row.
  const SH = { filter: "review", open: null, rows: [], seq: 0, video: null };
  const hasV = (w, v) => (w.rulings || []).some((r) => r.verdict === v);
  const allV = (w, v) => (w.rulings || []).length > 0 && (w.rulings || []).every((r) => r.verdict === v);
  const FILTERS = { review: (w) => hasV(w, "breach"), unable: (w) => allV(w, "unable_to_rule"), all: () => true };
  const VORDER = { breach: 0, unable_to_rule: 1, clear: 2 };
  function windowWhere(i, n) { return t("window") + " " + (i + 1) + " " + t("window.of") + " " + n; }
  function windowGist(w) {
    const rs = w.rulings || [];
    const br = byVerdict(rs, "breach").length, un = byVerdict(rs, "unable_to_rule");
    if (br) return cap(words(br)) + " " + t(br === 1 ? "wd.breach" : "wd.breaches") + (un.length ? " · " + words(un.length) + " " + t("wd.unable") : "");
    if (un.length === rs.length) return cap(uniq(un.map(whyShort)).join("; "));
    if (un.length) return cap(words(un.length)) + " " + t("wd.unable") + ": " + uniq(un.map(whyShort)).join("; ");
    return t("wd.clear");
  }
  function renderShift() {
    const sh = S.shift;
    if (!sh || !(sh.windows || []).length) { $("#shift-panel").hidden = true; return; }
    const bar = clear($("#shiftbar"));
    const c = sh.counts || {};
    const total = (c.breach || 0) + (c.clear || 0) + (c.unable_to_rule || 0);
    // widths as classes would need one per percent; use flex-grow through a fixed set of classes
    ["breach", "clear", "unable_to_rule"].forEach((v) => {
      const n = c[v] || 0;
      if (!n || !total) return;
      bar.appendChild(el("span", "v-" + v + " g" + Math.max(1, Math.round((n / total) * 20))));
    });
    const n = sh.windows.length;
    Object.keys(FILTERS).forEach((f) => { const x = $("#wf-" + f); if (x) x.textContent = String(sh.windows.filter(FILTERS[f]).length); });
    const list = clear($("#windows"));
    SH.rows = sh.windows.map((w, i) => {
      const b = el("button", "wrow");
      b.type = "button";
      b.setAttribute("aria-expanded", "false");
      b.setAttribute("aria-controls", "wdetail");
      const th = el("span", "wthumb");
      if (w.poster) {
        const img = el("img");
        img.loading = "lazy";
        img.decoding = "async";
        img.alt = "";
        img.addEventListener("error", () => th.classList.add("missing"));
        img.src = DATA + w.poster;
        th.appendChild(img);
      } else th.classList.add("missing");
      b.appendChild(th);
      const tx = el("span", "wtext");
      tx.appendChild(el("span", "wtitle", clipTitle(w.clip)));
      const where = el("span", "wwhere");
      where.appendChild(el("span", null, windowWhere(i, n)));
      const st = {};
      (w.rulings || []).forEach((r) => { st[r.rule] = r.verdict; });
      where.appendChild(dots(st));
      tx.appendChild(where);
      tx.appendChild(el("span", "wgist" + (hasV(w, "breach") ? " t-breach" : ""), windowGist(w)));
      b.appendChild(tx);
      b.appendChild(el("span", "wopen", "Open evidence"));
      b.addEventListener("click", () => (SH.open === i ? closeWindow(true) : openWindow(i)));
      list.appendChild(b);
      return b;
    });
    $$("[data-wfilter]").forEach((btn) => btn.addEventListener("click", () => setFilter(btn.dataset.wfilter)));
    $("#wdetail").addEventListener("keydown", (e) => { if (e.key === "Escape") closeWindow(true); });
    list.addEventListener("keydown", (e) => { if (e.key === "Escape" && SH.open != null) closeWindow(true); });
    let rz = 0;
    window.addEventListener("resize", () => { cancelAnimationFrame(rz); rz = requestAnimationFrame(() => { if (SH.open != null) { $("#windows").after($("#wdetail")); placeDetail(SH.open); } }); });
    setFilter("review");
  }
  function setFilter(f) {
    const sh = S.shift;
    SH.filter = f;
    $$("[data-wfilter]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.wfilter === f)));
    let shown = 0;
    SH.rows.forEach((b, i) => { const on = FILTERS[f](sh.windows[i]); b.hidden = !on; if (on) shown++; });
    if (SH.open != null && SH.rows[SH.open].hidden) closeWindow(false);
    if (SH.open != null) { $("#windows").after($("#wdetail")); placeDetail(SH.open); }
    const cnt = String(shown), c = sh.counts || {};
    const head = !shown ? t("wcap.empty")
      : f === "review" ? (c.breach ? c.breach + " " + t("wcap.review.n") + " " + cnt + " " + t("wcap.review.tail") : cnt + " " + t("wcap.review"))
      : f === "unable" ? cnt + " " + t("wcap.unable")
      : cnt + " " + t("wcap.all");
    $("#wcaption").textContent = head + (shown ? " " + t("wcap.hint") : "");
  }
  // The panel opens full width directly under the line of the list that holds the picked row
  // (on a phone that is the row itself), so the list stays in view above it.
  function placeDetail(i) {
    const d = $("#wdetail");
    const top = SH.rows[i].offsetTop;
    const line = SH.rows.filter((b) => !b.hidden && b.offsetTop === top);
    (line[line.length - 1] || SH.rows[i]).after(d);
  }
  function closeWindow(focusRow) {
    const i = SH.open;
    if (i == null) return;
    SH.open = null;
    SH.seq++;
    unloadVideo();
    const d = $("#wdetail");
    d.hidden = true;
    clear(d);
    SH.rows[i].setAttribute("aria-expanded", "false");
    SH.rows[i].classList.remove("on");
    $("#windows").after(d);
    if (focusRow) SH.rows[i].focus();
  }
  // An unable ruling in the panel: why (from the record), what it needs, the rest of the measurement.
  function unableLines(r) {
    const out = [el("p", "wd-key", whySentence(r) || needsLine(r))];
    if (whySentence(r) && needsAdds(r)) out.push(el("p", "needs", needsLine(r)));
    const rest = String(r.measurement || "").trim().slice(whySentence(r).length).trim();
    if (rest) out.push(el("p", "evidence", rest));
    return out;
  }
  function openWindow(i) {
    if (SH.open != null) closeWindow(false);
    const sh = S.shift, w = sh.windows[i];
    SH.open = i;
    SH.rows[i].setAttribute("aria-expanded", "true");
    SH.rows[i].classList.add("on");
    const d = clear($("#wdetail"));
    const head = el("div", "wd-head");
    const hx = el("div");
    hx.appendChild(el("p", "kicker", windowWhere(i, sh.windows.length)));
    const h = el("h3", null, clipTitle(w.clip));
    h.id = "wd-title";
    hx.appendChild(h);
    hx.appendChild(el("p", "wd-gist", windowGist(w)));
    head.appendChild(hx);
    const x = el("button", "wd-close", t("wd.close"));
    x.type = "button";
    x.addEventListener("click", () => closeWindow(true));
    head.appendChild(x);
    d.appendChild(head);
    d.setAttribute("aria-labelledby", "wd-title");
    const body = el("div", "wd-body");
    let fig = posterFig(w);
    body.appendChild(fig);
    const rl = el("div", "wd-rules");
    const refs = [];
    // A reason that several rulings share (a camera that moved fails every rule) is said once.
    const unr = byVerdict(w.rulings, "unable_to_rule");
    const m0 = unr.length > 1 && unr.every((r) => r.measurement === unr[0].measurement) ? unr[0] : null;
    if (m0) {
      const sh0 = el("div", "wd-shared");
      sh0.appendChild(el("p", "label", t("why.unable") + " " + t(unr.length === (w.rulings || []).length ? "wd.shared.all" : "wd.shared.these")));
      unableLines(m0).forEach((x) => sh0.appendChild(x));
      rl.appendChild(sh0);
    }
    (w.rulings || []).slice().sort((a, b) => (VORDER[a.verdict] || 0) - (VORDER[b.verdict] || 0)).forEach((r) => {
      const row = el("div", "wd-rule");
      const top = el("div", "wd-rule-top");
      top.appendChild(stamp(r.verdict, true));
      top.appendChild(el("p", "wd-rule-title", r.title || r.rule));
      row.appendChild(top);
      if (r.verdict === "breach" && r.decided_by) row.appendChild(el("p", "wd-key", t("wd.decided") + ": " + r.decided_by));
      if (r.verdict === "unable_to_rule") { if (!m0) unableLines(r).forEach((x) => row.appendChild(x)); }
      else if (r.measurement) row.appendChild(el("p", "evidence", r.measurement));
      if ((r.frames || []).length) {
        const fp = el("p", "wd-frames");
        framesText(fp, r.frames);
        refs.push({ p: fp, frames: r.frames });
        row.appendChild(fp);
      }
      rl.appendChild(row);
    });
    body.appendChild(rl);
    d.appendChild(body);
    $("#windows").after(d);
    placeDetail(i);
    d.hidden = false;
    const r = d.getBoundingClientRect();
    if (r.top < 0 || r.top > window.innerHeight * 0.6) d.scrollIntoView({ behavior: still() ? "auto" : "smooth", block: "start" });
    // The window's footage replaces the still once the manifest says it exists; until then,
    // and whenever it is missing or fails, the poster stays exactly as it was.
    const seq = SH.seq;
    videoIndex().then(() => {
      if (SH.open !== i || SH.seq !== seq) return;
      const m = VID.by[w.window];
      if (!m) return;
      const v = videoFig(w, m, () => {
        if (SH.video !== v.video) return;
        unloadVideo();
        const back = posterFig(w);
        v.fig.replaceWith(back);
        fig = back;
        refs.forEach((x) => framesText(x.p, x.frames));
      });
      fig.replaceWith(v.fig);
      fig = v.fig;
      refs.forEach((x) => framesButtons(x.p, x.frames, v.video, m));
    });
  }
  function frameLabel(f) { return t("frame") + " " + f.n + " · " + Number(f.t_s).toFixed(2) + " s"; }
  function framesText(p, frames) { clear(p).textContent = frames.map(frameLabel).join(", "); }
  // A frame ref seeks the window's video to that moment and holds it there. The ref counts
  // from the window's start, the same zero as the video.
  function framesButtons(p, frames, video, m) {
    clear(p);
    p.classList.add("has-refs");
    frames.forEach((f) => {
      const b = el("button", "fref", frameLabel(f));
      b.type = "button";
      b.setAttribute("aria-label", t("wd.jump") + " " + frameLabel(f));
      const at = f.t_s != null ? Number(f.t_s) : Number(f.n) / (m.fps || 24);
      b.addEventListener("click", () => {
        $$(".fref.on", $("#wdetail")).forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        seekTo(video, at);
      });
      p.appendChild(b);
    });
  }
  function seekTo(v, at) {
    const go = () => {
      v.pause();
      const end = isFinite(v.duration) ? Math.max(0, v.duration - 0.01) : at;
      v.currentTime = Math.min(Math.max(0, at), end);
    };
    v.autoplay = false;
    if (v.readyState >= 1) go();
    else { v.preload = "auto"; v.addEventListener("loadedmetadata", go, { once: true }); v.load(); }
    const r = v.getBoundingClientRect();
    if (r.top < 0 || r.bottom > window.innerHeight) v.scrollIntoView({ behavior: still() ? "auto" : "smooth", block: "nearest" });
  }
  function posterFig(w) {
    const fig = el("figure", "wd-poster");
    if (w.poster) {
      const b = el("button", "frame-btn");
      b.type = "button";
      b.setAttribute("aria-label", t("wd.poster"));
      const img = el("img");
      img.decoding = "async";
      img.alt = t("wd.poster");
      img.addEventListener("error", () => b.classList.add("missing"));
      img.src = DATA + w.poster;
      b.appendChild(img);
      b.addEventListener("click", () => { if (!b.classList.contains("missing")) enlarge(DATA + w.poster, clipTitle(w.clip)); });
      fig.appendChild(b);
      fig.appendChild(el("figcaption", null, t("wd.poster")));
    } else fig.appendChild(el("p", "noframe", t("frames.none")));
    return fig;
  }
  // The video is made only when its window opens, so nothing loads until a reader asks.
  function videoFig(w, m, onFail) {
    const fig = el("figure", "wd-poster wd-video");
    const v = el("video");
    v.controls = true;
    v.muted = true;
    v.loop = false;
    v.playsInline = true;
    v.setAttribute("playsinline", "");
    v.setAttribute("muted", "");
    v.preload = "metadata";
    if (m.width && m.height) { v.width = m.width; v.height = m.height; }
    if (w.poster) v.poster = DATA + w.poster;
    v.setAttribute("aria-label", t("wd.video") + ": " + clipTitle(w.clip));
    v.addEventListener("error", onFail);
    v.src = DATA + m.file;
    SH.video = v;
    fig.appendChild(v);
    fig.appendChild(el("figcaption", null, t("wd.video.cap")));
    if (!still()) { v.autoplay = true; const pp = v.play(); if (pp) pp.catch(() => {}); }
    return { fig, video: v };
  }
  // Pause, drop the source and reset, so only one window's video ever holds memory.
  function unloadVideo() {
    const v = SH.video;
    if (!v) return;
    SH.video = null;
    v.pause();
    v.removeAttribute("src");
    v.load();
  }
  // data/video/videos.json: {schema, videos: [{file, window, fps, width, height, ...}]}.
  // Fetched once, the first time any window opens; a missing manifest means posters only.
  const VID = { p: null, by: {} };
  function videoIndex() {
    if (!VID.p) {
      VID.p = getJSON(DATA + "video/videos.json")
        .then((doc) => { ((doc && doc.videos) || []).forEach((x) => { if (x && x.window && x.file) VID.by[x.window] = x; }); })
        .catch(() => {});
    }
    return VID.p;
  }

  // ---------------------------------------------------------------- the shipped-3 replay and the graded set
  function replayShipped() {
    if (S.running) return;
    const btn = $("#replay-shipped");
    btn.disabled = true;
    const ol = clear($("#replay-lines"));
    const end = $("#replay-end");
    end.hidden = true;
    const pg = progress("prog-shipped", "shipped");
    bringIntoView($("#prog-shipped"), btn);
    S.running = true;
    $("#go").disabled = true;
    // the shipped clips show at once, each waiting for its rebuilt line
    const row = (id) => {
      const li = el("li", "wait");
      li.dataset.id = id;
      li.appendChild(el("span", null, id));
      li.appendChild(el("span", "state", t("replay.wait")));
      ol.appendChild(li);
      return li;
    };
    ((S.index || {}).clips || []).filter((c) => c.group === "shipped").forEach((c) => row(c.id));
    const done = () => { btn.disabled = false; S.running = false; if (S.sel) barFor(S.sel); };
    job("replay-shipped", {}, {
      queued: pg.queued,
      stage: pg.stage,
      line: (d) => {
        const id = d.id || "";
        const li = $$("li", ol).find((x) => x.dataset.id === id) || row(id);
        li.className = d.match ? "ok-row" : "bad-row";
        const st = li.querySelector(".state");
        st.className = "state " + (d.match ? "ok" : "bad");
        st.textContent = t(d.match ? "replay.ok" : "replay.bad");
      },
      result: (d) => {
        pg.finish(true);
        clear(end);
        const want = ((S.index || {}).shipped_replay || {}).sha256;
        const home = !!want && d.set_sha256 === want;
        end.appendChild(document.createTextNode(t("replay.end") + " "));
        end.appendChild(hashCode(d.set_sha256));
        end.appendChild(document.createTextNode(" "));
        end.appendChild(tick(home, t(home ? "replay.home" : "replay.nothome")));
        if (typeof d.seconds === "number") end.appendChild(el("span", "fine", " " + d.seconds.toFixed(1) + " " + t("seal.secs")));
        end.hidden = false;
        done();
      },
      fallback: () => {
        pg.finish(false);
        $$("li.wait", ol).forEach((li) => { li.className = ""; li.querySelector(".state").textContent = t("replay.skip"); });
        end.textContent = t("replay.busy");
        end.hidden = false;
        done();
      },
    }, 240000);
  }
  async function gradedSet() {
    let g;
    try { g = await getJSON(API + "graded26"); } catch (e) { return; }
    const want = ((S.index || {}).graded_replay || {}).sha256;
    // graded26.json: {time, seconds, set_sha256, commit, network, result}, written by install.sh
    const sha = g && g.set_sha256;
    if (!sha) return;
    const code = $("#graded-sha");
    code.textContent = sha;
    $("#graded-when").textContent = [g.time || "", typeof g.seconds === "number" ? g.seconds.toFixed(0) + " s" : ""].filter(Boolean).join(" · ");
    const m = clear($("#graded-match"));
    m.appendChild(tick(!!want && sha === want, ""));
    m.appendChild(document.createTextNode(" " + t(want && sha === want ? "graded.match" : "graded.nomatch")));
    $("#graded-set").hidden = false;
  }

  // ---------------------------------------------------------------- boot
  function renderIndex() {
    const I = S.index;
    fillNumbers("data-num", "data-needs", I.numbers);
    (I.clips || []).forEach((c) => { S.byId[c.id] = c; });
    const feat = clear($("#featured"));
    (I.featured || []).forEach((id) => { if (S.byId[id]) feat.appendChild(clipTile(S.byId[id])); });
    ["graded", "real"].forEach((g) => {
      const list = (I.clips || []).filter((c) => c.group === g && (I.featured || []).indexOf(c.id) < 0);
      const ul = clear($("#list-" + g));
      list.forEach((c) => ul.appendChild(clipRow(c)));
      $$('[data-count="' + g + '"]').forEach((n) => { n.textContent = list.length ? String(list.length) : ""; });
      if (!list.length) $("#more-" + g + "-btn").hidden = true;
      if (g === "real") {
        const rt = clear($("#real-tiles"));
        list.forEach((c) => rt.appendChild(clipTile(c)));
      }
    });
    drawer($("#more-graded-btn"), $("#more-graded"));
    drawer($("#more-real-btn"), $("#more-real"));
    const ol = clear($("#models"));
    (I.models || []).forEach((m) => {
      const li = el("li");
      const body = el("span");
      body.appendChild(el("b", null, m.name));
      body.appendChild(el("span", "where", " (" + m.where + ") "));
      body.appendChild(document.createTextNode(m.use || ""));
      li.appendChild(body);
      ol.appendChild(li);
    });
    // the README line marks the model id with backticks: show it as code, never as raw marks
    const ow = clear($("#open-weight"));
    String(I.open_weight_line || "").split("`").forEach((part, i) => {
      ow.appendChild(i % 2 ? el("code", null, part) : document.createTextNode(part));
    });
    const sha = (I.shipped_replay || {}).sha256 || "";
    // the shipped count is the record's own line count, from the bundle, never typed in the HTML
    const shippedLines = (I.shipped_replay || {}).lines;
    $$('[data-count="shipped"]').forEach((n) => { n.textContent = typeof shippedLines === "number" ? String(shippedLines) : ""; });
    $("#shipped-sha").textContent = sha;
    $("#home-sha").textContent = sha;
    if (I.featured && I.featured[0]) select({ kind: "clip", id: I.featured[0] });
  }

  async function boot() {
    $("#go").addEventListener("click", () => {
      if (S.running || !S.sel) return;
      if (S.sel.kind === "clip") ruleClip(S.sel.id);
      else if (S.sel.kind === "protest") checkProtest(S.sel.id, "run");
      else if (S.sel.kind === "limits") checkLimits("run");
    });
    $("#replay-shipped").addEventListener("click", replayShipped);
    try {
      S.index = await getJSON(DATA + "index.json");
    } catch (e) {
      $("#sel-name").textContent = t("load.fail");
      return;
    }
    renderIndex();
    try { S.racing = await getJSON(DATA + "racing.json"); } catch (e) { S.racing = null; }
    try { S.racingMedia = await getJSON(DATA + "racing/media.json"); } catch (e) { S.racingMedia = null; }
    renderRacing();
    try { S.shift = await getJSON(DATA + "shift.json"); } catch (e) { S.shift = null; }
    renderShift();
    gradedSet();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
