# The Economic Current

Global finance. Clear perspective.

First working version: **verified source → scheduled collection → stored news → website**.
Python 3.12 standard library only. There is nothing to install.

## Architecture

```
sources.json        source registry (feed URL, publisher, coverage, reuse terms, gate)
collect.py          fetch feeds, parse, tag, dedupe, store; keeps old items when a source fails
data/items.json     stored stories (committed to the repo, so history is preserved)
data/status.json    per-source last success, last error, recent log
editorial.json      featured, hidden and corrected stories (changed by reviewed pull request)
build.py            generates the static site in site/
.github/workflows/  runs collect + build every 2 hours, then deploys to GitHub Pages
```

Why this shape: a static site needs no server, database or login to run, and GitHub's scheduler
makes the site update when nobody has it open. The repository is the database and the audit trail.

The protected editorial workflow is GitHub itself: only people with repository access can change
`editorial.json` or move a draft from `editions/drafts/` to `editions/published/`, and branch
protection can require a reviewer. A custom admin screen is not built yet.

## Recurring costs

As far as I know (check current pricing before relying on it):

| Item | Cost |
|---|---|
| GitHub Pages and Actions on a **public** repository | Free |
| Private repository | Pages needs a paid GitHub plan; Actions has a monthly free allowance, and this job uses roughly 12 short runs a day |
| Domain name (optional) | About 10 to 15 USD a year |
| News APIs (optional, later) | Not used yet. Most commercial feeds and APIs are paid, and many forbid commercial republication |
| AI drafting of editions (later) | Pay per use through the Anthropic API, not built yet |

Limits: GitHub may delay scheduled runs by several minutes. The site is rebuilt on every run, so
history lives in `data/items.json` (kept for `retention_days`, default 365).

## Setup

1. Create a **public** GitHub repository and push this folder.
2. Settings → Pages → Source: **GitHub Actions**.
3. Settings → Secrets and variables → Actions → Variables: add `ECC_CONTACT` with a contact URL or
   email. It is sent in the User-Agent so publishers can reach you. Some, such as the SEC, ask for this.
4. On your own computer, check which feeds work: `python collect.py --verify`
5. For each source you want: open its `terms_url`, read the reuse terms, then in `sources.json` set
   `"terms_reviewed": "YYYY-MM-DD"` and `"enabled": true`. The collector refuses to fetch a source
   without a review date, and never fetches one marked `"reuse": "blocked"`.
6. Run locally with `python run.py` and open `site/index.html`, or push and let the workflow run.

**Manual refresh:** Actions tab → *Collect and publish* → *Run workflow*. There is deliberately no
public refresh button, because it would need a secret in the browser.

**Tests:** `python -m unittest discover tests` (offline, uses a synthetic fixture feed).

## What works and what does not yet

Works, and covered by the offline tests:
- Feed fetch with timeouts, a size cap and conditional requests, for RSS 2.0, RSS 1.0 and Atom
- Source gate (review date required, blocked sources refused)
- Dedupe by canonical URL, tracking parameters removed
- Excerpts taken only from the publisher's feed, shortened to 300 characters; when the feed gives
  nothing beyond the headline the story shows "Summary unavailable" with a link
- Automated topic and region tags by keyword rules (labelled as automated on the About page)
- Grouping of near-identical headlines from different publishers, with a note that repetition is not confirmation
- A failed source keeps its old stories; failures are logged; the homepage names stale sources
- Homepage with topic and region filters, times shown in the reader's timezone and stored in UTC,
  last successful collection time, featured and hidden stories, corrections
- Searchable archive (text, date range, topic, region, source)
- Scheduled workflow and deployment

Needs your action:
- **Every source is switched off.** I could not read publisher terms or reach feeds from where this
  was built (no internet access), so nothing is enabled. Only the Federal Reserve's sibling feed
  `press_bcreg.xml` was seen live. Other URLs are marked `likely` or `find` in `sources.json` and
  must be confirmed with `--verify`.
- Sources are 11 candidates, one of them (BBC) marked blocked because its feeds are for
  non-commercial use. Add a few more to reach a balanced mix, especially commercial outlets you license.
- GitHub repository, Pages and `ECC_CONTACT` setup (steps 1 to 3)

Not built yet:
- Daily Brief, Weekly Review and Monthly Outlook content (pages exist and show an honest empty state)
- AI-drafted editions and the review screen for them
- Per-story "why it matters" and "what to watch next" analysis
- Browser visual testing and accessibility audit

## Security notes

- No credentials are used. If you add an API later, keep the key in GitHub Actions secrets, never in the repo.
- Feed text is HTML-escaped when rendered. The parser is Python's built-in XML parser; for hostile feeds
  consider swapping in `defusedxml`.


## Day-to-day tasks (developer notes, kept off the public site)

**Turn a source on.** Run the *Verify sources* workflow (Actions tab) to test every feed from GitHub's network.
Read the publisher's terms (`terms_url`), then in `sources.json` set `enabled: true` and `terms_reviewed` to
today's date (YYYY-MM-DD). Never enable a source whose `reuse` is `blocked`. Set the repository variable
`ECC_CONTACT` (an email) because some regulators require a contact in the User-Agent. Then run *Collect and publish*.

**Calendar and IPOs.** Edit `events.json`. Every entry needs an https `source_url`, a `status`
(proposed, expected, confirmed, postponed, withdrawn, completed) and a `verified` date. Use `date: null` for TBC.
IPOs take `milestones` (filing, subscription_open, subscription_close, pricing, listing), each with its own date and status.
Check each milestone against the exchange or regulator filing before marking it `confirmed`.

**Newsletter editions.** Write a JSON file in `editions/drafts/{daily,weekly,monthly}/YYYY-MM-DD.json`. After review, move it to
`editions/published/...` and fill in `reviewed_by` and `reviewed_on`; editions without both are not published.
Each edition gets its own URL, for example `/brief/2026-11-16/`. Fields: `date`, `title`, `period_start`, `period_end`,
`intro`, `stories` (`headline`, `context`, `why`, `sources`), `themes`, `watchlist`, `connections`.

**Lead story note.** `editorial.json` -> `lead_note` {id, why, sources} adds a "Why it matters" note to the lead story, written by an editor from the cited reporting. It is shown only if the id matches the current lead.

**Newsletter signup.** Set `newsletter.enabled` to `true` and `newsletter.signup_url` to a working https form endpoint
(for example a Buttondown, Mailchimp or MailerLite form URL) in `config.json`. Until then the Subscribe button stays disabled.

**Tests.** `python -m unittest discover tests`

**Refresh schedule.** `.github/workflows/refresh.yml` runs at minute 17 of every second hour (UTC). If sources fail, the
last good stories stay and the header shows "updates delayed" after `stale_after_hours`.
