"""
Phase separation regression tests.

Strict architectural rule:
  Phase 1 = filesystem + NFO only  (zero network calls)
  Phase 2 = ffprobe only           (zero network calls)
  Phase 3 = Seerr only             (network allowed here)
  Phase 4 = scoring only           (zero network calls)
  Phase 5 = recommendations only   (zero network calls)

These tests verify that _jsr_get (the low-level Seerr HTTP helper) is NEVER
called outside Phase 3.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, call

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db           # noqa: E402
import scanner      # noqa: E402
from repositories import media_repository  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tv_dir(root: pathlib.Path, folder: str, show: str, n_episodes: int = 2) -> pathlib.Path:
    """Create a minimal TV series directory with a tvshow.nfo."""
    series = root / folder / show
    series.mkdir(parents=True, exist_ok=True)
    s1 = series / "Season 01"
    s1.mkdir(exist_ok=True)
    for i in range(1, n_episodes + 1):
        (s1 / f"S01E{i:02d}.mkv").touch()
    nfo = series / "tvshow.nfo"
    nfo.write_text(
        '<?xml version="1.0"?><tvshow>'
        f'<title>{show}</title>'
        '<uniqueid type="tvdb">81189</uniqueid>'
        '</tvshow>',
        encoding="utf-8",
    )
    return series


def _make_movie_dir(root: pathlib.Path, folder: str, title: str) -> pathlib.Path:
    movie = root / folder / title
    movie.mkdir(parents=True, exist_ok=True)
    (movie / f"{title}.mkv").touch()
    nfo = movie / f"{title}.nfo"
    nfo.write_text(
        '<?xml version="1.0"?><movie>'
        f'<title>{title}</title>'
        '<uniqueid type="tmdb">603</uniqueid>'
        '</movie>',
        encoding="utf-8",
    )
    return movie


def _seerr_cfg(enabled: bool = True):
    return {"enabled": enabled, "url": "http://seerr.test", "apikey": "k"}


def _cfg_with_folders(root: pathlib.Path, folders: list[dict]) -> dict:
    return {
        "folders": folders,
        "enable_movies": True,
        "enable_series": True,
        "seerr": {"enabled": True, "url": "http://seerr.test"},
    }


# ---------------------------------------------------------------------------
# Phase 1 — no Seerr calls
# ---------------------------------------------------------------------------

class Phase1NoSeerrTest(unittest.TestCase):
    """Phase 1 (filesystem + NFO scan) must make zero calls to _jsr_get."""

    def _run_phase1(self, root, folders):
        cfg = _cfg_with_folders(root, folders)
        with tempfile.TemporaryDirectory() as dbdir:
            db_path = pathlib.Path(dbdir) / "mml.db"
            conn = db.initialize_database(db_path)
            conn.close()
            jsr_calls = []
            def spy_jsr_get(path, jsr=None):
                jsr_calls.append(path)
                return scanner._JSR_NOT_FOUND
            with patch.object(scanner, "LIBRARY_PATH", str(root)), \
                 patch.object(scanner, "load_config", return_value=cfg), \
                 patch.object(scanner, "save_config"), \
                 patch.object(scanner, "sync_folders", return_value=False), \
                 patch.object(scanner, "normalize_folder_enabled_flags", return_value=False), \
                 patch.object(scanner, "media_repository",
                              media_repository if True else None), \
                 patch.object(scanner, "OUTPUT_PATH", str(db_path) + ".json"), \
                 patch.object(scanner, "_jsr_get", side_effect=spy_jsr_get):
                scanner.run_quick()
            return jsr_calls

    def test_phase1_tv_no_seerr_calls(self):
        """Phase 1 with a TV series must make zero Seerr HTTP calls."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _make_tv_dir(root, "tv", "Breaking Bad", n_episodes=3)
            folders = [{"name": "tv", "type": "tv", "enabled": True}]
            calls = self._run_phase1(root, folders)
        self.assertEqual(calls, [],
                         f"Phase 1 must not call Seerr. Got calls: {calls}")

    def test_phase1_movie_no_seerr_calls(self):
        """Phase 1 with movies must make zero Seerr HTTP calls."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _make_movie_dir(root, "movies", "The Matrix")
            folders = [{"name": "movies", "type": "movie", "enabled": True}]
            calls = self._run_phase1(root, folders)
        self.assertEqual(calls, [],
                         f"Phase 1 must not call Seerr. Got calls: {calls}")

    def test_phase1_mixed_folders_no_seerr_calls(self):
        """Phase 1 with both TV and movie folders must make zero Seerr HTTP calls."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _make_tv_dir(root, "tv", "Show A")
            _make_tv_dir(root, "tv", "Show B")
            _make_movie_dir(root, "movies", "Film A")
            folders = [
                {"name": "tv", "type": "tv", "enabled": True},
                {"name": "movies", "type": "movie", "enabled": True},
            ]
            calls = self._run_phase1(root, folders)
        self.assertEqual(calls, [],
                         f"Phase 1 must not call Seerr. Got calls: {calls}")

    def test_scan_media_item_tv_no_seerr_without_jsr(self):
        """scan_media_item with jsr_for_counts=None (default) must not call _jsr_get."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            series = _make_tv_dir(root, "tv", "Test Show")
            cat = {"name": "Series", "type": "tv", "folder": "tv"}
            with patch.object(scanner, "_jsr_get") as mock_jsr:
                scanner.scan_media_item(series, root, cat, {}, enable_score=False)
            mock_jsr.assert_not_called()

    def test_scan_media_item_tv_calls_seerr_only_when_jsr_explicit(self):
        """scan_media_item with an explicit jsr_for_counts dict IS allowed to call Seerr.
        This ensures the parameter contract is preserved for tests that use it directly."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            series = _make_tv_dir(root, "tv", "Test Show")
            cat = {"name": "Series", "type": "tv", "folder": "tv"}
            jsr = _seerr_cfg(enabled=True)
            with patch.object(scanner, "_jsr_get", return_value=scanner._JSR_NOT_FOUND) as mock_jsr:
                scanner.scan_media_item(series, root, cat, {},
                                        enable_score=False, jsr_for_counts=jsr)
            # At least one /tv/ call should have been made
            tv_calls = [c.args[0] for c in mock_jsr.call_args_list if "/tv/" in c.args[0]]
            self.assertGreater(len(tv_calls), 0,
                               "With explicit jsr_for_counts, scan_media_item may call Seerr")


