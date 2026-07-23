import warnings

__version__ = "1.0.0"

# Some discovered URLs are XML (sitemaps, RSS/Atom feeds). We parse everything with the
# HTML parser to read status + harvest <a href>; for XML that yields nothing useful but is
# harmless. Silence BeautifulSoup's advisory warning so run output stays clean.
try:
    from bs4 import XMLParsedAsHTMLWarning

    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except Exception:
    pass
