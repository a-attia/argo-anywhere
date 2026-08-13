"""Browser-level smoke tests for the web UI.

**Why this file exists.** As of 2026-08-09 the project had 430 passing Python
tests and *four* live defects in ``web/static/index.html`` -- three of which a
single page-load-and-click pass would have caught:

* **B1** the theme toggle called ``term.setOption()``, removed in xterm.js 5.x,
  inside a bare ``catch {}``. Palette switched; terminals never re-tinted.
  Shipped broken from v3.1.0.
* **B2** the Disconnect handler referenced a bare ``term`` global that D-031
  deleted, throwing ``ReferenceError`` and skipping the trailing
  ``refreshStatus()``.
* **B3** the panel divider position was persisted on every drag and then
  overwritten by a hardcoded ``applyPct(50)`` on boot.

None were visible to the backend suite, because the backend was fine -- the
bugs lived entirely in browser-side JavaScript that nothing ever executed.
These tests execute it.

**Scope discipline.** This module deliberately does NOT touch the SSH channel,
spawn an engine process, or open a ``/ws`` terminal session. It drives the
static UI against a ``create_app(engine_argv=["help"])`` instance: page load,
theme toggle, terminal show/hide, dialogs. Anything requiring a real channel
belongs in the manual live-test plan (``docs/TESTING.md``), not here.

Skipped cleanly when Playwright or its Chromium build is unavailable, so a
contributor without ``python -m playwright install chromium`` (and CI, which
does not install browsers) is not blocked.
"""

from __future__ import annotations

import socket
import threading
import time
from contextlib import closing

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from argo_anywhere.web.app import create_app  # noqa: E402


def _free_port() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def ui_server():
    """Serve the real app on a loopback port for the browser to hit.

    ``engine_argv=["help"]`` means any accidental /ws spawn runs the engine's
    help text and exits immediately -- it can never open an SSH connection.
    """
    uvicorn = pytest.importorskip("uvicorn", reason="uvicorn not installed")

    port = _free_port()
    config = uvicorn.Config(
        create_app(engine_argv=["help"]),
        host="127.0.0.1",
        port=port,
        log_level="error",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:  # pragma: no cover - environment failure
        pytest.skip("uvicorn did not start in time")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except PlaywrightError as exc:  # pragma: no cover - environment failure
            pytest.skip(f"chromium unavailable ({exc}); run: playwright install chromium")
        yield b
        b.close()


@pytest.fixture()
def page(browser, ui_server):
    """A loaded page that FAILS THE TEST on any uncaught JS error.

    The collected-errors assertion is the whole point: B1/B2 were both silent
    in normal use (one swallowed by a bare catch, one in a click handler nobody
    checked), so an explicit "no pageerror" gate is what turns them into
    failures.
    """
    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(ui_server, wait_until="networkidle")
    pg.wait_for_timeout(500)
    pg.errors = errors  # type: ignore[attr-defined]
    yield pg
    pg.close()


def test_page_loads_without_js_errors(page) -> None:
    assert page.errors == [], f"uncaught JS errors on load: {page.errors}"
    assert page.title() == "argo-anywhere"


def test_theme_toggle_retints_both_terminals(page) -> None:
    """B1 regression: xterm.js 5.x dropped setOption(); the retint must use the
    `options` setter and must actually reach BOTH panels."""
    # Force the explicit light palette (not `auto`, which depends on the OS).
    page.evaluate("applyTheme('light')")
    page.wait_for_timeout(200)

    css_bg = page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--term-bg').trim()"
    )
    for panel in ("channelPanel", "utilityPanel"):
        term_bg = page.evaluate(f"{panel}.term.options.theme.background")
        assert term_bg.lower() == css_bg.lower(), (
            f"{panel} did not retint: xterm says {term_bg}, CSS says {css_bg}"
        )

    page.evaluate("applyTheme('dark')")
    page.wait_for_timeout(200)
    css_bg_dark = page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--term-bg').trim()"
    )
    assert css_bg_dark.lower() != css_bg.lower(), "palette did not actually change"
    for panel in ("channelPanel", "utilityPanel"):
        term_bg = page.evaluate(f"{panel}.term.options.theme.background")
        assert term_bg.lower() == css_bg_dark.lower()

    assert page.errors == [], f"theme toggle raised: {page.errors}"


