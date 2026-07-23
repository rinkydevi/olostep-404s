# Olostep Link Checker

Detects 404s and broken links (hard and soft) on a site. Built so a designer shipping new
pages can't silently tank SEO with a dead link.

**Architecture (v3, HTTP-first + Olostep-verified externals):** Olostep **Maps** discovers
the site's URL set; every page is then checked over plain HTTP (honest status codes — we
verified the origin returns real 404s, so no scrape is needed just to read status); Olostep
**Scrape** is spent on two things: JS-rendering the rare content-less shell page a plain GET
can't see into, and re-verifying every external link plain HTTP couldn't confidently clear
(blocked by anti-bot, timed out, or even reported dead — a bare HTTP client and a real
browser get different answers from third-party sites, live-verified at scale). Verdicts
are cached across runs so only new/changed external links pay the credit again.

## Setup (any teammate, on their own machine)

```bash
git clone <this-repo> && cd olostep-link-checker
python3 -m venv .venv
source .venv/bin/activate
pip install -e .                          # installs the `olostep-link-checker` command
export OLOSTEP_API_KEY="your-own-key"     # never put this in the config file
```

`pip install -e .` registers a real command on your PATH — after this, `olostep-link-checker`
works from anywhere (no `python -m`, no remembering the package path). Each person uses
their own Olostep API key via the env var; nothing here is shared or hardcoded.

