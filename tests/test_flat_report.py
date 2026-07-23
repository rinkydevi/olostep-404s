import csv

from olostep_link_checker.flat_report import flat_broken_list, render_pipe_table, write_csv

RUN = {
    "run_id": "2026-07-23T00:00:00Z",
    "results": [
        {
            "url": "https://x.com/broken",
            "classification": "hard-404",
            "status_code": 404,
            "source_pages": ["https://x.com/"],
            "anchor_text": ["Learn more"],
            "not_in_sitemap": False,
        },
        {
            "url": "https://external.com/dead",
            "classification": "external-dead",
            "status_code": None,
            "source_pages": ["https://x.com/blog/post"],
            "anchor_text": ["Ref"],
            "not_in_sitemap": True,
        },
        {
            "url": "https://x.com/fine",
            "classification": "ok",
            "status_code": 200,
            "source_pages": ["https://x.com/"],
            "anchor_text": ["Home"],
            "not_in_sitemap": False,
        },
        {
            "url": "https://external.com/blocked",
            "classification": "external-blocked",
            "status_code": 403,
            "source_pages": ["https://x.com/"],
            "anchor_text": ["Blocked"],
            "not_in_sitemap": True,
        },
        {
            "url": "https://x.com/orphan-broken",
            "classification": "hard-404",
            "status_code": 404,
            "source_pages": [],
            "anchor_text": [],
            "not_in_sitemap": False,
        },
    ],
}


def test_flat_broken_list_includes_only_confirmed_broken_classifications():
    rows = flat_broken_list(RUN)
    urls = {r["url"] for r in rows}
    assert urls == {"https://x.com/broken", "https://external.com/dead", "https://x.com/orphan-broken"}
    assert "https://x.com/fine" not in urls  # ok, excluded
    assert "https://external.com/blocked" not in urls  # ambiguous, excluded


def test_flat_broken_list_row_shape_includes_from_and_status():
    rows = flat_broken_list(RUN)
    row = next(r for r in rows if r["url"] == "https://x.com/broken")
    assert row["from"] == "https://x.com/"
    assert row["status"] == "hard-404 (404)"


def test_status_omits_parens_when_status_code_is_none():
    rows = flat_broken_list(RUN)
    row = next(r for r in rows if r["url"] == "https://external.com/dead")
    assert row["status"] == "external-dead"


def test_from_is_empty_string_when_no_source_page():
    rows = flat_broken_list(RUN)
    row = next(r for r in rows if r["url"] == "https://x.com/orphan-broken")
    assert row["from"] == ""


def test_rows_sorted_by_url():
    rows = flat_broken_list(RUN)
    urls = [r["url"] for r in rows]
    assert urls == sorted(urls)


def test_render_pipe_table_has_header_and_rows():
    rows = flat_broken_list(RUN)
    text = render_pipe_table(rows)
    lines = text.splitlines()
    assert lines[0] == "url | from | status"
    assert any("https://x.com/broken | https://x.com/ | hard-404 (404)" in line for line in lines)


def test_render_pipe_table_empty_says_no_broken_links():
    text = render_pipe_table([])
    assert "no confirmed broken links" in text.lower()


def test_write_csv_produces_valid_csv_with_header_and_rows(tmp_path):
    rows = flat_broken_list(RUN)
    path = tmp_path / "broken.csv"
    write_csv(rows, path)

    with open(path, newline="") as f:
        reader = list(csv.reader(f))

    assert reader[0] == ["url", "from", "status"]
    assert ["https://x.com/broken", "https://x.com/", "hard-404 (404)"] in reader