def test_setoption_is_not_used_anywhere(page) -> None:
    """Belt-and-braces for B1: the removed API must not creep back in."""
    assert page.evaluate("typeof channelPanel.term.setOption") == "undefined", (
        "vendored xterm.js unexpectedly exposes setOption -- if the build was "
        "downgraded to 4.x, revisit the retint implementation"
    )


def test_disconnect_handler_does_not_throw(page) -> None:
    """B2 regression: the handler referenced a deleted `term` global."""
    assert page.evaluate("typeof term") == "undefined", (
        "a global `term` exists again; the D-031 dual-panel model expects "
        "channelPanel / utilityPanel instead"
    )
    page.click("#toggleTerm")  # reveal the terminal container
    page.wait_for_timeout(200)
    page.click("#disconnectBtn")
    page.wait_for_timeout(200)
    # With nothing running the confirm button is disabled by design, so invoke
    # the handler the way a user with a live session would.
    page.evaluate("el('doDisconnect').removeAttribute('disabled')")
    page.click("#doDisconnect")
    page.wait_for_timeout(400)
    assert page.errors == [], f"Disconnect raised: {page.errors}"


def test_divider_position_is_restored_from_state(browser, ui_server) -> None:
    """B3 regression: a persisted divider_pct must survive boot.

    This test must reproduce the *boot-order race*, not just the event
    plumbing. The bug was that ``initDivider()`` ran ``applyPct(50)``
    unconditionally at parse time while the restore arrived later from
    ``/api/state`` -- so asserting on an event dispatched after page load would
    pass against the broken code. Instead we stub ``/api/state`` to return a
    non-default value BEFORE the page loads, exercising the real path:
    ``loadState() -> _applyPersistedDivider -> argo:setDividerPct``.
    """
    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.route(
        "**/api/state",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"version":1,"mru":[],"divider_pct":70,"theme":"auto"}',
        ),
    )
    pg.goto(ui_server, wait_until="networkidle")
    pg.wait_for_timeout(700)
    flex = pg.evaluate("el('panel-channel').style.flex")
    pg.close()
    assert "70%" in flex, (
        f"persisted divider_pct was not restored on boot (got {flex!r}); "
        "a hardcoded applyPct(50) is probably winning the race again"
    )
    assert errors == [], f"boot raised: {errors}"


def test_channel_state_is_the_largest_text_on_the_page(page) -> None:
    """Hierarchy guard (2026-08-09).

    The page answers one question -- "is my channel up?" -- and that answer
    used to render at 10.5px (the smallest type in the system) while the brand
    rendered at 13px. This pins the inversion as fixed: the state element must
    be strictly larger than the brand, and nothing may out-size it.
    """
    sizes = page.evaluate(
        """() => {
          const px = s => parseFloat(getComputedStyle(document.querySelector(s)).fontSize);
          const max = Math.max(...[...document.querySelectorAll('body *')]
            .filter(e => e.offsetParent && [...e.childNodes].some(
              n => n.nodeType === 3 && n.textContent.trim()))
            .map(e => parseFloat(getComputedStyle(e).fontSize)));
          return {state: px('#chState'), brand: px('.brand'), max};
        }"""
    )
    assert sizes["state"] > sizes["brand"], (
        f"channel state ({sizes['state']}px) is not larger than the brand "
        f"({sizes['brand']}px) -- the hierarchy inversion is back"
    )
    assert sizes["state"] >= sizes["max"], (
        f"something out-sizes the channel state ({sizes['state']}px "
        f"vs largest {sizes['max']}px)"
    )


