from unittest.mock import patch

from toolbox import browser_scrape

MB = 1024 * 1024


def _allowed(headroom):
    with patch.dict("os.environ", {"FANTASY_SCRAPER_BROWSER": "1"}), \
         patch.object(browser_scrape, "offline_mode", return_value=False), \
         patch.object(browser_scrape, "memory_headroom_bytes", return_value=headroom):
        return browser_scrape._browser_allowed()


def test_sin_limite_legible_se_permite():
    assert _allowed(None) is True


def test_hueco_suficiente_se_permite():
    assert _allowed(1500 * MB) is True


def test_poco_hueco_no_abre_chromium():
    assert _allowed(250 * MB) is False


def test_render_with_browser_devuelve_none_sin_memoria():
    with patch.dict("os.environ", {"FANTASY_SCRAPER_BROWSER": "1"}), \
         patch.object(browser_scrape, "offline_mode", return_value=False), \
         patch.object(browser_scrape, "memory_headroom_bytes", return_value=100 * MB):
        assert browser_scrape.render_with_browser("https://example.com") is None
        assert browser_scrape.fetch_json_with_browser("https://example.com") == (None, None)


def test_en_render_sin_limite_legible_no_abre_chromium():
    with patch.dict("os.environ", {"FANTASY_SCRAPER_BROWSER": "1", "RENDER": "true"}), \
         patch.object(browser_scrape, "offline_mode", return_value=False), \
         patch.object(browser_scrape, "memory_headroom_bytes", return_value=None):
        assert browser_scrape._browser_allowed() is False


def test_memory_status_devuelve_las_tres_claves():
    status = browser_scrape.memory_status()
    assert set(status) == {"rss_mb", "container_mb", "limit_mb"}
