# Olostep Link Checker

Finds broken links — hard 404s, soft 404s, and dead external links — on a site before
they quietly hurt SEO. New pages sometimes ship with a stray broken link; this catches it
early instead of waiting for someone to notice.

**How it works:** [Olostep Maps](https://docs.olostep.com) discovers every URL on the
site. Each page is then checked over plain HTTP first — free, and accurate for status
codes. Olostep **Scrape** is reserved for the two cases plain HTTP can't resolve on its
own: JS-rendered pages with no server-side content, and external links blocked or timed
out by anti-bot defenses. Verdicts are cached across runs, so repeat checks stay effective.

## Install

```bash
pipx install "git+https://github.com/rinkydevi/olostep-404s.git"
export OLOSTEP_API_KEY="your-own-key"     # never put this in the config file
```

[pipx](https://pipx.pypa.io) installs the CLI into its own isolated environment
automatically — no venv to manage yourself. (A short-name PyPI release is planned; until
then this git-based install is the primary path.)

## Quick start

```bash
olostep-link-checker init --site-url https://yoursite.com   # writes config.yaml
olostep-link-checker --config config.yaml
```

This prints a categorized summary (new / still-broken / fixed since the last run) and a
flat `url | from | status` table of every currently-broken link. Add `--csv out.csv` to
also write that table to a file.

## Config

Key fields in `config.yaml` (see `config.example.yaml` for the full annotated template):

- `site_url` — the site to scan
- `exclude_patterns` — glob patterns to skip (app routes, auth pages, playgrounds, etc.)
- `canary_url` — a URL guaranteed not to exist, checked each run to sanity-check soft-404 detection
- `budget_ceiling` — optional cap on Olostep scrape credits per run (unset = unlimited)

The API key is never read from this file — only from `OLOSTEP_API_KEY`.

Exit codes: `0` clean run, `1` budget cap stopped escalation partway (partial report,
still usable), `2` the soft-404 fingerprint no longer matches the site (fix
`classifier.py`), `4` config error, `5` site discovery failed.

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

193 tests, all against mocks/fixtures — no live Olostep credits spent by the suite.

## License

MIT
