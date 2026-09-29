from urllib.parse import quote

from Skills.app_launcher import AppLauncher


class YouTubeSkill:
    """Search and open YouTube results (or a channel/playlist).

    ``build_url`` is pure for testing; ``search`` opens it in the
    default browser via the allowlisted AppLauncher.
    """

    BASE = "https://www.youtube.com"

    @staticmethod
    def build_url(query):
        query = (query or "").strip()
        if not query:
            return YouTubeSkill.BASE
        return f"{YouTubeSkill.BASE}/results?search_query={quote(query)}"

    def search(self, query):
        query = (query or "").strip()
        if not query:
            return "What should I search for on YouTube?"
        launcher = AppLauncher()
        url = self.build_url(query)
        ok, _ = launcher.open(url)
        return f"Searching YouTube for '{query}'." if ok else (
            f"I couldn't open YouTube search for '{query}'."
        )