def test_only_one_primary_button_is_visible(page) -> None:
    """CTA-weighting guard: at most one .btn-primary on screen at a time.

    Checked in the baseline state AND with each dialog open. The dialog cases
    matter because a modal renders *over* the channel card without hiding it:
    About's Close button was primary, so opening About while the channel was
    down put two primaries on screen at once (found 2026-08-09 -- the
    baseline-only version of this test missed it).
    """

    def visible_primaries() -> list[str]:
        return page.evaluate(
            "[...document.querySelectorAll('.btn-primary')]"
            ".filter(e => e.offsetParent !== null).map(e => e.textContent.trim())"
        )

    baseline = visible_primaries()
    assert len(baseline) <= 1, f"{baseline} competing primaries at baseline"

    # With a modal open, only the modal may own a primary. Content behind the
    # backdrop is inert (not clickable), so it must not keep primary weight and
    # pull the eye away from the dialog's actual action.
    for opener, closer in (("#openAbout", "#closeAbout"), ("#openLaunch", "#cancelLaunch")):
        page.click(opener)
        page.wait_for_timeout(200)
        # Assert on RENDERED weight, not the class list: the demotion is done
        # in CSS (body.modal-open), so .btn-primary legitimately remains in the
        # class attribute while the button no longer *looks* primary.
        styled_primary = page.evaluate(
            "[...document.querySelectorAll('.btn-primary')]"
            ".filter(e => e.offsetParent !== null)"
            ".filter(e => { const bg = getComputedStyle(e).backgroundColor;"
            "  return bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent'; })"
            ".map(e => ({t: e.textContent.trim(),"
            "            inModal: !!e.closest('.backdrop')}))"
        )
        page.click(closer)
        page.wait_for_timeout(150)
        assert len(styled_primary) <= 1, (
            f"{styled_primary} render as primary with {opener} open"
        )
        assert all(x["inModal"] for x in styled_primary), (
            f"{styled_primary} -- a button behind the {opener} backdrop still "
            "renders as primary; backdrop content is inert and must not "
            "compete with the dialog's action"
        )


def test_signal_path_claims_nothing_while_disconnected(browser, ui_server) -> None:
    """Honesty guard for the signal path (2026-08-09).

    The diagram depicts the CHANNEL. With no channel, the laptop hop used to
    render green AND pulsing (``class="hop up"`` was hardcoded in the markup),
    the first wire's origin was hardcoded green, and the cached port rendered
    in the accent colour -- three separate claims of a live link that did not
    exist. ``pulse`` is the design's vocabulary for "live"; spending it on a
    dormant hop is the part that actively misleads.
    """
    pg = browser.new_page(viewport={"width": 1440, "height": 800})
    pg.route(
        "**/api/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"package":{"package_version":"0","engine_version":"0",'
                '"app_cwd_short":"~"},'
                '"cached":{"user":"u","node":"compute-01.example.org","port":64742},'
                '"listeners":[],"sessions":[]}'
            ),
        ),
    )
    pg.goto(ui_server, wait_until="networkidle")
    pg.wait_for_timeout(900)
    state = pg.evaluate(
        """() => {
          const cs = s => getComputedStyle(document.querySelector(s));
          return {
            laptop: document.querySelector('#hopLaptop').className,
            laptopAnim: cs('#hopLaptop .hopdot').animationName,
            wireFrom: cs('#wireTunnel').getPropertyValue('--from').trim(),
            portIdle: document.querySelector('#portLabel').classList.contains('idle'),
          };
        }"""
    )
    pg.close()
    assert "up" not in state["laptop"].split(), (
        f"laptop hop is 'up' with no channel: {state['laptop']!r}"
    )
    assert state["laptopAnim"] in ("none", ""), (
        "laptop dot is pulsing with no channel -- pulse means 'live traffic'"
    )
    assert "--up" not in state["wireFrom"] and state["wireFrom"] != "#46c76a", (
        f"tunnel wire origin still reads as up: {state['wireFrom']}"
    )
    assert state["portIdle"], "cached port not dimmed while the channel is down"


