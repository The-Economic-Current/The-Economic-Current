#!/usr/bin/env python3
"""Build the static site into site/ from data/items.json. Standard library only."""
import html
import json
import re
import shutil
from datetime import timedelta
from pathlib import Path

from collect import CATEGORIES, REGIONS, load_json, now_utc, parse_iso, save_json

esc = html.escape

NAV = [("Latest", ""), ("Daily Brief", "brief/"), ("Weekly Review", "weekly/"),
       ("Monthly Outlook", "monthly/"), ("Archive", "archive/"), ("About", "about/")]

STOP = set("the and for with from that this after over amid says say new its are was were has have will into as at by of to in on a an or is it".split())


def fmt_utc(iso_str, with_date=True):
    dt = parse_iso(iso_str)
    if not dt:
        return ""
    return dt.strftime("%d %b %Y, %H:%M UTC") if with_date else dt.strftime("%H:%M UTC")


def layout(cfg, title, body, depth, active, page_js=""):
    p = "../" * depth
    cur = ' aria-current="page"'
    nav = "".join(
        f'<a href="{p}{href}"{cur if name == active else ""}>{esc(name)}</a>'
        for name, href in NAV)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(cfg['tagline'])}">
<link rel="stylesheet" href="{p}assets/style.css">
</head>
<body>
<a class="skip" href="#main">Skip to stories</a>
<header class="masthead">
  <div class="wrap">
    <a class="brand" href="{p or './'}">
      <span class="brand-name">{esc(cfg['site_name'])}</span>
      <svg class="wave" viewBox="0 0 120 10" aria-hidden="true" focusable="false"><path d="M0 5 C10 0 20 0 30 5 S50 10 60 5 S80 0 90 5 S110 10 120 5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>
    </a>
    <p class="tagline">{esc(cfg['tagline'])}</p>
    <nav aria-label="Sections">{nav}</nav>
  </div>
</header>
<main id="main" class="wrap">
{body}
</main>
<footer class="wrap foot">
  <p>Headlines and excerpts belong to their publishers. We link to every original. Built {now_utc().strftime('%d %b %Y, %H:%M UTC')}.</p>
</footer>
<script src="{p}assets/app.js" defer></script>
{page_js}
</body>
</html>
"""


# ---------- data prep ----------

def tokens(title):
    return {w for w in re.findall(r"[a-z0-9$%.]+", title.lower()) if w not in STOP and len(w) > 2}


def cluster(items):
    """Group items that report the same event. Returns list of lists, earliest first in each."""
    recent = sorted(items, key=lambda i: i.get("published") or i["first_seen"])
    parent = list(range(len(recent)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    toks = [tokens(i["title"]) for i in recent]
    times = [parse_iso(i.get("published") or i["first_seen"]) for i in recent]
    for a in range(len(recent)):
        for b in range(a + 1, len(recent)):
            if times[b] - times[a] > timedelta(hours=72):
                break
            if recent[a]["publisher"] == recent[b]["publisher"]:
                continue
            common = toks[a] & toks[b]
            union = toks[a] | toks[b]
            if len(common) >= 3 and union and len(common) / len(union) >= 0.5:
                parent[find(b)] = find(a)
    groups = {}
    for idx, it in enumerate(recent):
        groups.setdefault(find(idx), []).append(it)
    return list(groups.values())


def source_health(registry, status, cfg, now):
    stale_h = cfg.get("stale_after_hours", 6)
    enabled = [s for s in registry if s.get("enabled") and s.get("terms_reviewed") and s.get("reuse") != "blocked"]
    last = None
    stale = []
    for s in enabled:
        ok = parse_iso(status["sources"].get(s["id"], {}).get("last_success"))
        if ok and (last is None or ok > last):
            last = ok
        if not ok or now - ok > timedelta(hours=stale_h):
            stale.append(s["publisher"])
    return enabled, last, stale


def status_block(enabled, last, stale, cfg):
    if not enabled:
        return ('<p class="status warn" role="status">No sources are switched on yet, so there are no stories to show. '
                'Nothing on this site is placeholder or simulated.</p>')
    if last is None:
        return '<p class="status warn" role="status">No collection has succeeded yet.</p>'
    txt = f'Last successful collection <time class="t full" datetime="{last.strftime("%Y-%m-%dT%H:%M:%SZ")}">{fmt_utc(last.strftime("%Y-%m-%dT%H:%M:%SZ"))}</time>. {len(enabled) - len(stale)} of {len(enabled)} sources are up to date.'
    if stale:
        txt += f' Not updated in over {cfg.get("stale_after_hours", 6)} hours: {esc(", ".join(stale))}. Stories from these sources may be out of date.'
        return f'<p class="status warn" role="status">{txt}</p>'
    return f'<p class="status" role="status">{txt}</p>'


def story_html(it, others, corrections):
    ts = it.get("published")
    when = (f'<time class="t" datetime="{ts}">{esc(fmt_utc(ts))}</time>'
            if ts else '<span class="nodate">Date not provided</span>')
    if it.get("summary"):
        summ = f'<p class="sum"><span class="basis">Publisher excerpt</span> {esc(it["summary"])}</p>'
    else:
        summ = (f'<p class="sum none">Summary unavailable. '
                f'<a href="{esc(it["url"])}" rel="noopener noreferrer" target="_blank">Read the original at {esc(it["publisher"])}</a>.</p>')
    also = ""
    if others:
        links = ", ".join(f'<a href="{esc(o["url"])}" rel="noopener noreferrer" target="_blank">{esc(o["publisher"])}</a>' for o in others)
        also = (f'<p class="also">Also reported by {links}. Repeated coverage of one report is not independent confirmation.</p>')
    corr = "".join(f'<p class="corr"><strong>Correction, {esc(c["date"])}:</strong> {esc(c["note"])}</p>'
                   for c in corrections if c.get("id") == it["id"])
    return f"""<article class="story" data-cat="{esc(it['category'])}" data-region="{esc(it['region'])}" data-ts="{esc(ts or '')}">
  <div class="when">{when}</div>
  <div class="what">
    <h3><a href="{esc(it['url'])}" rel="noopener noreferrer" target="_blank">{esc(it['title'])}</a></h3>
    <p class="meta"><span class="pub">{esc(it['publisher'])}</span><span>{esc(it['category'])}</span><span>{esc(it['region'])}</span></p>
    {summ}{also}{corr}
  </div>
