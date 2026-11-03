"""The live demo page (site/): CSP-safe, numbers only from the bundle, hooks match the schema.

The page is static HTML, CSS and JS. These tests read the files as text: no browser, no network.
Its fixture bundle (tests/fixtures/site_page/) is hand-written from the plan's bundle schema.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
FIX = Path(__file__).resolve().parent / "fixtures" / "site_page"
REPO_LINK = "https://github.com/BrockDawg/faultline"
ALLOWED_NUMBERS = {"0", "1", "2", "3", "24"}
# The medical and sports words are swept over every repo file, site/ included, by
# tests/test_provenance.py; spelling them out here would put them in this file.
TOOLING = re.compile(r"\b(claude|anthropic|agent|harness|builder|tournament|wave)\b", re.I)


class _Page(HTMLParser):
    """Collects visible text, tags with attributes, and script/style bodies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.text: list[str] = []
        self.inline_script: list[str] = []
        self.inline_style: list[str] = []
        self._in: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if tag in ("script", "style"):
            self._in = tag

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._in == "script":
            if data.strip():
                self.inline_script.append(data)
        elif self._in == "style":
            if data.strip():
                self.inline_style.append(data)
        else:
            self.text.append(data)


def _page() -> _Page:
    p = _Page()
    p.feed((SITE / "index.html").read_text(encoding="utf-8"))
    return p


def _fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_viewport_meta_present():
    tags = _page().tags
    vp = [a for t, a in tags if t == "meta" and a.get("name") == "viewport"]
    assert vp and "width=device-width" in (vp[0].get("content") or "")


def test_no_inline_script_or_style():
    p = _page()
    scripts = [a for t, a in p.tags if t == "script"]
    assert scripts, "the page loads app.js"
    assert all(a.get("src") for a in scripts), "a <script> without src breaks the CSP"
    assert not p.inline_script
    assert not p.inline_style and not any(t == "style" for t, _ in p.tags)
    assert not any("style" in a for _, a in p.tags), "a style= attribute breaks the CSP"
    handlers = [k for _, a in p.tags for k in a if k.startswith("on")]
    assert not handlers, "inline handlers break the CSP"


def test_js_never_sets_inline_style_or_html():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    assert ".style" not in js, "toggle classes; element.style breaks the CSP"
    assert 'setAttribute("style"' not in js and "innerHTML" not in js
    assert "eval(" not in js and "new Function" not in js


def test_no_third_party_url():
    for name in ("index.html", "app.js", "app.css"):
        text = (SITE / name).read_text(encoding="utf-8")
        urls = re.findall(r"https?://[^\s\"'<>)]+", text)
        others = [u for u in urls if u != REPO_LINK and u != "http://www.w3.org/2000/svg"]
        assert not others, f"{name}: {others}"
    css = (SITE / "app.css").read_text(encoding="utf-8")
    assert "@import" not in css and "@font-face" not in css


def test_no_number_in_html_text_outside_the_allow_list():
    text = " ".join(_page().text)
    nums = set(re.findall(r"\d+(?:\.\d+)?", text))
    assert nums <= ALLOWED_NUMBERS, f"numbers typed into the HTML: {sorted(nums - ALLOWED_NUMBERS)}"


def test_no_tooling_words_in_page_copy():
    text = " ".join(_page().text)
    assert not TOOLING.findall(text), TOOLING.findall(text)
    js = (SITE / "app.js").read_text(encoding="utf-8")
    strings = " ".join(re.findall(r"\"([^\"\\]*)\"", js))
    assert not TOOLING.findall(strings), TOOLING.findall(strings)


def test_every_number_hook_exists_in_the_fixture():
    tags = _page().tags
    index = _fixture("index.json")
    racing = _fixture("racing.json")
    for attr, needs, numbers in (
        ("data-num", "data-needs", index["numbers"]),
        ("data-rnum", "data-needs-r", racing["numbers"]),
    ):
        hooks = {a[attr] for _, a in tags if a.get(attr)}
        assert hooks, attr
        assert hooks <= set(numbers), f"{attr} not in the schema fixture: {hooks - set(numbers)}"
        needed = {k for _, a in tags if a.get(needs) for k in (a[needs] or "").split()}
        assert needed <= set(numbers), f"{needs}: {needed - set(numbers)}"
        unless = needs.replace("needs", "unless")
        fall = {k for _, a in tags if a.get(unless) for k in (a[unless] or "").split()}
        assert fall <= set(numbers), f"{unless}: {fall - set(numbers)}"
    real = {"real_camera_line", "real_floor_unable", "real_hi_vis"}  # README 316-317
    page = {a["data-num"] for _, a in tags if a.get("data-num")}
    assert real <= page, f"the real-footage panel lacks {real - page}"