def test_unattributable_tunnel_is_not_rendered_as_a_named_node(
    browser, ui_server
) -> None:
    """Web-UI Defect 3 (2026-08-12): the dashboard's version of the overclaim.

    Set up exactly the incident shape: something IS listening on the cached
    port, but its destination cannot be established (``verified_node: null``),
    while the cache still remembers ``compute-01``. The old code lit the node
    hop green and rendered ``localhost:64742 -> compute-01`` -- a verified
    topology asserted from an lsof hit plus a memory. On a shared node that
    listener may be a co-tenant's argo-proxy, which is how the 2026-08-10
    incident produced ALL GREEN while traffic left under a stranger's identity.

    The UI must now decline to name a node it cannot confirm.
    """
    pg = browser.new_page(viewport={"width": 1440, "height": 800})
    pg.route(
        "**/api/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"package":{"package_version":"0","engine_version":"0",'
                '"app_cwd_short":"~"},'
                '"cached":{"user":"u","node":"compute-01.example.org","port":64742},'
                '"listeners":[{"port":64742,"pid":4242,"command":"python3"}],'
                '"sessions":[],"verified_node":null,'
                # A listener we cannot attribute is NOT a discovered channel:
                # discovery requires an ssh process whose ControlPath names one
                # of our sockets. It is still in `listeners`, so the UI must
                # decide what to say about it.
                '"discovered":[]}'
            ),
        ),
    )
    pg.goto(ui_server, wait_until="networkidle")
    pg.wait_for_timeout(900)
    state = pg.evaluate(
        """() => ({
          nodeHop: document.querySelector('#hopNode').className,
          nodeSub: document.querySelector('#nodeSub').textContent.trim(),
          addr: document.querySelector('#chAddr').textContent.trim(),
          meta: document.querySelector('#channelMeta').textContent.trim(),
        })"""
    )
    pg.close()

    assert "up" not in state["nodeHop"].split(), (
        f"node hop is 'up' for an unattributable tunnel: {state['nodeHop']!r}"
    )
    assert "compute-01" not in state["nodeSub"], (
        f"node hop names the CACHED host as if verified: {state['nodeSub']!r}"
    )
    assert "compute-01" not in state["addr"], (
        "the channel address asserts a destination we could not confirm: "
        f"{state['addr']!r}"
    )
    assert "unverified" in state["addr"].lower(), (
        f"the unverified far end must be stated, not omitted: {state['addr']!r}"
    )
    # The cached value may still appear in the detail line, but only labelled
    # as cached -- "last known", never presented as the current destination.
    if "compute-01" in state["meta"]:
        assert "cached" in state["meta"].lower(), (
            f"cached node shown without the 'cached' qualifier: {state['meta']!r}"
        )


def test_health_200_does_not_light_the_proxy_hop_when_unverified(
    browser, ui_server
) -> None:
    """The same overclaim, one hop to the right.

    Found by looking at a screenshot of the fix rather than at its tests: the
    node hop correctly read 'unverified' while the argo-proxy hop beside it was
    green with a latency figure. A ``/health`` 200 proves *something* serves the
    far end of the port -- a co-tenant's argo-proxy answers identically, since
    it is the same software. Green there while the node reads unverified is
    internally inconsistent, and the green is the part users believe.
    """
    pg = browser.new_page(viewport={"width": 1440, "height": 800})
    pg.route(
        "**/api/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"package":{"package_version":"0","engine_version":"0",'
                '"app_cwd_short":"~"},'
                '"cached":{"user":"u","node":"compute-01.example.org","port":64742},'
                '"listeners":[{"port":64742,"pid":4242,"command":"python3"}],'
                '"sessions":[],"verified_node":null,"discovered":[]}'
            ),
        ),
    )
    pg.route(
        "**/api/health**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"port":64742,"up":true,"status":"healthy","latency_ms":12}',
        ),
    )
    pg.goto(ui_server, wait_until="networkidle")
    pg.wait_for_timeout(600)
    pg.click("#checkHealth")
    pg.wait_for_timeout(1200)
    state = pg.evaluate(
        """() => ({
          proxyHop: document.querySelector('#hopProxy').className,
          proxySub: document.querySelector('#proxySub').textContent.trim(),
          note: document.querySelector('#healthNote').textContent.trim(),
        })"""
    )
    pg.close()

    assert "up" not in state["proxyHop"].split(), (
        "argo-proxy hop is green off a /health 200 while the far end is "
        f"unverified: {state['proxyHop']!r}"
    )
    assert "unverified" in (state["proxySub"] + state["note"]).lower(), (
        f"the unverified far end is not stated: {state['proxySub']!r} / "
        f"{state['note']!r}"
    )