</article>"""


# ---------- pages ----------

def home(cfg, items, editorial, status_html):
    hidden = set(editorial.get("hidden", []))
    visible = [i for i in items.values() if i["id"] not in hidden]
    groups = cluster(visible)
    rows = []
    for g in groups:
        g.sort(key=lambda i: i.get("published") or i["first_seen"])
        rows.append((g[0], g[1:]))
    rows.sort(key=lambda r: r[0].get("published") or r[0]["first_seen"], reverse=True)
    rows = rows[:cfg.get("homepage_items", 150)]
    corrections = editorial.get("corrections", [])
    by_id = {r[0]["id"]: r for r in rows}

    featured = [by_id[i] for i in editorial.get("featured", []) if i in by_id][:5]
    feat_html = ""
    if featured:
        feat_html = ('<section class="featured" aria-label="Selected by the editors"><h2 class="sect">Selected by the editors</h2>'
                     + "".join(story_html(i, o, corrections) for i, o in featured) + "</section>")

    chips = '<button type="button" class="chip" data-cat="" aria-pressed="true">All topics</button>' + "".join(
        f'<button type="button" class="chip" data-cat="{esc(c)}" aria-pressed="false">{esc(c)}</button>' for c in CATEGORIES)
    region_opts = '<option value="">All regions</option>' + "".join(f'<option>{esc(r)}</option>' for r in REGIONS)

    if rows:
        feed = "".join(story_html(i, o, corrections) for i, o in rows)
        feed_html = f'<div class="feed" id="feed">{feed}</div><p id="none" class="empty" hidden>No stories match these filters.</p>'
    else:
        feed_html = ('<div class="empty"><p>No stories collected yet.</p>'
                     '<p>Review a source in <code>sources.json</code>, set <code>terms_reviewed</code> and <code>enabled</code>, '
                     'then run <code>python run.py</code>.</p></div>')

    body = f"""{status_html}
<section class="controls" aria-label="Filters">
  <div class="chips" id="chips">{chips}</div>
  <label class="region">Region <select id="region">{region_opts}</select></label>
</section>
<p class="tz" id="tz"></p>
{feat_html}
{feed_html}"""
    return layout(cfg, f"{cfg['site_name']}: {cfg['tagline']}", body, 0, "Latest")


def edition_page(cfg, name, path, depth, what, rng):
    body = f"""<h1>{esc(name)}</h1>
<p class="lede">{what}</p>
<p>{rng}</p>
<div class="empty"><p>No edition has been published yet.</p>
<p>Editions start as drafts in <code>editions/drafts/</code> and appear here only after an editor moves them to <code>editions/published/</code>. Every edition states its exact date range in UTC.</p></div>"""
    return layout(cfg, f"{name} | {cfg['site_name']}", body, depth, name)


def archive_page(cfg, items, depth=1):
    publishers = sorted({i["publisher"] for i in items.values()})
    opt = lambda vals: "".join(f"<option>{esc(v)}</option>" for v in vals)
    body = f"""<h1>Archive</h1>
<form id="af" class="afilters" role="search">
  <label>Search headlines <input type="search" id="q" autocomplete="off"></label>
  <label>From <input type="date" id="from"></label>
  <label>To <input type="date" id="to"></label>
  <label>Topic <select id="cat"><option value="">All</option>{opt(CATEGORIES)}</select></label>
  <label>Region <select id="reg"><option value="">All</option>{opt(REGIONS)}</select></label>
  <label>Source <select id="src"><option value="">All</option>{opt(publishers)}</select></label>