def test_real_footage_wording_has_a_fallback():
    """Without the README keys the panel still reads: the floor and hi-vis claims keep their
    own words inside the hook, and the camera-line clause hides."""
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert '<span data-num="real_floor_unable">every rule' in html
    assert '<span data-num="real_hi_vis">the hi-vis rule' in html
    assert 'data-needs="real_camera_line"' in html


def test_every_copy_key_the_js_reads_is_in_the_html():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    keys = {a["data-copy"] for _, a in _page().tags if a.get("data-copy")}
    used = set(re.findall(r"\bt\(\"([a-z_.]+)\"\)", js))
    assert used, "the JS reads its copy from the HTML"
    assert used <= keys, f"copy keys the HTML lacks: {sorted(used - keys)}"
    # dynamic keys: verdicts, hints, frame sources and limit modes
    for k in ("breach", "clear", "unable_to_rule"):
        assert f"verdict.{k}" in keys
    for c in _fixture("index.json")["clips"]:
        assert f"hint.{c['hint']}" in keys
    for mode in ("rerule", "checked"):
        assert f"go.{mode}" in keys and f"r.lines.{mode}" in keys and f"seal.how.{mode}" in keys
        assert f"what.{mode}" in keys and f"r.fine.{mode}" in keys and f"prog.head.{mode}" in keys
    for k in ("clip", "racing", "limits"):
        assert f"why.{k}" in keys
    for n in ("one", "all"):
        assert f"seal.same.{n}" in keys and f"seal.diff.{n}" in keys
    for src in ("ruling", "model", "window"):
        assert f"frames.{src}" in keys


def test_every_id_the_js_reads_exists_in_the_html():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    ids = {a["id"] for _, a in _page().tags if a.get("id")}
    used = set(re.findall(r"\$\(\"#([A-Za-z0-9_-]+)(?:\"\)| )", js))
    for g in ("graded", "real"):  # built as "#list-" + g, "#more-" + g + "-btn"
        used |= {f"list-{g}", f"more-{g}", f"more-{g}-btn"}
    used |= set(re.findall(r"getElementById\(\"([A-Za-z0-9_-]+)\"\)", js))
    assert used <= ids, f"ids the HTML lacks: {sorted(used - ids)}"


def test_js_reads_only_schema_fields():
    """Every bundle field the JS names exists in the hand-written schema fixture."""
    js = (SITE / "app.js").read_text(encoding="utf-8")
    index, racing, shift = _fixture("index.json"), _fixture("racing.json"), _fixture("shift.json")
    clip = _fixture("clips/blind_corner_no_vest_07.json")

    def keys(o, out):
        if isinstance(o, dict):
            for k, v in o.items():
                out.add(k)
                keys(v, out)
        elif isinstance(o, list):
            for v in o:
                keys(v, out)
        return out

    schema = set()
    for doc in (index, racing, shift, clip):
        keys(doc, schema)
    # worker event fields (the plan's worker API), and the JS's own state names
    worker = {
        "job",
        "position",
        "name",
        "id",
        "match",
        "record",
        "record_shipped",
        "record_rebuilt",
        "rulings",
        "seconds",
        "set_sha256",
        "message",
        "lines",
        "arm",
        "mode",
        "matched",
        "sessions",
        "why",
        "time",
    }
    own = {
        "dataset",
        "textContent",
        "className",
        "classList",
        "length",
        "hidden",
        "disabled",
        "firstChild",
        "matches",
        "data",
        "type",
        "alt",
        "src",
        "loading",
        "decoding",
        "title",
        "ok",
        "json",
        "showModal",
        "focus",
        "close",
        "kind",
        "sel",
        "running",
        "clips",
        "byId",
        "protest",
        "label",
        "n",
        "copy",
        "closest",
        "querySelector",
        "appendChild",
        "readyState",
        "onerror",
        "checked",
        "words",
        "pack",
        "verdict",
        "rule",
        "status",
    }
    read = set(re.findall(r"\b(?:[a-zA-Z_]\w*|\))\.([a-z_][a-z_0-9]*)\b", js))
    bundle_like = {k for k in read if "_" in k}
    missing = {k for k in bundle_like if k not in schema | worker | own}
    assert not missing, f"fields the JS reads that the schema lacks: {sorted(missing)}"
    for k in (
        "featured",
        "clips",
        "numbers",
        "models",
        "open_weight_line",
        "shipped_replay",
        "graded_replay",
        "rulings",
        "frames",
        "frames_source",
        "decided_by",
        "measurement",
        "pack_words",
        "lacks",
        "words",
        "note",
        "reads",
        "agreed",
        "protests",
        "limits",
        "limits_mode",
        "candidates",
        "facts",
        "steward_ruling",
        "scoreboard",
        "honesty",
        "feed_s",
        "moment_feed_s",
        "ruling_on_record",
        "windows",
        "counts",
        "incidents",
        "limit",
    ):
        assert k in schema, f"the fixture lacks {k}"
        assert re.search(r"\b" + k + r"\b", js), f"the JS never reads {k}"