def test_health_200_lights_the_proxy_hop_when_verified(browser, ui_server) -> None:
    """The positive case must keep working -- this is the common path."""
    pg = browser.new_page(viewport={"width": 1440, "height": 800})
    pg.route(
        "**/api/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"package":{"package_version":"0","engine_version":"0",'
                '"app_cwd_short":"~"},'
                '"cached":{"user":"u","node":"compute-01.example.org","port":64742},'
                '"listeners":[{"port":64742,"pid":4242,"command":"ssh"}],'
                '"sessions":[],"verified_node":"compute-01.example.org",'
                '"discovered":[{"port":64742,"pid":4242,'
                '"node":"compute-01.example.org"}]}'
            ),
        ),
    )
    pg.route(
        "**/api/health**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"port":64742,"up":true,"status":"healthy","latency_ms":12}',
        ),
    )
    pg.goto(ui_server, wait_until="networkidle")
    pg.wait_for_timeout(600)
    pg.click("#checkHealth")
    pg.wait_for_timeout(1200)
    state = pg.evaluate(
        """() => ({
          proxyHop: document.querySelector('#hopProxy').className,
          proxySub: document.querySelector('#proxySub').textContent.trim(),
        })"""
    )
    pg.close()
    assert "up" in state["proxyHop"].split()
    assert "unverified" not in state["proxySub"].lower()
    assert "ms" in state["proxySub"]


def test_verified_tunnel_is_named_from_the_probe_not_the_cache(
    browser, ui_server
) -> None:
    """The positive case: a confirmed destination is named, and it is the
    VERIFIED one -- so a stale cache disagreeing with reality cannot win.
    """
    pg = browser.new_page(viewport={"width": 1440, "height": 800})
    pg.route(
        "**/api/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"package":{"package_version":"0","engine_version":"0",'
                '"app_cwd_short":"~"},'
                '"cached":{"user":"u","node":"stale-cache.example.org","port":64742},'
                '"listeners":[{"port":64742,"pid":4242,"command":"ssh"}],'
                '"sessions":[],"verified_node":"compute-07.cels.anl.gov",'
                '"discovered":[{"port":64742,"pid":4242,'
                '"node":"compute-07.cels.anl.gov"}]}'
            ),
        ),
    )
    pg.goto(ui_server, wait_until="networkidle")
    pg.wait_for_timeout(900)
    state = pg.evaluate(
        """() => ({
          nodeHop: document.querySelector('#hopNode').className,
          nodeSub: document.querySelector('#nodeSub').textContent.trim(),
          addr: document.querySelector('#chAddr').textContent.trim(),
        })"""
    )
    pg.close()

    assert "up" in state["nodeHop"].split(), "a verified node hop should be up"
    assert state["nodeSub"] == "compute-07", (
        f"node hop should name the verified host; got {state['nodeSub']!r}"
    )
    assert "compute-07" in state["addr"]
    assert "stale-cache" not in state["addr"], (
        "the stale cached name must never outrank the verified destination"
    )


