"""Site-level tests: calendar honesty, editions, dates, duplicates. Run: python -m unittest discover tests"""
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

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Bank holds rate</title><link href="https://example.org/a"/><updated>2026-11-16T10:00:00Z</updated></entry>
<entry><title>Exchange lists firm</title><link href="https://example.org/b"/><published>2026-11-15T08:00:00Z</published><updated>2026-11-16T09:00:00Z</updated></entry>
</feed>"""


class Dates(unittest.TestCase):
    def test_updated_never_becomes_published(self):
        a, b = collect.parse_feed(ATOM)
        self.assertIsNone(a["published"])          # only an update time: publication unknown
        self.assertIsNotNone(a["updated"])
        self.assertEqual(b["published"].day, 15)   # real publication kept apart from update
        self.assertEqual(b["updated"].day, 16)

    def test_nine_categories_and_four_regions(self):
        self.assertEqual(len(collect.CATEGORIES), 9)
        for r in ("Asia Pacific", "Europe", "Americas", "Middle East & Africa"):
            self.assertIn(r, collect.REGIONS)

    def test_classify_ipo_and_crypto(self):
        src = {"default_category": "Economy", "region": "Global"}
        self.assertEqual(collect.classify("Firm files IPO prospectus in Hong Kong", "", src), ("IPOs & Listings", "Asia Pacific"))
        self.assertEqual(collect.classify("Stablecoin rules proposed", "", src)[0], "Blockchain & Digital Assets")


class Site(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        for f in ("config.json", "editorial.json", "sources.json"):
            shutil.copy(ROOT / f, self.t / f)
        shutil.copytree(ROOT / "assets", self.t / "assets")
        (self.t / "data").mkdir()

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def page(self, rel):
        return (self.t / "site" / rel).read_text("utf-8")

    def test_empty_site_is_honest_and_public(self):
        build.run(self.t)
        home = self.page("index.html")
        self.assertIn("No verified stories", home)
        self.assertNotIn("sources.json", home)
        self.assertNotIn("python run.py", home)
        self.assertIn("disabled", home)             # subscribe disabled until a service is connected

    def test_events_need_source_and_unknown_dates_are_tbc(self):
        (self.t / "events.json").write_text(json.dumps({"events": [
            {"title": "No source", "type": "ipo", "status": "expected", "date": "2027-01-01"},
            {"title": "Acme IPO", "type": "ipo", "status": "expected", "source_url": "https://exchange.example/acme",
             "exchange": "XYZ", "milestones": {"listing": {"date": "2027-02-02", "status": "expected"}}},
        ]}))
        build.run(self.t)
        cal = self.page("calendar/index.html")
        self.assertNotIn("No source", cal)
        self.assertIn("Acme IPO", cal)
        self.assertIn("TBC", cal)
        self.assertNotIn("badge confirmed", cal)    # an expected listing is never shown as confirmed

    def test_edition_needs_review_and_gets_own_url(self):
        d = self.t / "editions/published/daily"
        d.mkdir(parents=True)
        base = {"date": "2026-11-16", "title": "Daily Brief", "stories": [{"headline": "H", "context": "C", "sources": [{"publisher": "P", "url": "https://example.org/x"}]}]}
        (d / "2026-11-16.json").write_text(json.dumps(base))                      # unreviewed: not published
        build.run(self.t)
        self.assertFalse((self.t / "site/brief/2026-11-16/index.html").exists())
        base.update(reviewed_by="Editor", reviewed_on="2026-11-16")
        (d / "2026-11-16.json").write_text(json.dumps(base))
        build.run(self.t)
        self.assertIn("https://example.org/x", self.page("brief/2026-11-16/index.html"))

    def test_duplicate_coverage_grouped_not_confirmed(self):
        now = "2026-11-16T08:00:00Z"
        mk = lambda i, pub, title: {"id": i, "title": title, "url": f"https://{pub}.example/{i}", "publisher": pub, "source_id": pub,
                                    "published": now, "first_seen": now, "category": "Economy", "region": "Global", "summary": None}
        items = {"1": mk("1", "a", "Central bank cuts interest rate by quarter point"),
                 "2": mk("2", "b", "Central bank cuts interest rate by quarter point today")}
        (self.t / "data/items.json").write_text(json.dumps({"items": items}))
        build.run(self.t)
        self.assertIn("not independent confirmation", self.page("index.html"))


if __name__ == "__main__":
    unittest.main()