def test_fixture_follows_the_schema():
    index = _fixture("index.json")
    assert index["schema"] == 1
    ids = [c["id"] for c in index["clips"]]
    assert len(ids) == len(set(ids)), "a clip id appears once"
    assert set(index["featured"]) <= set(ids)
    for cid in index["featured"]:
        clip = _fixture(f"clips/{cid}.json")
        assert clip["id"] == cid and clip["record"] == next(
            c["record"] for c in index["clips"] if c["id"] == cid
        )
        for r in clip["rulings"]:
            assert r["verdict"] in ("breach", "clear", "unable_to_rule")
            assert r["frames_source"] in ("ruling", "model", "window")
    racing = _fixture("racing.json")
    assert racing["limits_mode"] in ("rerule", "checked")
    raw = (FIX / "racing.json").read_text(encoding="utf-8")
    raw = re.sub(r"\b[0-9a-f]{64}\b", "", raw)  # record hashes
    assert not re.search(r"\b\d{5,}\b", raw), "no sim session number in the racing fixture"


def test_graded_set_reads_only_the_install_keys():
    """graded26.json is {time, seconds, set_sha256, commit, network, result} (install.sh)."""
    js = (SITE / "app.js").read_text(encoding="utf-8")
    body = js[js.index("async function gradedSet") :]
    body = body[: body.index("\n  }\n")]
    read = set(re.findall(r"\bg\.([a-z_0-9]+)", body))
    allowed = {"time", "seconds", "set_sha256", "commit", "network", "result"}
    assert read and read <= allowed, read


KINDS = ("clip", "shipped", "protest", "rerule", "checked")
STAGE_NAMES = ("queued", "start", "record", "rebuild", "seal")


def _copy_keys() -> set[str]:
    return {a["data-copy"] for _, a in _page().tags if a.get("data-copy")}


def test_every_button_says_what_it_will_do_before_the_press():
    """The one button carries a plain line (why the check matters) right before it, the
    copy for each kind it can run sits in the HTML, and each of the four live buttons has
    its own progress panel slot."""
    html = (SITE / "index.html").read_text(encoding="utf-8")
    go = html.index('id="go"')
    assert html.index('id="go-what"') < go, "the dispute line sits right before the button"
    ids = {a["id"] for _, a in _page().tags if a.get("id")}
    keys = _copy_keys()
    for k in ("what.clip", "what.protest", "what.rerule", "what.checked"):
        assert k in keys, k
    js = (SITE / "app.js").read_text(encoding="utf-8")
    for slot in ("prog-run", "prog-shipped", "prog-protest", "prog-limits"):
        assert slot in ids, slot
        assert f'"{slot}"' in js, f"the JS never fills {slot}"
    assert 'progress("prog-shipped", "shipped")' in js
    assert 'progress("prog-run", "clip")' in js