_CONTRAST_JS = """
(sel) => {
  // Parse 'rgb(r,g,b)' / 'rgba(r,g,b,a)' -> [r,g,b,a].
  const parse = c => {
    const n = (c.match(/[\\d.]+/g) || []).map(Number);
    return [n[0] || 0, n[1] || 0, n[2] || 0, n.length > 3 ? n[3] : 1];
  };
  const lum = ([r, g, b]) => {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  // Composite src OVER dst (both [r,g,b,a]); returns an opaque colour.
  const over = (src, dst) => {
    const a = src[3];
    return [0, 1, 2].map(i => src[i] * a + dst[i] * (1 - a)).concat([1]);
  };
  // Resolve the EFFECTIVE background by compositing every translucent layer
  // down to the first opaque ancestor.
  //
  // The first version stopped at the first background that was not exactly
  // 'rgba(0, 0, 0, 0)' and treated it as opaque. A translucent tint --
  // .btn-soft uses `--link-soft`, which is the link colour at 10% alpha --
  // was therefore compared against ITSELF, giving ratio 1 and failing a
  // button that is perfectly legible. The test measured its own arithmetic,
  // not the page.
  const effBg = el => {
    const layers = [];
    let p = el;
    while (p) {
      const c = parse(getComputedStyle(p).backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] === 1) break;
      p = p.parentElement;
    }
    let acc = layers.length ? layers[layers.length - 1] : [255, 255, 255, 1];
    for (let i = layers.length - 2; i >= 0; i--) acc = over(layers[i], acc);
    return acc;
  };
  return [...document.querySelectorAll(sel)]
    .filter(e => e.offsetParent !== null && e.textContent.trim())
    .map(e => {
      const s = getComputedStyle(e);
      const bg = effBg(e);
      const fg = over(parse(s.color), bg);   // text can be translucent too
      const a = lum(fg), c = lum(bg);
      const hi = Math.max(a, c), lo = Math.min(a, c);
      return {text: e.textContent.trim().slice(0, 30),
              ratio: +(((hi + 0.05) / (lo + 0.05)).toFixed(2))};
    });
}
"""


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_text_meets_wcag_aa_in_both_themes(browser, ui_server, theme: str) -> None:
    """Contrast guard for BOTH palettes.

    Written because the manual audit that produced these fixes kept finding
    one more failure: the light palette's button text (3.29), then light
    --ink-faint (3.12), then dark --ink-faint (3.02), then the dark provider
    badges (3.78 / 4.13), then the light status badges (3.94 / 4.34). Each was
    missed by a review that only looked at the surfaces it had thought of.
    This measures every rendered text node instead.
    """
    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    pg.route(
        "**/api/models",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"models":[{"id":"a","internal_name":"a","provider":"openai",'
                '"modalities":"text->text","in_opencode_config":true},'
                '{"id":"b","internal_name":"b","provider":"claude",'
                '"modalities":"text->text","is_orphan":true},'
                '{"id":"c","internal_name":"c","provider":"gemini",'
                '"modalities":"text->text"}],'
                '"opencode_config_present":true,'
                '"counts":{"total":3,"in_config":1,"orphan":1},"note":"n"}'
            ),
        ),
    )
    pg.goto(ui_server, wait_until="networkidle")
    pg.wait_for_timeout(600)
    pg.evaluate(f"applyTheme('{theme}')")
    pg.wait_for_timeout(200)
    pg.click("#loadModels")
    pg.wait_for_timeout(700)

    # Buttons, badges and small labels -- the surfaces where tinted text on a
    # tinted ground actually risks falling under AA. `.empty`, `.models-note`
    # and `.row` are included because --ink-faint / --ink-dim render on THREE
    # different grounds (--panel, --panel-raised, --bg) and a value can clear
    # one while failing another: the light palette's --ink-faint passed on
    # panel at 4.83 and failed on raised at 4.31.
    results = pg.evaluate(
        _CONTRAST_JS,
        ".m-badge, .btn, .eyebrow, .subhead, .chip, .empty, .models-note,"
        " .row, .pop-note, .act-note, .channel-addr, .hopsub",
    )
    pg.close()

    assert results, "no elements measured -- selector or fixture is wrong"
    failures = [r for r in results if r["ratio"] < 4.5]
    assert not failures, f"[{theme}] below WCAG AA (4.5:1): {failures}"


