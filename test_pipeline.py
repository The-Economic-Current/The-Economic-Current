"""Offline end-to-end test: fixture feed -> collect -> store -> build site.
Run from the project root:  python -m unittest discover tests
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["ECC_ALLOW_FILE"] = "1"

import build  # noqa: E402
import collect  # noqa: E402


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "config.json", self.tmp / "config.json")
        shutil.copy(ROOT / "editorial.json", self.tmp / "editorial.json")
        shutil.copytree(ROOT / "assets", self.tmp / "assets")
        feed = (ROOT / "tests/fixtures/sample_feed.xml").resolve().as_uri()
        self.write_sources(feed, enabled=True, reviewed="2026-11-12")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_sources(self, feed, enabled, reviewed, reuse="reviewed-ok"):
        (self.tmp / "sources.json").write_text(json.dumps({"sources": [{
            "id": "fixture", "publisher": "Fixture Publisher", "feed_url": feed,
            "coverage": "test", "default_category": "Global Economy", "region": "Global",
            "reuse": reuse, "enabled": enabled, "terms_reviewed": reviewed}]}))

    def items(self):
        return json.loads((self.tmp / "data/items.json").read_text())["items"]

    def test_collect_store_and_dedupe(self):
        self.assertEqual(collect.run(self.tmp), (1, 0))
        first = self.items()
        self.assertEqual(len(first), 3)
        collect.run(self.tmp)
        self.assertEqual(len(self.items()), 3, "second run must not duplicate items")
        by_title = {i["title"]: i for i in first.values()}
        a1 = by_title["Test central bank holds policy rate steady"]
        self.assertEqual(a1["category"], "Economy")
        self.assertNotIn("utm_source", a1["url"])
        self.assertTrue(a1["summary"].startswith("Synthetic test text"))
        self.assertEqual(a1["published"], "2026-11-11T09:30:00Z")
        # headline repeated as description -> no invented summary
        self.assertIsNone(by_title["Test regulator announces enforcement action"]["summary"])
        self.assertIsNone(by_title["Item with no date in the feed"]["published"])
        self.assertEqual(by_title["Item with no date in the feed"]["region"], "Americas")

    def test_source_gate(self):
        feed = (ROOT / "tests/fixtures/sample_feed.xml").resolve().as_uri()
        self.write_sources(feed, enabled=True, reviewed=None)
        self.assertEqual(collect.run(self.tmp), (0, 0))
        self.write_sources(feed, enabled=True, reviewed="2026-11-12", reuse="blocked")
        self.assertEqual(collect.run(self.tmp), (0, 0))
        self.assertEqual(self.items(), {})

    def test_failure_keeps_old_items_and_shows_stale_status(self):
        collect.run(self.tmp)
        self.write_sources("file:///nonexistent/feed.xml", enabled=True, reviewed="2026-11-12")
        self.assertEqual(collect.run(self.tmp), (0, 1))
        self.assertEqual(len(self.items()), 3, "old items must survive a failed fetch")
        status = json.loads((self.tmp / "data/status.json").read_text())
        self.assertEqual(status["sources"]["fixture"]["consecutive_failures"], 1)
        self.assertTrue(status["sources"]["fixture"]["last_success"])

    def test_build_site(self):
        collect.run(self.tmp)
        build.run(self.tmp)
        site = self.tmp / "site"
        index = (site / "index.html").read_text()
        self.assertIn("Fixture Publisher", index)
        self.assertIn("Summary unavailable", index)
        self.assertIn("Publisher excerpt", index)
        self.assertIn("Last successful collection", index)
        self.assertNotIn("undefined", index)
        for page in ("archive", "about", "brief", "weekly", "monthly"):
            self.assertTrue((site / page / "index.html").exists(), page)
        archive = json.loads((site / "data/archive.json").read_text())
        self.assertEqual(len(archive), 3)

    def test_empty_site_is_honest(self):
        (self.tmp / "sources.json").write_text(json.dumps({"sources": []}))
        build.run(self.tmp)
        index = (self.tmp / "site/index.html").read_text()
        self.assertIn("No sources are switched on yet", index)

    def test_clustering_marks_repeats(self):
        mk = lambda i, pub, title: {"id": i, "title": title, "publisher": pub, "published": "2026-11-11T10:00:00Z", "first_seen": "2026-11-11T10:05:00Z"}
        a = mk("1", "A", "Central bank cuts rates by quarter point amid slowing growth")
        b = mk("2", "B", "Central bank cuts rates by quarter point as growth slows")
        c = mk("3", "C", "Oil prices climb after OPEC output decision")
        groups = sorted(build.cluster([a, b, c]), key=len, reverse=True)
        self.assertEqual(len(groups[0]), 2)
        self.assertEqual(len(groups[1]), 1)


if __name__ == "__main__":
    unittest.main()