## Configure

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml`:

- `site_url` — the site to scan.
- `exclude_patterns` — glob patterns for app routes / non-SEO surface (`/dashboard/**`, `/auth`, `/playground`, ...). Same syntax as Olostep Maps' `exclude_urls`.
- `canary_url` — a URL on the site guaranteed not to exist. Checked every run to confirm the soft-404 fingerprint (`classifier.py`) still matches this site's actual 404 page before anything else is trusted.
- `budget_ceiling` — hard cap on `scrape_website` credits per run (main loop + canary + internal-fallback fetches all count). Unset by default (unlimited); set an integer to cap cost on a specific run.
- `concurrency` — max concurrent scrape calls in flight.
- `runs_dir` — where run history JSON is written/read for diffing.

The API key is **never** read from this file — only from `OLOSTEP_API_KEY`.

## Run

```bash
olostep-link-checker --config config.yaml
```

This prints a categorized human-readable summary (new/still/fixed), writes the full run
(JSON) to `<runs_dir>/<run_id>.json`, and prunes run files older than `--retention-days`
(default 90).

### Getting a flat list: `url | from | status`

After the categorized summary, the CLI always also prints a flat table of every
currently-confirmed-broken link — the simplest form to skim or paste into Slack:

```
url | from | status
https://www.olostep.com/about-olostep | https://www.olostep.com/blog/ai-training-data-providers | hard-404 (404)
...
```

Add `--csv path/to/file.csv` to also write the same rows to a CSV (opens directly in
Sheets/Excel — same three columns: `url,from,status`):

```bash
olostep-link-checker --config config.yaml --csv broken-links.csv
```

This is the "hand this to someone else" output — it's a flat, deduplicated, currently-true
snapshot (only confirmed-broken: `hard-404`/`soft-404`/`external-dead`/`redirect-loop`),
unlike the categorized summary above which is about *what changed* since the last run.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Clean run, completed within the scrape-escalation budget |
| `1` | `budget_ceiling` is set in `config.yaml` (it's unset/unlimited by default) and stopped further escalation partway (JS-shell pages and/or external-link resolution) — partial report, not a crash. Raise or remove `budget_ceiling`; the unescalated pages/links keep `confidence: "unverified"` so this is visible in the report, not silent |
| `2` | Canary check failed: the soft-404 fingerprint no longer matches this site's real 404 page. This gates *only* soft-404 detection — a genuine soft-404 page reports as `ok` instead of `soft-404` this run rather than risking a guess. `hard-404` and every external result don't depend on this fingerprint and are still fully trustworthy in the same report. Fix the fingerprint in `classifier.py`, then re-run |
| `4` | Config error (missing/invalid `config.yaml`, or `OLOSTEP_API_KEY` not set) |
| `5` | Site discovery failed (the Maps API call itself errored) — the only code with no report at all |

## Reading the report

The report groups broken links into:

- **`newly_broken`** — broke since the last run. This is what should page someone.
- **`still_broken`** — broke before and still is; `first_seen` is carried forward from when it first appeared, not reset.
- **`new_baseline`** — first run ever (no prior run to diff against), so these are framed as a starting baseline, not a regression.
- **`fixed`** — broken last run, healthy now.
- **`no_longer_scanned`** — was broken last run, but the URL wasn't discovered/scanned at all this run (e.g. the page was removed).

Each entry has: `url`, `break_type` (`hard-404` / `soft-404` / `external-dead` / `external-timeout` / `redirect-loop`), `source_pages` (which page(s) link to it), `anchor_text`, `first_seen`, and `confidence` (`confirmed` — settled by plain HTTP or an unambiguous status; `browser-verified` — an Olostep escalation resolved something plain HTTP couldn't; `unverified` — still ambiguous, e.g. budget ran out before escalating it).

`unverified` (in the report's separate `unverified` section, not counted as broken) covers `external-blocked`, `external-timeout`, `external-unreachable` (Olostep itself couldn't resolve it even after escalation), and `external-provider-unsupported` (Olostep refuses this domain by durable account policy — e.g. LinkedIn, Reddit — not a transient failure). None of these are ever reported as confirmed-broken. A non-HTML resource (PDF/JSON/XML/CSV/ZIP by URL extension) is never escalated at all — Olostep's scrape is an HTML renderer and only makes these worse (live-verified: a 504 timeout on a real dead PDF, null content on a real JSON file) — so its plain-HTTP verdict is trusted directly and reported `confidence: confirmed`.

### v3: how external links get resolved (`external_resolver.py`)

Plain HTTP settles most external links on its own, but it structurally can't win against
two kinds of third-party defenses: outright anti-bot blocking (403/429/999) and a sneakier
soft-404 served only to bot-like request signatures (live-verified on `rfc-editor.org`,
`support.google.com`, and others). Any external
link plain HTTP leaves `external-blocked`, `external-timeout`, or `external-dead` gets a
second opinion via an Olostep scrape (budget-gated, same ceiling as JS-shell escalation).
The decision on that scrape never trusts Olostep's own status code (it reflects the
rendered document, not the origin — the same trap §8.1 found for internal pages) or
content length alone (a real 404 template and a real long document can both be almost any
length). Instead: a title/H1 not-found-phrase fingerprint decides dead, substantial
rendered content with no such fingerprint decides alive, and anything else — including
Olostep itself failing to reach the page — stays honestly `unverified`.

Resolved verdicts are cached in `verdict_cache_path` (default `data/external_verdicts.json`)
keyed by URL, and reused for `verdict_staleness_days` (default 14) before a link is
re-escalated — so the first run on a site pays the full external-resolution cost and
steady-state runs only pay for new or changed links.

## Adding or updating the site's 404 fingerprint

Soft-404 detection (`olostep_link_checker/classifier.py`) requires **all three** signals
to match before flagging a page as a soft-404 — this is deliberate, to avoid false
positives on any legitimate page that happens to mention "404" in its own copy:

- `<title>` contains a configured substring (default: `"this page could not be found"`)
- an element with a configured class exists (default: `next-error-h1`)
- the page's `<h1>` text exactly matches a configured string (default: `"404"`)

If the site's actual 404 page markup changes, update the three constants at the top of
`classifier.py` (`_SOFT_404_TITLE_SUBSTRING`, `_SOFT_404_ERROR_CLASS`, `_SOFT_404_H1_TEXT`).
The canary check (exit code `2`) exists specifically to catch this drift automatically —
if it starts failing, that's your signal these constants are stale, not that the site
broke. A failed canary no longer aborts the run: it only means soft-404 detection is
disabled for that run (a genuine soft-404 reads as `ok` rather than being guessed at).
`hard-404` and every external result are a completely separate check each and are
unaffected — the report still comes back full and usable, just flagged.

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

All 190 tests run against mocks/fixtures — no live Olostep credits are spent and no
real network calls are made by the test suite. (The v3 design itself *was* validated with
real credits before being implemented, but that was a one-time live probe, not something
the test suite repeats on every run.) Built TDD-style throughout: test first, watch it
fail, implement, watch it pass.
