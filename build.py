#!/usr/bin/env python3
"""Build the static site into site/ from data/items.json. Standard library only."""
import html
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from collect import CATEGORIES, REGIONS, load_json, now_utc, parse_iso, save_json

esc = html.escape

NAV = [("Latest News", ""), ("Daily Brief", "brief/"), ("Weekly Review", "weekly/"),
       ("Monthly Outlook", "monthly/"), ("Calendar", "calendar/"), ("Archive", "archive/"), ("About", "about/")]
CTX = {"refresh": "", "subscribe": ""}
STATUSES = ("proposed", "expected", "confirmed", "postponed", "withdrawn", "completed")
EVENT_TYPES = {"ipo": "IPO", "earnings": "Earnings", "inflation": "Inflation", "employment": "Employment",
               "gdp": "GDP", "central_bank": "Central bank", "election": "Election", "policy": "Policy deadline", "other": "Other"}
MILESTONES = [("filing", "Filing"), ("subscription_open", "Subscription opens"), ("subscription_close", "Subscription closes"),
              ("pricing", "Pricing"), ("listing", "Listing")]

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
<a class="skip" href="#main">Skip to content</a>
<header class="masthead">
  <div class="wrap">
    <a class="brand" href="{p or './'}">
      <span class="brand-name">{esc(cfg['site_name'])}</span>
      <svg class="wave" viewBox="0 0 120 10" aria-hidden="true" focusable="false"><path d="M0 5 C10 0 20 0 30 5 S50 10 60 5 S80 0 90 5 S110 10 120 5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>
    </a>
    <p class="tagline">{esc(cfg['tagline'])}</p>
    <div class="dateline"><span id="today">{now_utc().strftime('%A %d %b %Y')} (UTC)</span>{CTX['refresh']}</div>
    {CTX['subscribe']}
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


def story_html(it, others, corrections, pri=0, lead=False):
    ts = it.get("published")
    when = (f'<time class="t" datetime="{ts}">{esc(fmt_utc(ts))}</time>'
            if ts else '<span class="nodate">Date not provided</span>')
    upd = (f'<p class="upd">Updated <time class="t" datetime="{it["updated"]}">{esc(fmt_utc(it["updated"]))}</time></p>'
           if it.get("updated") else "")
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
    return f"""<article class="story{' lead' if lead else ''}" data-cat="{esc(it['category'])}" data-region="{esc(it['region'])}" data-ts="{esc(ts or '')}" data-pri="{pri}" data-text="{esc((it['title'] + ' ' + it['publisher'] + ' ' + (it.get('summary') or '')).lower())}">
  <div class="when">{when}{upd}</div>
  <div class="what">
    <h3><a href="{esc(it['url'])}" rel="noopener noreferrer" target="_blank">{esc(it['title'])}</a></h3>
    <p class="meta"><span class="pub">{esc(it['publisher'])}</span><span>{esc(it['category'])}</span><span>{esc(it['region'])}</span></p>
    {summ}{also}{corr}
  </div>
</article>"""


# ---------- pages ----------

def priority(group, registry_kind):
    """Editorial-priority score: more independent publishers and official sources rank higher. Recency breaks ties."""
    pubs = {i["publisher"] for i in group}
    official = any(registry_kind.get(i.get("source_id")) == "official" for i in group)
    return len(pubs) * 10 + (5 if official else 0)


def build_rows(items, editorial, registry):
    hidden = set(editorial.get("hidden", []))
    visible = [i for i in items.values() if i["id"] not in hidden]
    kind = {s["id"]: s.get("kind", "press") for s in registry}
    rows = []
    for g in cluster(visible):
        g.sort(key=lambda i: i.get("published") or "9999")
        rows.append({"lead": g[0], "others": g[1:], "pri": priority(g, kind)})
    # newest first; undated stories go last because collection time is not publication time
    rows.sort(key=lambda r: r["lead"].get("published") or "", reverse=True)
    return rows