# ---------------------------------------------------------------------------
# Phase 2 — no Seerr calls (ffprobe only)
# ---------------------------------------------------------------------------

class Phase2NoSeerrTest(unittest.TestCase):
    """Phase 2 (ffprobe) must make zero Seerr calls."""

    def test_phase2_probe_no_seerr_calls(self):
        """run_probe must not call _jsr_get."""
        with patch.object(scanner, "_jsr_get") as mock_jsr, \
             patch.object(scanner, "load_config", return_value={}), \
             patch.object(scanner, "run_media_probe_pipeline_if_enabled",
                          return_value=None):
            scanner.run_probe()
        mock_jsr.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 4 — no Seerr calls (scoring only)
# ---------------------------------------------------------------------------

class Phase4NoSeerrTest(unittest.TestCase):
    """Phase 4 (scoring) must make zero Seerr calls."""

    def test_phase4_scoring_no_seerr_calls(self):
        """run_scoring must not call _jsr_get."""
        with patch.object(scanner, "_jsr_get") as mock_jsr, \
             patch.object(scanner, "load_library_document_non_blocking",
                          return_value={"items": [], "categories": []}), \
             patch.object(scanner, "load_config", return_value={}):
            scanner.run_scoring()
        mock_jsr.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 5 — no Seerr calls (recommendations only)
# ---------------------------------------------------------------------------

class Phase5NoSeerrTest(unittest.TestCase):
    """Phase 5 (recommendations) must make zero Seerr calls."""

    def test_phase5_recommendations_no_seerr_calls(self):
        """run_recommendations must not call _jsr_get."""
        with patch.object(scanner, "_jsr_get") as mock_jsr, \
             patch.object(scanner, "load_library_document_non_blocking",
                          return_value={"items": [], "categories": []}), \
             patch.object(scanner, "load_config", return_value={}):
            scanner.run_recommendations()
        mock_jsr.assert_not_called()


# ---------------------------------------------------------------------------
# run_phases — phase isolation across full pipeline
# ---------------------------------------------------------------------------

