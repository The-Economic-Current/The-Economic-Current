#!/usr/bin/env python3
"""Collect news items from reviewed RSS/Atom sources into data/items.json.

Standard library only. Usage:
  python collect.py            collect from enabled, reviewed sources
  python collect.py --verify   test every source (even disabled), write nothing
  python collect.py --status   print registry merged with last-fetch status
"""
import hashlib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CATEGORIES = [
    "Global Economy",
    "Stocks & Corporate Earnings",
    "Central Banks & Interest Rates",
    "Forex & Bonds",
    "Commodities & Energy",
    "Trade & Economic Policy",
    "Exchanges, Trading & Regulation",
    "Digital Assets",
]
REGIONS = ["Global", "North America", "Europe", "Asia-Pacific", "Middle East & Africa", "Latin America"]

# Automated keyword tags. Order is the tie-break priority. These are labelled as automated on the site.
CAT_RULES = [
    ("Digital Assets", ["bitcoin", "crypto", "stablecoin", "ethereum", "digital asset", "blockchain", "token", "cbdc"]),
    ("Central Banks & Interest Rates", ["central bank", "interest rate", "rate cut", "rate hike", "monetary policy", "fomc", "federal reserve", "ecb", "bank of england", "bank of japan", "repo rate", "policy rate", "discount rate"]),
    ("Commodities & Energy", ["oil", "crude", "opec", "natural gas", "lng", "gold", "copper", "commodity", "commodities", "wheat", "brent", "energy prices"]),
    ("Forex & Bonds", ["currency", "forex", "exchange rate", "dollar", "euro", "yen", "yuan", "sterling", "bond", "bonds", "yield", "yields", "sovereign debt"]),
    ("Stocks & Corporate Earnings", ["earnings", "shares", "stock", "stocks", "equities", "profit", "quarterly results", "ipo", "dividend", "s&p 500", "nasdaq"]),
    ("Exchanges, Trading & Regulation", ["regulator", "regulation", "exchange", "trading", "listing", "clearing", "enforcement", "compliance", "market structure", "cftc", "esma", "fca", "sec"]),
    ("Trade & Economic Policy", ["tariff", "tariffs", "trade deal", "trade war", "sanctions", "export", "exports", "import", "imports", "wto", "subsidy", "budget", "fiscal", "tax"]),
    ("Global Economy", ["gdp", "inflation", "unemployment", "jobs", "economy", "recession", "growth", "cpi", "pmi", "imf", "world bank", "productivity", "labour", "labor"]),
]
REGION_RULES = [
    ("North America", ["u.s.", "united states", "american", "washington", "wall street", "federal reserve", "fomc", "canada", "canadian", "nasdaq", "nyse", "s&p 500"]),
    ("Europe", ["euro area", "eurozone", "european", "ecb", "germany", "german", "france", "french", "italy", "italian", "spain", "spanish", "britain", "u.k.", "uk", "bank of england", "london", "switzerland", "swiss"]),
    ("Asia-Pacific", ["china", "chinese", "japan", "japanese", "india", "indian", "australia", "australian", "korea", "singapore", "hong kong", "asean", "taiwan", "indonesia", "pboc", "bank of japan", "rbi"]),
    ("Middle East & Africa", ["saudi", "opec", "israel", "uae", "emirates", "nigeria", "south africa", "egypt", "africa", "african", "gulf", "iran", "turkey", "turkish"]),
    ("Latin America", ["brazil", "brazilian", "mexico", "mexican", "argentina", "chile", "colombia", "peru", "latin america"]),
]

MAX_BYTES = 3_000_000
LOG_LIMIT = 200
TRACKING = ("utm_", "fbclid", "gclid", "mc_", "ref")


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except FileNotFoundError:
        return default


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8")
    tmp.replace(path)


def user_agent():
    contact = os.environ.get("ECC_CONTACT", "").strip()
    return "TheEconomicCurrentBot/0.1" + (f" (+{contact})" if contact else "")


# ---------- parsing ----------

def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def child_text(el, names):
    for c in el:
        if local(c.tag) in names:
            t = "".join(c.itertext()).strip()
            if t:
                return t
    return None


def entry_link(el):
    for c in el:
        if local(c.tag) == "link":
            if c.get("href") and c.get("rel", "alternate") == "alternate":
                return c.get("href").strip()
            if (c.text or "").strip():
                return c.text.strip()
    return None


def parse_date(s):
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        dt = parse_iso(s)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_feed(data):
    root = ET.fromstring(data)
    out = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        title = child_text(el, ("title",))
        link = entry_link(el)
        if not title or not link:
            continue
        out.append({
            "title": strip_html(title),
            "link": link,
            "published": parse_date(child_text(el, ("pubDate", "published", "updated", "date"))),
            "raw_summary": child_text(el, ("description", "summary", "encoded", "content")),
        })
    return out


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def make_summary(raw, title, limit):
    """Publisher's own excerpt only. Returns None when the feed gives nothing beyond the headline."""
    text = strip_html(raw)
    if len(text) < 60:
        return None
    nt, ns = norm(title), norm(text)
    if ns == nt or (ns.startswith(nt) and len(ns) < len(nt) + 40):
        return None
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "\u2026"
    return text


def canonical_url(u):
    p = urlsplit(u.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith(TRACKING)]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, urlencode(q), ""))


def item_id(url):
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()[:16]


def _count(text, words):
    n = 0
    for w in words:
        if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", text):
            n += 1
    return n