def parse_day(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def clean_events(events):
    """Keep only events that have a source link and a valid status. Unknown dates become TBC, never guessed."""
    good = []
    for e in events:
        if not e.get("title") or not str(e.get("source_url", "")).startswith("https://"):
            continue
        if e.get("status") not in STATUSES:
            continue
        e = dict(e)
        e["_day"] = parse_day(e.get("date"))
        good.append(e)
    return good


def date_label(day, raw, time_utc=None):
    if not day:
        return "TBC"
    return day.strftime("%d %b %Y") + (f", {esc(time_utc)} UTC" if time_utc else "")


def event_html(e):
    t = EVENT_TYPES.get(e.get("type"), "Other")
    head = f'<h3>{esc(e["title"])}</h3>'
    st = f'<span class="badge {e["status"]}">{e["status"].capitalize()}</span>'
    meta = " ".join(f"<span>{esc(str(e[k]))}</span>" for k in ("country", "exchange", "ticker", "currency") if e.get(k))
    ms = ""
    if e.get("type") == "ipo":
        rows = ""
        for key, label in MILESTONES:
            m = (e.get("milestones") or {}).get(key) or {}
            d = parse_day(m.get("date"))
            mst = m.get("status") if m.get("status") in STATUSES else None
            rows += (f'<tr><th scope="row">{label}</th><td>{date_label(d, m.get("date"), m.get("time_utc"))}</td>'
                     f'<td>{f"<span class=\'badge {mst}\'>{mst.capitalize()}</span>" if mst and d else "TBC"}</td></tr>')
        price = e.get("final_price") or e.get("offer_range")
        pl = ("Final price" if e.get("final_price") else "Offer range") if price else ""
        ms = (f'<table class="ms"><tbody>{rows}</tbody></table>'
              + (f'<p class="meta"><span>{pl}: {esc(str(price))}</span></p>' if price else ""))
    ver = f' Checked {esc(e["verified"])}.' if e.get("verified") else ""
    return (f'<article class="event" data-type="{esc(e.get("type", "other"))}"><div class="when">{date_label(e["_day"], e.get("date"), e.get("time_utc"))}</div>'
            f'<div class="what">{head}<p class="meta"><span class="pub">{t}</span>{st}{meta}</p>{ms}'
            f'<p class="also">Source: <a href="{esc(e["source_url"])}" rel="noopener noreferrer" target="_blank">{esc(e.get("source_name") or "Original announcement")}</a>.{ver}</p></div></article>')


def sidebar(cfg, events, editorial, today):
    up = sorted((e for e in events if e["status"] not in ("withdrawn", "completed") and (e["_day"] is None or e["_day"] >= today)),
                key=lambda e: (e["_day"] is None, e["_day"] or today))[:6]
    ev = ("".join(f'<li><span class="d">{date_label(e["_day"], None)}</span> <a href="{esc(e["source_url"])}" rel="noopener noreferrer" target="_blank">{esc(e["title"])}</a>'
                  f' <span class="badge {e["status"]}">{e["status"].capitalize()}</span></li>' for e in up)
          if up else "<li>No upcoming events have been added yet.</li>")
    th = "".join(f'<li><strong>{esc(t["title"])}</strong> {esc(t.get("note", ""))}</li>' for t in editorial.get("themes", []))
    th = th or "<li>Themes appear here when the editors publish them.</li>"
    return f"""<aside class="side" aria-label="Sidebar">
<section><h2 class="sect">Newsletter</h2><p class="small">Daily Brief, Weekly Review and Monthly Outlook, each with dated source links.</p>{CTX['subscribe']}</section>
<section><h2 class="sect">Coming up</h2><ul class="plain">{ev}</ul><p class="small"><a href="calendar/">Full calendar</a></p></section>
<section><h2 class="sect">Themes to watch</h2><ul class="plain">{th}</ul></section>
</aside>"""


def home(cfg, rows, editorial, status_html, events, today):
    corrections = editorial.get("corrections", [])
    by_id = {r["lead"]["id"]: r for r in rows}
    ordered = [by_id[i] for i in editorial.get("featured", []) if i in by_id]
    rest = sorted((r for r in rows if r not in ordered), key=lambda r: (r["pri"], r["lead"].get("published") or ""), reverse=True)
    top = (ordered + rest)[:5]
    top_html = ""
    if top:
        note = editorial.get("lead_note") or {}
        why = ""
        if note.get("id") == top[0]["lead"]["id"] and note.get("why"):
            srcs = ", ".join(f'<a href="{esc(u["url"])}" rel="noopener noreferrer" target="_blank">{esc(u["publisher"])}</a>' for u in note.get("sources", []))
            why = f'<div class="why"><h3>Why it matters</h3><p>{esc(note["why"])}</p>' + (f'<p class="small">Sources: {srcs}</p>' if srcs else "") + "</div>"
        top_html = ('<section class="top" aria-label="Top stories"><h2 class="sect">Top stories</h2>'
                    + story_html(top[0]["lead"], top[0]["others"], corrections, top[0]["pri"], True) + why
                    + "".join(story_html(r["lead"], r["others"], corrections, r["pri"]) for r in top[1:]) + "</section>")
    chips = '<button type="button" class="chip" data-cat="" aria-pressed="true">All topics</button>' + "".join(
        f'<button type="button" class="chip" data-cat="{esc(c)}" aria-pressed="false">{esc(c)}</button>' for c in CATEGORIES)
    opts = lambda vals, first: f'<option value="">{first}</option>' + "".join(f"<option>{esc(v)}</option>" for v in vals)
    if rows:
        feed = "".join(story_html(r["lead"], r["others"], corrections, r["pri"]) for r in rows[:cfg.get("homepage_items", 150)])
        feed_html = (f'<p id="loading" class="empty">Loading stories…</p><div class="feed" id="feed">{feed}</div>'
                     '<p id="none" class="empty" hidden>No stories match these filters. Clear a filter or search term to see more.</p>'
                     '<p class="more"><button type="button" id="more" class="btn" hidden>Load more</button></p>'
                     '<noscript><p class="status warn">JavaScript is off, so filters are unavailable. All stories are listed in date order above.</p></noscript>')
    else:
        feed_html = '<div class="empty"><p>No verified stories are available right now.</p><p>Stories appear here after their sources have been reviewed and collected. Nothing on this site is placeholder or simulated.</p></div>'
    body = f"""{status_html}
{top_html}
<div class="cols"><div class="mainc">
<h2 class="sect" id="latest">Latest worldwide news</h2>
<section class="controls" aria-label="Search and filters">
  <label class="q">Search <input type="search" id="q" autocomplete="off" placeholder="Headline, publisher or topic"></label>
  <div class="chips" id="chips">{chips}</div>
  <label>Region <select id="region">{opts(REGIONS, "All regions")}</select></label>
  <label>Published <select id="when"><option value="">Any time</option><option value="1">Last 24 hours</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option></select></label>
  <label>Sort <select id="sort"><option value="new">Newest first</option><option value="pri">Editorial priority</option></select></label>
</section>
<p class="tz" id="tz"></p>
<p id="count" class="tz" role="status"></p>
{feed_html}
</div>{sidebar(cfg, events, editorial, today)}</div>"""
    return layout(cfg, f"{cfg['site_name']}: {cfg['tagline']}", body, 0, "Latest News")


def calendar_page(cfg, events, today):
    ev = sorted(events, key=lambda e: (e["_day"] is None, e["_day"] or today))
    upcoming = [e for e in ev if e["status"] not in ("completed", "withdrawn") and (e["_day"] is None or e["_day"] >= today)]
    past = [e for e in ev if e not in upcoming]
    chips = '<button type="button" class="chip" data-type="" aria-pressed="true">All events</button>' + "".join(
        f'<button type="button" class="chip" data-type="{k}" aria-pressed="false">{v}</button>' for k, v in EVENT_TYPES.items())
    sec = lambda title, lst: (f'<h2 class="sect">{title}</h2>' + "".join(event_html(e) for e in lst)) if lst else ""
    body = f"""<h1>Calendar</h1>
<p class="lede">IPO milestones, earnings, data releases, central-bank decisions, elections and policy deadlines. Dates are UTC. TBC means no date has been announced. Expected and proposed dates are not confirmed.</p>
<div class="chips" id="evchips">{chips}</div>
<div id="evlist">{sec("Upcoming", upcoming)}{sec("Recent and past", past)}</div>
{'' if ev else '<div class="empty"><p>No events have been added yet.</p><p>Each event needs an official source link before it is shown.</p></div>'}"""
    return layout(cfg, f"Calendar | {cfg['site_name']}", body, 1, "Calendar", '<script src="../assets/calendar.js" defer></script>')


def load_editions(root):
    out = {"daily": [], "weekly": [], "monthly": []}
    for kind in out:
        for f in sorted((Path(root) / "editions/published" / kind).glob("*.json"), reverse=True):
            try:
                e = json.loads(f.read_text("utf-8"))
            except ValueError:
                continue
            if parse_day(e.get("date")) and e.get("reviewed_by") and e.get("reviewed_on"):
                e["kind"] = kind
                out[kind].append(e)
    return out


SECTIONS = {"daily": ("brief", "Daily Brief", "Essential stories", "Coming up"),
            "weekly": ("weekly", "Weekly Review", "Major developments", "Connections across the week"),
            "monthly": ("monthly", "Monthly Outlook", "Themes of the month", "Watchlist for next month")}
LEDE = {"daily": "Ten to fifteen selected developments from the last day, each with context and what is coming next.",
        "weekly": "The week's major themes and how they connected, rather than a list of headlines.",
        "monthly": "A look back at the previous month plus the scheduled events to watch in the next."}


def edition_index(cfg, kind, editions):
    slug, name, _, _ = SECTIONS[kind]
    if editions:
        lst = "".join(f'<li><a href="{e["date"]}/">{esc(e.get("title") or name)}</a> <span class="meta">{esc(e["date"])}</span></li>' for e in editions)
        inner = f'<ul class="plain">{lst}</ul>'
    else:
        inner = f'<div class="empty"><p>The first {esc(name)} has not been published yet.</p></div>'
    body = f'<h1>{esc(name)}</h1><p class="lede">{LEDE[kind]}</p>{inner}'
    return layout(cfg, f"{name} | {cfg['site_name']}", body, 1, name)


def src_links(srcs):
    return ", ".join(f'<a href="{esc(u["url"])}" rel="noopener noreferrer" target="_blank">{esc(u.get("publisher", "Source"))}</a>' for u in srcs or [] if str(u.get("url", "")).startswith("http"))


def edition_page(cfg, e):
    slug, name, h1, h2 = SECTIONS[e["kind"]]
    stories = "".join(
        f'<article class="ed-story"><h3>{esc(s["headline"])}</h3><p>{esc(s.get("context", ""))}</p>'
        + (f'<p class="why-line"><strong>Why it matters.</strong> {esc(s["why"])}</p>' if s.get("why") else "")
        + f'<p class="also">Sources: {src_links(s.get("sources")) or "none listed"}</p></article>' for s in e.get("stories", []))
    watch = "".join(f'<li>{esc(w.get("date", "TBC"))}: {esc(w["text"])}'
                    + (f' <a href="{esc(w["source_url"])}" rel="noopener noreferrer" target="_blank">Source</a>' if w.get("source_url") else "") + "</li>"
                    for w in e.get("watchlist", []))
    themes = "".join(f"<li><strong>{esc(t['title'])}</strong> {esc(t.get('note', ''))}</li>" for t in e.get("themes", []))
    conn = f'<p>{esc(e["connections"])}</p>' if e.get("connections") else ""
    if e["kind"] == "daily":
        second = f'<h2>{h2}</h2><ul class="plain">{watch}</ul>' if watch else ""
        first_extra = ""
    elif e["kind"] == "weekly":
        second = f"<h2>{h2}</h2>{conn}" if conn else ""
        first_extra = ""
    else:
        first_extra = f'<h2>{h1}</h2><ul class="plain">{themes}</ul>' if themes else ""
        second = f'<h2>{h2}</h2><ul class="plain">{watch}</ul>' if watch else ""
    lead_h = "" if e["kind"] == "monthly" else f"<h2>{h1}</h2>"
    body = (f'<h1>{esc(e.get("title") or name)}</h1><p class="meta"><span>{esc(e["date"])}</span>'
            f'<span>Covers {esc(e.get("period_start", e["date"]))} to {esc(e.get("period_end", e["date"]))} UTC</span>'
            f'<span>Reviewed by {esc(e["reviewed_by"])} on {esc(e["reviewed_on"])}</span></p>'
            f'{f"<p class=lede>{esc(e["intro"])}</p>" if e.get("intro") else ""}{first_extra}{lead_h}{stories}{second}'
            f'<p class="small"><a href="../">All {esc(name)} editions</a></p>')
    return layout(cfg, f'{e.get("title") or name} | {cfg["site_name"]}', body, 2, name)


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
    last_s = last.strftime("%Y-%m-%dT%H:%M:%SZ") if last else None
    CTX["refresh"] = (f'<span class="rf{" late" if stale else ""}">News last refreshed <time class="full" datetime="{last_s}">{fmt_utc(last_s)}</time>'
                      + (" (updates delayed)" if stale else "") + "</span>") if last else '<span class="rf late">No successful news refresh yet</span>'
    nl = cfg.get("newsletter", {})
    if nl.get("enabled") and str(nl.get("signup_url", "")).startswith("https://"):
        CTX["subscribe"] = (f'<form class="sub" method="post" action="{esc(nl["signup_url"])}"><label class="sr">Email address</label>'
                            '<input type="email" name="email" required placeholder="Email address"><button class="btn" type="submit">Subscribe</button></form>')
    else:
        CTX["subscribe"] = '<div class="sub off"><button class="btn" type="button" disabled>Subscribe</button><span class="small">Signup opens when the newsletter launches.</span></div>'

    events = clean_events(load_json(root / "events.json", {"events": []}).get("events", []))
    today = now.date()
    rows = build_rows(items, editorial, registry)
    editions = load_editions(root)

    pages = {
        "index.html": home(cfg, rows, editorial, status_html, events, today),
        "calendar/index.html": calendar_page(cfg, events, today),
        "archive/index.html": archive_page(cfg, items),
        "about/index.html": about_page(cfg, registry, status),
    }
    for kind, (slug, *_r) in SECTIONS.items():
        pages[f"{slug}/index.html"] = edition_index(cfg, kind, editions[kind])
        for e in editions[kind]:
            pages[f"{slug}/{e['date']}/index.html"] = edition_page(cfg, e)
    for rel, content in pages.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, "utf-8")

    hidden = set(editorial.get("hidden", []))
    archive = sorted(
        ({"i": v["id"], "t": v["title"], "u": v["url"], "p": v["publisher"], "d": v.get("published"), "x": v.get("updated"),
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
