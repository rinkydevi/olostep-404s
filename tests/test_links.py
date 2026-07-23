from pathlib import Path

from olostep_link_checker.links import extract_links

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_UNIQUE_HREFS = {
    "/", "/careers", "/blog", "/pricing", "/docs",
    "/careers/backend-engineer", "/careers/frontend-engineer", "/careers/product-designer",
    "https://www.linkedin.com/company/olostep", "https://twitter.com/olostep",
    "../blog/culture", "//status.olostep.com",
    "mailto:careers@olostep.com", "tel:+14155551234",
    "/legacy-careers-page", "/this-page-definitely-does-not-exist-404-test",
    "/privacy", "/terms", "https://github.com/olostep", "/dashboard/monitors",
    "#top", "javascript:void(0)",
}


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_extracts_all_unique_hrefs_from_healthy_page():
    links = extract_links(load("healthy_page.html"))
    hrefs = {link.href for link in links}
    assert hrefs == EXPECTED_UNIQUE_HREFS
    assert len(links) == len(EXPECTED_UNIQUE_HREFS)


def test_anchor_tag_without_href_is_skipped():
    links = extract_links(load("healthy_page.html"))
    anchor_texts = {text for link in links for text in link.anchor_texts}
    assert "Missing href entirely" not in anchor_texts


def test_button_onclick_is_not_extracted_as_a_link():
    links = extract_links(load("healthy_page.html"))
    hrefs = {link.href for link in links}
    assert "/not-a-real-link" not in hrefs


def test_duplicate_href_deduplicated_with_occurrence_count_and_anchor_texts_preserved():
    links = extract_links(load("healthy_page.html"))
    home_link = next(link for link in links if link.href == "/")
    assert home_link.count == 2
    assert home_link.anchor_texts == ["Home", "Home"]

    designer_link = next(link for link in links if link.href == "/careers/product-designer")
    assert designer_link.count == 2
    assert designer_link.anchor_texts == ["Product Designer", "Product Designer (duplicate)"]


def test_non_duplicate_link_has_count_one():
    links = extract_links(load("healthy_page.html"))
    careers_link = next(link for link in links if link.href == "/careers")
    assert careers_link.count == 1
    assert careers_link.anchor_texts == ["Careers"]


def test_nav_and_footer_links_extracted_same_as_body():
    links = extract_links(load("healthy_page.html"))
    hrefs = {link.href for link in links}
    assert "/pricing" in hrefs
    assert "https://github.com/olostep" in hrefs