</form>
<p id="count" class="tz" role="status"></p>
<ol id="results" class="results"></ol>
<noscript><p>The archive needs JavaScript to search. All stories are also in <a href="../data/archive.json">archive.json</a>.</p></noscript>"""
    return layout(cfg, f"Archive | {cfg['site_name']}", body, depth, "Archive",
                  '<script src="../assets/archive.js" defer></script>')


def about_page(cfg, registry, status):
    rows = ""
    for s in registry:
        if s.get("enabled") and s.get("terms_reviewed") and s.get("reuse") != "blocked":
            rows += (f'<tr><td>{esc(s["publisher"])}</td><td>{esc(s["coverage"])}</td>'
                     f'<td>Terms reviewed {esc(s["terms_reviewed"])}</td></tr>')
    table = (f'<table><thead><tr><th>Publisher</th><th>Coverage</th><th>Reuse check</th></tr></thead><tbody>{rows}</tbody></table>'
             if rows else "<p>No sources are switched on yet.</p>")
    body = f"""<h1>About and editorial policy</h1>
<p class="lede">{esc(cfg['site_name'])} is an independent finance and economics briefing. It aims to show readers what happened, why it matters, and what to watch next, with every claim traceable to a source.</p>
<h2>How stories get here</h2>
<p>Software collects headlines from publishers' own feeds every two hours. We only use a feed after reading the publisher's reuse terms. Each story links to the original article, shows the publisher and the original publication time, and carries the publisher's own excerpt where the feed provides one. If the feed offers nothing beyond the headline, we say "Summary unavailable" rather than guess.</p>
<h2>What is automated</h2>
<p>Topic and region tags are assigned by keyword rules and can be wrong. Stories from different outlets about the same report are grouped, and we do not treat repetition as independent confirmation.</p>
<h2>What we do not do</h2>
<p>We do not copy full articles, use unlicensed images, bypass paywalls, display live market tickers, or state prices, quotes or statistics that a source did not report.</p>
<h2>Analysis and editions</h2>
<p>Context and analysis will be labelled separately from reported facts and will link its supporting sources. Daily, weekly and monthly editions are drafted for human review and published only after approval.</p>
<h2>Corrections</h2>
<p>Corrections are attached to the affected story with the date and a note of what changed.</p>
<h2>Sources currently in use</h2>
{table}"""
    return layout(cfg, f"About | {cfg['site_name']}", body, 1, "About")


def run(root):
    root = Path(root)
    cfg = load_json(root / "config.json", {})
    registry = load_json(root / "sources.json", {"sources": []})["sources"]
    store = load_json(root / "data/items.json", {"items": {}})
    status = load_json(root / "data/status.json", {"sources": {}})
    editorial = load_json(root / "editorial.json", {})
    items = store["items"]
    now = now_utc()

    out = root / "site"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    shutil.copytree(root / "assets", out / "assets")

    enabled, last, stale = source_health(registry, status, cfg, now)
    status_html = status_block(enabled, last, stale, cfg)

    pages = {
        "index.html": home(cfg, items, editorial, status_html),
        "brief/index.html": edition_page(cfg, "Daily Brief", "brief", 1, "Ten to fifteen selected developments from the last day, each with what happened, why it matters and what to watch next.", "Covers one UTC calendar day."),
        "weekly/index.html": edition_page(cfg, "Weekly Review", "weekly", 1, "The week's major themes and how they connected, rather than a list of headlines.", "Covers Monday 00:00 to Sunday 23:59 UTC."),
        "monthly/index.html": edition_page(cfg, "Monthly Outlook", "monthly", 1, "A look back at the previous month plus the scheduled events to watch in the next.", "Covers one UTC calendar month."),
        "archive/index.html": archive_page(cfg, items),
        "about/index.html": about_page(cfg, registry, status),
    }
    for rel, content in pages.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, "utf-8")

    hidden = set(editorial.get("hidden", []))
    archive = sorted(
        ({"i": v["id"], "t": v["title"], "u": v["url"], "p": v["publisher"], "d": v.get("published"),
          "c": v["category"], "r": v["region"]} for v in items.values() if v["id"] not in hidden),
        key=lambda r: r["d"] or "", reverse=True)
    save_json(out / "data/archive.json", archive)
    save_json(out / "data/status.json", {
        "built": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_successful_collection": last.strftime("%Y-%m-%dT%H:%M:%SZ") if last else None,
        "stale_sources": stale,
        "sources": {s["id"]: {k: status["sources"].get(s["id"], {}).get(k) for k in ("last_success", "last_error")} for s in enabled},
    })
    print(f"build: {len(items)} items, site written to {out}")


if __name__ == "__main__":
    run(Path(__file__).parent)
