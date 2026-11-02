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
        assert f"go.{mode}" in keys and f"r.lines.{mode}" in keys and f"run.limits.{mode}" in keys
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