def test_every_stage_has_a_plain_sentence_for_every_kind():
    keys = _copy_keys()
    for s in STAGE_NAMES:
        assert f"st.{s}" in keys, s
    for s in ("queued", "start"):
        assert f"st.{s}.what" in keys, s
    for kind in KINDS:
        for s in ("record", "rebuild", "seal"):
            assert f"st.{s}.what.{kind}" in keys, (s, kind)
    for kind in ("clip", "protest", "rerule", "checked"):
        assert f"seal.how.{kind}" in keys, kind


def test_progress_moves_only_on_worker_events():
    """A stage event names a step just passed, so the next step lights; the only timer is
    the elapsed clock, which writes seconds and nothing else."""
    js = (SITE / "app.js").read_text(encoding="utf-8")
    body = js[js.index("function progress(") :]
    body = body[: body.index("\n  }\n")]
    assert 'const STAGES = ["queued", "start", "record", "rebuild", "seal"]' in js
    assert "at(i + 1)" in body, "a stage event lights the step after it"
    assert js.count("setInterval(") == 1 and "setInterval(show, 100)" in body
    show = re.search(r"const show = \(\) => \{([^}]*)\};", body)
    assert show and show.group(1).strip().startswith("secs.textContent"), (
        "the clock writes seconds only"
    )
    assert "Math.random" not in js and "%" not in re.sub(r"//.*", "", body)


