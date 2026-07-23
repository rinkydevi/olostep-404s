from olostep_link_checker.patterns import is_non_html_resource, is_placeholder_domain


def test_bare_placeholder_domains_are_recognized():
    for url in (
        "https://example.com/robots.txt",
        "https://example.org/data-maps",
        "https://example.net/search-guide",
        "https://example.edu/anything",
        "https://yourdomain.com/robots.txt",
    ):
        assert is_placeholder_domain(url) is True


def test_subdomains_of_placeholder_domains_are_recognized():
    for url in (
        "https://www.example.com/robots.txt",
        "https://shop.example.com/",
        "https://sub.yourdomain.com/x",
    ):
        assert is_placeholder_domain(url) is True


def test_real_domains_are_not_flagged():
    for url in (
        "https://www.olostep.com/blog/x",
        "https://www.reddit.com/prefs/apps",
        "https://exampleindustries.com/x",  # must not substring-match "example"
        "https://notyourdomain.com/x",
    ):
        assert is_placeholder_domain(url) is False


def test_pdf_json_xml_csv_zip_paths_are_non_html_resources():
    for url in (
        "https://homes.esat.kuleuven.be/~asenol/ua-reduction/user_agent_reduction_wpes_23.pdf",
        "https://olostep-storage.s3.us-east-1.amazonaws.com/json_hyjx3dykha_1.json",
        "https://example.com/data.xml",
        "https://example.com/export.csv",
        "https://example.com/archive.zip",
    ):
        assert is_non_html_resource(url) is True


def test_ordinary_html_paths_are_not_non_html_resources():
    for url in (
        "https://www.olostep.com/blog/how-to-scrape-reddit-data",
        "https://www.rfc-editor.org/rfc/rfc6585",
        "https://www.linkedin.com/in/jasonscui",  # policy-blocked, but not by extension
    ):
        assert is_non_html_resource(url) is False


def test_extension_check_is_path_based_not_domain_based():
    # reddit.com/r/python.json IS a genuine JSON endpoint by path, independent of the
    # fact that reddit is also separately policy-blocked by Olostep (external_resolver.py).
    assert is_non_html_resource("https://reddit.com/r/python.json") is True
