import unittest

from Skills.web_search import WebSearchSkill


class WebSearchSkillTest(unittest.TestCase):

    def test_parse_extracts_title_and_url(self):
        html = """
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A//example.com/page">
            Example <b>Page</b>
        </a>
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ftest.org%2Fa%3Fb%3D1">
            Test Org
        </a>
        """
        results = WebSearchSkill._parse(html)
        self.assertEqual(len(results), 2)
        title, url = results[0]
        self.assertIn("Example", title)
        self.assertTrue(url.startswith("https://"))

    def test_clean_url_decodes_uddg(self):
        raw = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fsearch%3Fq%3Dhi"
        self.assertEqual(
            WebSearchSkill._clean_url(raw), "https://example.com/search?q=hi"
        )

    def test_clean_url_plain(self):
        self.assertEqual(WebSearchSkill._clean_url("https://plain.example"), "https://plain.example")

    def test_empty_query_guard(self):
        self.assertIn("search", WebSearchSkill().execute("   ").lower())


if __name__ == "__main__":
    unittest.main()