def test_stored_cards_show_at_once_then_flip():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    rule = js[js.index("async function ruleClip") :]
    rule = rule[: rule.index("\n  }\n")]
    assert rule.index("renderRulings(clip)") < rule.index('job("rule"'), (
        "stored cards before the job"
    )
    assert 'cardState(c, "wait", t("card.wait"))' in js
    assert "flipCards(live" in rule and '"stored", t("card.stored")' in rule
    flip = js[js.index("function flipCards") :]
    flip = flip[: flip.index("\n  }\n")]
    assert "still() ? 0 : 120" in flip, "the reveal stagger is off under reduced motion"
    css = (SITE / "app.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion:reduce" in css.replace(" ", "")
    for cls in (".rcard.wait", ".rcard.same", ".rcard.differs", ".stages li.on", ".stages li.done"):
        assert cls in css, cls


def test_the_busy_line_is_the_plans_own_words():
    keys = {a["data-copy"]: a for _, a in _page().tags if a.get("data-copy")}
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "busy.clip" in keys
    assert "stored ruling — live check unavailable. The live rebuild is busy, try again in a minute." in html


def _copy() -> dict[str, str]:
    """data-copy key -> its text, read from the hidden copy block."""
    html = (SITE / "index.html").read_text(encoding="utf-8")
    return dict(re.findall(r'<span data-copy="([^"]+)">([^<]*)</span>', html))


def test_the_check_button_says_check_nobody_changed_it():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert re.search(r'id="go"[^>]*>Check nobody changed it</button>', html)
    assert re.search(r'id="check-protest"[^>]*>Check nobody changed it</button>', html)
    copy = _copy()
    assert copy["go.clip"] == "Check nobody changed it"
    assert copy["go.protest"] == "Check nobody changed it"


def _body(js: str, start: str) -> str:
    body = js[js.index(start) :]
    return body[: body.index("\n  }\n")]


def test_the_result_headline_is_the_meaning():
    """The result leads with what the check means; hashes sit in one small detail line."""
    copy = _copy()
    assert copy["seal.same.one"] == "Same ruling. Nobody edited it."
    assert copy["seal.diff.one"] == (
        "Not the same: this ruling does not match its published record."
    )
    js = (SITE / "app.js").read_text(encoding="utf-8")
    head = _body(js, "function sealHead(")
    assert '"seal.same." + n' in head and '"seal.diff." + n' in head
    live = _body(js, "function sealLive(")
    assert live.index("sealHead(") < live.index("sealDetail("), "meaning before the hashes"
    assert copy["live.same"] == "unchanged", "each card says it quietly"


def test_no_byte_word_in_the_page_copy():
    """No user-facing byte-identical or byte for byte in the page's own words. The only one
    left is a README number (the scoreboard's replay row), rendered from the bundle."""
    text = " ".join(_page().text) + " " + " ".join(_copy().values())
    hits = re.findall(r"[^.]*\bbyte[^.]*", text, re.I)
    assert not hits, hits
    js = (SITE / "app.js").read_text(encoding="utf-8")
    strings = " ".join(re.findall(r"\"([^\"\\]*)\"", js))
    assert not re.search(r"\bbyte", strings, re.I)


def test_every_featured_clip_opens_as_an_incident():
    """The three featured clips carry hand-written sentences from the film script; the JS
    reads them before building any from the record's own rulings."""
    copy = _copy()
    for cid in _fixture("index.json")["featured"]:
        assert copy.get(f"case.title.{cid}"), cid
        assert copy.get(f"case.story.{cid}"), cid
    assert "no hi-vis" in copy["case.story.blind_corner_no_vest_07"]
    assert "Both wore hi-vis" in copy["case.story.spotter_ahead_01"]
    assert "Nobody walked into view" in copy["case.story.idle_empty_aisle_40"]
    js = (SITE / "app.js").read_text(encoding="utf-8")
    story = _body(js, "function clipStory(")
    assert story.index('"case.story." + clip.id') < story.index("clip.rulings"), (
        "the script's sentences win; the rest come from the record's rulings"
    )
    assert ".words" not in story and "note" not in story, (
        "a model's words never become the incident's sentences"
    )
    for k in ("for.lead", "for.insurer", "for.person", "why.clip", "why.racing"):
        assert copy.get(k), k


def _shift_html() -> str:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    start = html.index('id="shift-panel"')
    return html[start : html.index("</section>", start)]


def test_the_shift_list_holds_no_rule_detail():
    """A window's rules open in one detail panel beside the list, never inside a list row."""
    html = _shift_html()
    assert html.count('id="windows"') == 1 and html.count('id="wdetail"') == 1
    assert "<details" not in html and "<ul" not in html
    assert html.index('id="windows"') < html.index('id="wdetail"'), "the panel sits after the list"
    js = (SITE / "app.js").read_text(encoding="utf-8")
    render = _body(js, "function renderShift(")
    for k in ("details", "summary", "measurement", "decided_by", "lacks", "whySentence("):
        assert k not in render, f"the list rows read {k}: rule detail belongs in the panel"
    detail = _body(js, "function openWindow(")
    assert 'clear($("#wdetail"))' in detail and "SH.open = i" in detail
    assert "closeWindow(false)" in detail.split("SH.open = i")[0], "one window open at a time"
    assert '"Escape"' in render and "aria-expanded" in render


def test_the_shift_list_opens_on_the_review_list():
    html = _shift_html()
    pressed = re.findall(r'data-wfilter="(\w+)" aria-pressed="(\w+)"', html)
    assert dict(pressed) == {"review": "true", "unable": "false", "all": "false"}
    js = (SITE / "app.js").read_text(encoding="utf-8")
    assert 'setFilter("review")' in _body(js, "function renderShift(")
    assert 'review: (w) => hasV(w, "breach")' in js


def test_the_shift_panel_copy_has_no_static_digits():
    text = re.sub(r"<[^>]+>", " ", _shift_html())
    assert not re.findall(r"\d", text), "render shift numbers from the bundle"
    shift_keys = [k for k in _copy() if k.split(".")[0] in ("wcap", "wd", "window")]
    assert shift_keys
    assert not [k for k in shift_keys if re.search(r"\d", _copy()[k])]


def test_an_unable_ruling_never_shows_its_needed_fact_bare():
    """FACT_WORDS name the fact a ruling NEEDED ("a camera held still…"); shown bare it reads
    as the opposite of the truth. The reason leads, from the record's measurement, and the
    fact only ever appears behind the "It needs:" label."""
    from faultline.adapters.video.dashboard import FACT_WORDS

    copy = _copy()
    assert copy["needs"] == "It needs:"
    assert copy["why.unable"] == "Why it could not rule"
    assert "for.lacked" not in copy and "lacks" not in copy
    js = (SITE / "app.js").read_text(encoding="utf-8")
    html = (SITE / "index.html").read_text(encoding="utf-8")
    for phrase in FACT_WORDS.values():
        assert phrase not in js and phrase not in html, phrase
    # lacksOf is read only by needsLine (which prefixes the label) and needsAdds (a compare)
    allowed = []
    for f in ("function lacksOf(", "function needsLine(", "function needsAdds("):
        at = js.index(f)
        eol = js.find("\n", at)
        one_line = js[at:eol].rstrip().endswith("}")
        allowed.append((at, eol if one_line else js.find("\n  }\n", at)))
    for m in re.finditer(r"lacksOf\(", js):
        assert any(a <= m.start() < b for a, b in allowed), js[m.start() - 60 : m.start() + 20]
    assert 't("needs") + " " + lk' in _body(js, "function needsLine(")
    owns = [k for k in copy if k.startswith("needs.")]
    assert all(copy[k].startswith("It needs: ") for k in owns), owns
    lacks_lines = [ln.strip() for ln in js.splitlines() if "r.lacks" in ln]
    assert all("function lacksOf(" in ln or "const pw =" in ln for ln in lacks_lines), lacks_lines
    for fn in ("function ruleCard(", "function unableLines("):
        body = _body(js, fn)
        assert body.index("whySentence(r)") < body.index("needsLine(r)"), fn
    for fn in ("function clipStory(", "function clipFor(", "function windowGist("):
        assert "whyShort" in _body(js, fn) and "lacksOf" not in _body(js, fn), fn


def test_a_window_video_is_made_only_when_the_window_opens():
    """No video sits in the markup; the player is built inside openWindow's path, after the
    manifest (fetched once, lazily) names the window, and asks for metadata only."""
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "<video" not in html
    js = (SITE / "app.js").read_text(encoding="utf-8")
    assert js.count('"video/videos.json"') == 1
    index = _body(js, "function videoIndex(")
    assert "if (!VID.p)" in index, "the manifest is fetched once"
    assert "videoIndex()" not in _body(js, "function renderShift("), "not fetched at load"
    assert "videoIndex()" not in _body(js, "function boot(")
    assert "videoIndex()" in _body(js, "function openWindow(")
    fig = _body(js, "function videoFig(")
    assert 'el("video")' in fig and 'v.preload = "metadata"' in fig
    assert "v.muted = true" in fig and "v.loop = false" in fig and "playsinline" in fig
    assert fig.index("still()") < fig.index("v.play()"), "no autoplay under reduced motion"
    copy = _copy()
    assert copy["wd.video.cap"] == (
        "The footage the judge read for this window. Tap a frame on any rule to jump to it."
    )
    assert not re.search(r"\d", copy["wd.video.cap"] + copy["wd.jump"] + copy["wd.video"])


def test_frame_refs_are_buttons_that_seek_and_hold():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    refs = _body(js, "function framesButtons(")
    assert 'el("button", "fref", frameLabel(f))' in refs and 'b.type = "button"' in refs
    assert "Number(f.t_s)" in refs and "seekTo(video, at)" in refs
    seek = _body(js, "function seekTo(")
    assert "v.pause()" in seek and "v.currentTime =" in seek
    assert "loadedmetadata" in seek, "a seek before metadata waits for it"
    css = (SITE / "app.css").read_text(encoding="utf-8")
    assert re.search(r"\.fref\{[^}]*min-height:44px", css), "a phone tap target"


def test_a_missing_manifest_or_video_falls_back_to_the_poster():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    index = _body(js, "function videoIndex(")
    assert ".catch(() => {})" in index, "a missing manifest leaves the posters"
    opened = js[js.index("function openWindow(") : js.index("function frameLabel(")]
    assert "if (!m) return;" in opened, "a window without a video keeps its poster"
    assert "const back = posterFig(w);" in opened and "framesText(x.p, x.frames)" in opened
    assert 'v.addEventListener("error", onFail)' in _body(js, "function videoFig(")
    assert "error" not in _copy().get("wd.video.cap", "").lower()


def test_closing_or_switching_a_window_unloads_its_video():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    unload = _body(js, "function unloadVideo(")
    assert (
        unload.index("v.pause()")
        < unload.index('v.removeAttribute("src")')
        < unload.index("v.load()")
    )
    close = _body(js, "function closeWindow(")
    assert close.index("unloadVideo()") < close.index("clear(d)")
    assert "SH.seq++" in close, "a late manifest never mounts into a closed window"
    assert "closeWindow(false)" in _body(js, "function openWindow(").split("SH.open = i")[0]