class RunPhasesIsolationTest(unittest.TestCase):
    """run_phases must only allow Seerr calls during Phase 3."""

    def _make_library(self, items=None):
        return {
            "scanned_at": "2026-01-01T00:00:00",
            "library_path": "/library",
            "total_items": len(items or []),
            "categories": [],
            "items": items or [],
        }

    def test_phases_1_2_4_5_no_seerr_calls(self):
        """Running phases 1,2,4,5 (all except Phase 3) must never call _jsr_get."""
        jsr_calls = []
        def spy(*a, **kw):
            jsr_calls.append(a)
            return scanner._JSR_NOT_FOUND

        with patch.object(scanner, "_jsr_get", side_effect=spy), \
             patch.object(scanner, "run_quick", return_value="0 items"), \
             patch.object(scanner, "run_probe", return_value=""), \
             patch.object(scanner, "run_scoring", return_value=""), \
             patch.object(scanner, "run_recommendations", return_value=""):
            scanner.run_phases([
                scanner.PHASE_SCAN,
                scanner.PHASE_PROBE,
                scanner.PHASE_SCORE,
                scanner.PHASE_RECOMMENDATIONS,
            ])

        self.assertEqual(jsr_calls, [],
                         f"Phases 1/2/4/5 must not call _jsr_get. Calls: {jsr_calls}")

    def test_phase3_only_calls_seerr(self):
        """Phase 3 in run_phases must call _jsr_get (verifies the mock is wired correctly)."""
        item = {
            "id": "m:F:Movie", "title": "Movie", "type": "movie", "category": "Films",
            "tmdb_id": "603",
            "providers": [], "providers_fetched": False,
            "seerr_status": None, "seerr_last_fetched_at": None,
        }
        jsr_calls = []
        def spy(path, jsr=None):
            jsr_calls.append(path)
            return {"watchProviders": {}}

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "library.json"
            out.write_text(json.dumps(self._make_library([item])), encoding="utf-8")
            with patch.object(scanner, "OUTPUT_PATH", str(out)), \
                 patch.object(scanner, "_jsr_cfg", return_value=_seerr_cfg()), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "_jsr_get", side_effect=spy), \
                 patch.object(scanner, "_resolve_ids_from_search",
                              return_value=scanner._JSR_NOT_FOUND):
                scanner.run_phases([scanner.PHASE_ENRICH])

        self.assertGreater(len(jsr_calls), 0,
                           "Phase 3 must call _jsr_get (Seerr is expected here)")


# ---------------------------------------------------------------------------
# Phase 1 — IDs preserved from NFO, no resolution via Seerr
# ---------------------------------------------------------------------------

class Phase1IdPreservationTest(unittest.TestCase):
    """Phase 1 must store IDs from NFO verbatim. No remote resolution."""

    def _run_phase1_get_item(self, root, folder_name, folder_type, media_dir):
        """Run scan_media_item directly with jsr_for_counts=None and return the item."""
        cat = {"name": folder_name, "type": folder_type, "folder": folder_name}
        with patch.object(scanner, "_jsr_get") as mock_jsr:
            item = scanner.scan_media_item(
                media_dir, root, cat, {}, enable_score=False
                # jsr_for_counts defaults to None
            )
        mock_jsr.assert_not_called()
        return item

    def test_tv_nfo_tvdb_id_stored_without_seerr(self):
        """TV show with tvdb_id in NFO: ID must be stored without any Seerr call."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            series = _make_tv_dir(root, "tv", "Breaking Bad")
            item = self._run_phase1_get_item(root, "tv", "tv", series)
        self.assertEqual(item.get("tvdb_id"), "81189")

    def test_movie_nfo_tmdb_id_stored_without_seerr(self):
        """Movie with tmdb_id in NFO: ID must be stored without any Seerr call."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            movie = _make_movie_dir(root, "movies", "The Matrix")
            item = self._run_phase1_get_item(root, "movies", "movie", movie)
        self.assertEqual(item.get("tmdb_id"), "603")

    def test_tv_nfo_ids_available_for_phase3(self):
        """IDs stored by Phase 1 must be usable by Phase 3 enrichment."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            series = _make_tv_dir(root, "tv", "Breaking Bad")
            cat = {"name": "Series", "type": "tv", "folder": "tv"}
            item = scanner.scan_media_item(series, root, cat, {}, enable_score=False)
        # Phase 3 needs tvdb_id or tmdb_id to enrich
        self.assertTrue(
            item.get("tvdb_id") or item.get("tmdb_id"),
            "Phase 1 must store at least one ID for Phase 3 to use",
        )
        # providers_fetched=False means Phase 3 will pick it up
        self.assertFalse(item.get("providers_fetched"))


if __name__ == "__main__":
    unittest.main()