def test_launcher_opens_and_closes(page) -> None:
    page.click("#openLaunch")
    page.wait_for_timeout(200)
    assert not page.locator("#launchBackdrop").get_attribute("hidden")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert page.locator("#launchBackdrop").get_attribute("hidden") is not None
    assert page.errors == [], f"launcher raised: {page.errors}"


def test_topbar_buttons_stay_on_screen_at_mobile_width(browser, ui_server) -> None:
    """Item 2 regression: below ~720px the topbar used to overflow, putting
    every action button past the right viewport edge and out of reach."""
    pg = browser.new_page(viewport={"width": 420, "height": 800})
    pg.goto(ui_server, wait_until="networkidle")
    pg.wait_for_timeout(400)
    offscreen = pg.evaluate(
        "[...document.querySelectorAll('.topbar button')]"
        ".filter(e => e.getBoundingClientRect().right >"
        " document.documentElement.clientWidth + 1).length"
    )
    overflow = pg.evaluate(
        "document.documentElement.scrollWidth >"
        " document.documentElement.clientWidth + 1"
    )
    pg.close()
    assert offscreen == 0, f"{offscreen} topbar button(s) off-screen at 420px"
    assert not overflow, "page scrolls horizontally at 420px"


def test_stale_cache_does_not_hide_a_live_channel(browser, ui_server) -> None:
    """The 2026-08-12 field incident, driven through the real page.

    A healthy tunnel on :64743; the cache still names :64742 from an aborted
    run. The dashboard used to report "not connected" -- because it asked "is
    something on the cached port?" -- while a working session ran in the
    embedded terminal beside it. The user chased the contradiction, reconnected
    repeatedly, and lost the channel.

    Connected-ness must come from what exists, and the stale cache must be
    called out rather than silently papered over: the client configs may still
    point at the dead port, which is what turns "connected but nothing works"
    into a support thread.
    """
    pg = browser.new_page(viewport={"width": 1440, "height": 800})
    pg.route(
        "**/api/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"package":{"package_version":"0","engine_version":"0",'
                '"app_cwd_short":"~"},'
                '"cached":{"user":"u","node":"compute-01.example.org","port":64742},'
                '"listeners":[{"port":64743,"pid":53133,"command":"ssh"}],'
                '"sessions":[],"verified_node":null,'
                '"discovered":[{"port":64743,"pid":53133,'
                '"node":"compute-01.example.org"}]}'
            ),
        ),
    )
    pg.goto(ui_server, wait_until="networkidle")
    pg.wait_for_timeout(900)
    state = pg.evaluate(
        """() => ({
          chState: document.querySelector('#chState').textContent.trim(),
          addr: document.querySelector('#chAddr').textContent.trim(),
          nodeHop: document.querySelector('#hopNode').className,
          meta: document.querySelector('#channelMeta').textContent.trim(),
          tunnels: document.querySelector('#listeners').textContent.trim(),
        })"""
    )
    pg.close()

    assert state["chState"] == "connected", (
        f"a live channel was reported as {state['chState']!r} because the cache "
        "named a different port"
    )
    assert "64743" in state["addr"], (
        f"the address must show the port actually forwarding; got {state['addr']!r}"
    )
    assert "64742" not in state["addr"], "the dead cached port must not be shown as live"
    assert "up" in state["nodeHop"].split(), "verified destination should light the hop"
    assert "stale" in state["meta"].lower(), (
        f"a stale cache must be surfaced, not hidden; got {state['meta']!r}"
    )
    assert "64743" in state["tunnels"], (
        f"the live tunnel must appear in the Tunnels panel; got {state['tunnels']!r}"
    )
