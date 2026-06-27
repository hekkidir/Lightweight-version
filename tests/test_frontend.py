"""
Frontend smoke test — loads the REAL dashboard in headless Chromium, runs the
JS against a true DOM, and fails on any JS error. This catches the class of bug
the Python tests can't see (runtime errors in the browser modules).

Requires Playwright:  pip install playwright && python -m playwright install chromium
The whole module skips cleanly if Playwright or its browser aren't installed,
so the core suite still runs without them.
"""
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT     = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


# Ports Chromium refuses to navigate to (ERR_UNSAFE_PORT).
_UNSAFE_PORTS = {1719, 1720, 1723, 2049, 3659, 4045, 5060, 5061,
                 6000, 6566, 6665, 6666, 6667, 6668, 6669, 6697, 10080}


def _free_port() -> int:
    port = 0
    for _ in range(30):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        if port >= 1024 and port not in _UNSAFE_PORTS:
            return port
    return port


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn

    from pipeline import indicators, rotation, sectors
    from pipeline.config import load
    from server.app import create_app

    cfg  = load(ROOT / "config.ini")
    data = tmp_path_factory.mktemp("data")
    shutil.copy(FIXTURES / "prices_sample.parquet", data / "prices.parquet")
    shutil.copy(FIXTURES / "robots_sample.json", data / "robots.json")
    indicators.run(cfg, data)
    sectors.run(cfg, data)
    rotation.run(cfg, data)

    port = _free_port()
    config = uvicorn.Config(create_app(data), host="127.0.0.1", port=port, log_level="error")
    srv = uvicorn.Server(config)
    srv.install_signal_handlers = lambda: None   # required off the main thread
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    srv.should_exit = True
    thread.join(timeout=5)


