from dataclasses import dataclass, field

from bs4 import BeautifulSoup


@dataclass
class ExtractedLink:
    href: str
    anchor_texts: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.anchor_texts)


def extract_links(html: str) -> list[ExtractedLink]:
    soup = BeautifulSoup(html, "lxml")
    by_href: dict[str, ExtractedLink] = {}

    for tag in soup.find_all("a"):
        href = tag.get("href")
        if not href:
            continue

        anchor_text = tag.get_text(strip=True)
        if href not in by_href:
            by_href[href] = ExtractedLink(href=href)
        by_href[href].anchor_texts.append(anchor_text)

    return list(by_href.values())
