import re

import requests


class WebSearchSkill:
    """Web search using the DuckDuckGo HTML endpoint (no API key,
    privacy-friendly, works without cloud sign-up).

    Only searches; it never executes anything returned by peers.
    """

    URL = "https://html.duckduckgo.com/html/"
    LIMIT = 3
    TIMEOUT = 12

    def execute(self, query):
        query = query.strip()
        if not query:
            return "Tell me what you'd like to search for."

        try:
            response = requests.get(
                self.URL,
                params={"q": query},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"
                    )
                },
                timeout=self.TIMEOUT,
            )
            response.raise_for_status()
        except (requests.RequestException, OSError) as error:
            return f"Search isn't available right now: {error}"

        results = self._parse(response.text)
        if not results:
            return f"I couldn't find results for {query}."

        lines = [f"Here's what I found for {query}:"]
        for title, url in results:
            lines.append(f"• {title} — {url}")
        return "\n".join(lines)

    @classmethod
    def _parse(cls, html):
        items = []
        pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for href, title in pattern.findall(html):
            title = re.sub(r"<[^>]+>", "", title)
            title = re.sub(r"\s+", " ", title).strip()
            url = cls._clean_url(href)
            if title and url:
                items.append((title, url))
            if len(items) >= cls.LIMIT:
                break
        return items

    @staticmethod
    def _clean_url(raw):
        raw = raw.strip()
        if raw.startswith("//"):
            raw = "https:" + raw
        if "uddg=" in raw:
            import urllib.parse

            parsed = urllib.parse.parse_qs(
                urllib.parse.urlparse(raw).query
            ).get("uddg", [raw])[0]
            raw = parsed
        return raw