def test_dashboard_renders_without_js_errors(server):
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(server, wait_until="networkidle")
        page.wait_for_timeout(500)   # let renderAll() run

        sector_rows = page.locator(".sector-row").count()
        table_rows  = page.locator("#stock-tbody tr").count()

        # Stock detail modal: click a table row -> fetch + render chart/table, then close
        page.locator("#stock-tbody tr").first.click()
        page.wait_for_selector("#sm-chart", timeout=4000)
        sm_open = page.locator("#stock-modal.open").count()
        sm_table_rows = page.locator(".sm-table tbody tr").count()
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
        sm_closed = page.locator("#stock-modal.open").count()

        # selecting a sector should narrow the table (cross-frame link)
        page.locator(".sector-row").first.click()
        page.wait_for_timeout(200)
        filtered = page.locator("#stock-tbody tr").count()

        # RRG fullscreen open (button) + inspector panel renders + close (Escape)
        page.locator("#rrg-fullscreen-btn").click()
        page.wait_for_timeout(200)
        fs_open = page.locator("#rrg-modal.open").count()
        panel_quads  = page.locator("#rp-quads .rp-quad-row").count()
        panel_leader = page.locator("#rp-leader .rp-leader-row").count()
        page.locator("#rp-labels").check()        # toggle a display control (no error)
        page.wait_for_timeout(80)
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
        fs_closed = page.locator("#rrg-modal.open").count()

        # A-frame category chip activates and re-renders the list without error
        page.locator("#sector-cats .cat-chip", has_text="Strong").click()
        page.wait_for_timeout(150)
        cat_active = page.locator("#sector-cats .cat-chip.active", has_text="Strong").count()

        # Two-layer model: Tumunu Sec pins rows; the active category must survive.
        page.locator("#pin-all").click()
        page.wait_for_timeout(120)
        cat_after_pin = page.locator("#sector-cats .cat-chip.active", has_text="Strong").count()
        page.locator("#clear-pins").click()
        page.wait_for_timeout(120)
        pins_cleared = page.locator(".sector-row.selected").count()

        # Select-all over the full list (All view) actually pins rows; clear empties.
        page.locator("#sector-cats .cat-chip", has_text="All").click()
        page.wait_for_timeout(120)
        page.locator("#pin-all").click()
        page.wait_for_timeout(120)
        pinned_rows = page.locator(".sector-row.selected").count()
        page.locator("#clear-pins").click()
        page.wait_for_timeout(120)

        # A-frame sector search (narrows sidebar, no error)
        page.fill("#sector-search", "a")
        page.wait_for_timeout(120)
        sec_search_val = page.input_value("#sector-search")
        page.fill("#sector-search", "")

        # E-frame: open filter bar, toggle a stage chip, set a range, export CSV
        page.locator("#filters-toggle").click()
        page.wait_for_timeout(100)
        filt_open = page.locator("#stock-filters.open").count()
        page.locator("#stage-chips .stage-chip", has_text="2B").click()
        page.wait_for_timeout(100)
        stage_active = page.locator("#stage-chips .stage-chip.active", has_text="2B").count()
        page.fill("input[data-rng='rsi'][data-b='min']", "40")
        page.wait_for_timeout(100)
        page.locator("#csv-export").click()
        page.wait_for_timeout(100)

        # Active Filters bar shows removable chips; a chip × removes a filter
        af_visible = page.locator("#active-filters").is_visible()
        before_chips = page.locator("#active-filters .af-chip").count()
        page.locator("#active-filters .af-chip-x").first.click()
        page.wait_for_timeout(120)
        after_chips = page.locator("#active-filters .af-chip").count()

        # Robots view: toggle, cards render
        page.locator("#view-robots").click()
        page.wait_for_timeout(150)
        robots_visible = page.locator("#robots-view").is_visible()
        robot_cards = page.locator(".rb-card").count()

        # Robot tearsheet modal: click a card name -> panels render, then close
        page.locator(".rb-name[data-robot]").first.click()
        page.wait_for_selector("#rm-perf", timeout=3000)
        rm_open = page.locator("#robot-modal.open").count()
        rm_heatmap = page.locator("#robot-modal .rm-hm-cell").count()
        rm_trade_rows = page.locator("#rm-trades-wrap .rm-trade").count()
        rm_cand_chips = page.locator("#rm-trades-wrap .rm-cand-chip").count()
        rm_win_default = page.locator("#rm-winchips .rm-winchip.active", has_text="1 Yıl").count()
        page.locator("#rm-winchips .rm-winchip", has_text="Tümü").click()  # widen window, no error
        page.wait_for_timeout(80)
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
        rm_closed = page.locator("#robot-modal.open").count()

        # A ticker row in the robots view opens the stock modal
        page.locator("#robots-view .rb-table tbody tr[data-ticker]").first.click()
        page.wait_for_selector("#sm-chart", timeout=4000)
        rb_modal_open = page.locator("#stock-modal.open").count()
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)

        browser.close()

    assert not errors, f"JS errors on load: {errors}"
    assert sector_rows > 0, "no sector rows rendered"
    assert table_rows > 0, "no table rows rendered"
    assert sm_open == 1, "stock modal did not open on row click"
    assert sm_table_rows > 0, "stock modal 20-day table rendered no rows"
    assert sm_closed == 0, "stock modal did not close on Escape"
    assert filtered <= table_rows, "sector click did not filter the table"
    assert fs_open == 1, "RRG fullscreen did not open"
    assert panel_quads == 4, "quadrant legend did not render 4 rows"
    assert panel_leader > 0, "rotation leaderboard rendered no rows"
    assert fs_closed == 0, "RRG fullscreen did not close on Escape"
    assert cat_active == 1, "category chip did not activate"
    assert cat_after_pin == 1, "Tumunu Sec collapsed the active category"
    assert pins_cleared == 0, "Tumunu Temizle did not clear the pins"
    assert pinned_rows > 0, "Tumunu Sec pinned no rows in the full list"
    assert filt_open == 1, "filter bar did not open"
    assert stage_active == 1, "stage chip did not activate"
    assert sec_search_val == "a", "sector search did not accept input"
    assert af_visible, "active filters bar not visible with filters set"
    assert before_chips >= 1, "no active-filter chips rendered"
    assert after_chips < before_chips, "chip x did not remove a filter"
    assert robots_visible, "robots view did not show on toggle"
    from pipeline.robots import ROBOTS
    assert robot_cards == len(ROBOTS), f"expected {len(ROBOTS)} robot cards, got {robot_cards}"
    assert rm_open == 1, "robot tearsheet did not open"
    assert rm_heatmap > 0, "monthly heatmap rendered no cells"
    assert rm_trade_rows > 0, "trade tape rendered no rows"
    assert rm_cand_chips > 0, "trade rows show no entry-time candidates"
    assert rm_win_default == 1, "trade window did not default to 1 Yıl"
    assert rm_closed == 0, "robot tearsheet did not close on Escape"
    assert rb_modal_open == 1, "robot ticker row did not open the stock modal"