def classify(title, summary, src):
    text = f"{title} {summary or ''}".lower()
    best, score = None, 0
    for cat, words in CAT_RULES:
        n = _count(text, words)
        if n > score:
            best, score = cat, n
    category = best or src.get("default_category") or "Global Economy"
    best, score = None, 0
    for reg, words in REGION_RULES:
        n = _count(text, words)
        if n > score:
            best, score = reg, n
    region = best or src.get("region") or "Global"
    return category, region


# ---------- fetching ----------

def fetch(url, timeout, etag=None, last_modified=None):
    scheme = urlsplit(url).scheme
    if scheme not in ("http", "https") and not (scheme == "file" and os.environ.get("ECC_ALLOW_FILE") == "1"):
        raise ValueError(f"unsupported URL scheme: {scheme}")
    headers = {
        "User-Agent": user_agent(),
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            data = r.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("feed larger than 3 MB limit")
            h = getattr(r, "headers", {}) or {}
            return 200, data, h.get("ETag"), h.get("Last-Modified")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, b"", etag, last_modified
        raise


def source_allowed(s):
    if not s.get("enabled"):
        return False, "disabled"
    if s.get("reuse") == "blocked":
        return False, "reuse blocked by registry"
    if not s.get("terms_reviewed"):
        return False, "terms_reviewed date missing"
    return True, ""


def log(status, source, level, msg):
    status.setdefault("log", []).append({"time": iso(now_utc()), "source": source, "level": level, "message": msg})
    status["log"] = status["log"][-LOG_LIMIT:]


def run(root):
    root = Path(root)
    cfg = load_json(root / "config.json", {})
    registry = load_json(root / "sources.json", {"sources": []})["sources"]
    store = load_json(root / "data/items.json", {"items": {}})
    items = store["items"]
    status = load_json(root / "data/status.json", {"sources": {}, "log": []})
    t0 = now_utc()
    limit = cfg.get("max_summary_chars", 300)
    timeout = cfg.get("request_timeout_seconds", 20)
    ok_count = fail_count = 0

    for s in registry:
        allowed, why = source_allowed(s)
        if not allowed:
            if s.get("enabled"):
                log(status, s["id"], "warn", f"skipped: {why}")
            continue
        st = status["sources"].setdefault(s["id"], {})
        st["last_attempt"] = iso(t0)
        try:
            code, data, etag, lm = fetch(s["feed_url"], timeout, st.get("etag"), st.get("last_modified"))
            new = 0
            if code == 200:
                for e in parse_feed(data):
                    iid = item_id(e["link"])
                    summary = make_summary(e["raw_summary"], e["title"], limit)
                    category, region = classify(e["title"], summary, s)
                    rec = {
                        "id": iid,
                        "title": e["title"],
                        "url": canonical_url(e["link"]),
                        "publisher": s["publisher"],
                        "source_id": s["id"],
                        "published": iso(e["published"]),
                        "category": category,
                        "region": region,
                        "summary": summary,
                    }
                    if iid not in items:
                        rec["first_seen"] = iso(t0)
                        new += 1
                    else:
                        rec["first_seen"] = items[iid].get("first_seen", iso(t0))
                    items[iid] = rec
            st.update(etag=etag, last_modified=lm, last_success=iso(t0), last_error=None,
                      consecutive_failures=0, new_items_last_fetch=new)
            log(status, s["id"], "info", f"ok: HTTP {code}, {new} new items")
            ok_count += 1
        except Exception as ex:  # keep going: one broken source must not stop the others
            st["last_error"] = f"{type(ex).__name__}: {ex}"[:300]
            st["consecutive_failures"] = st.get("consecutive_failures", 0) + 1
            log(status, s["id"], "error", st["last_error"])
            fail_count += 1

    cutoff = t0 - timedelta(days=cfg.get("retention_days", 365))
    for iid in [k for k, v in items.items() if (parse_iso(v.get("published")) or parse_iso(v.get("first_seen")) or t0) < cutoff]:
        del items[iid]

    store["updated"] = iso(t0)
    save_json(root / "data/items.json", store)
    save_json(root / "data/status.json", status)
    print(f"collect: {ok_count} sources ok, {fail_count} failed, {len(items)} items stored")
    return ok_count, fail_count


def verify(root):
    root = Path(root)
    cfg = load_json(root / "config.json", {})
    for s in load_json(root / "sources.json", {"sources": []})["sources"]:
        try:
            code, data, _, _ = fetch(s["feed_url"], cfg.get("request_timeout_seconds", 20))
            entries = parse_feed(data)
            dated = [e["published"] for e in entries if e["published"]]
            with_sum = sum(1 for e in entries if make_summary(e["raw_summary"], e["title"], 300))
            newest = iso(max(dated)) if dated else "none"
            print(f"OK   {s['id']:<16} {len(entries):>3} items, {with_sum} with usable excerpt, newest {newest}")
        except Exception as ex:
            print(f"FAIL {s['id']:<16} {type(ex).__name__}: {str(ex)[:100]}")
        print(f"       terms to read: {s.get('terms_url')}  ({s.get('reuse_notes')})")


def show_status(root):
    root = Path(root)
    status = load_json(root / "data/status.json", {"sources": {}})
    for s in load_json(root / "sources.json", {"sources": []})["sources"]:
        st = status["sources"].get(s["id"], {})
        print(f"{s['id']:<16} enabled={s.get('enabled')} reviewed={s.get('terms_reviewed')} "
              f"last_success={st.get('last_success')} error={st.get('last_error')}")


if __name__ == "__main__":
    here = Path(__file__).parent
    if "--verify" in sys.argv:
        verify(here)
    elif "--status" in sys.argv:
        show_status(here)
    else:
        run(here)
