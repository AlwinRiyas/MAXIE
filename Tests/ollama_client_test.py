import unittest
from unittest import mock

from requests.exceptions import ConnectionError as RequestsConnectionError

from AI.ollama_client import (
    CONNECTION_ERROR_MESSAGE,
    GENERIC_ERROR_MESSAGE,
    TIMEOUT_MESSAGE,
    OllamaClient,
)
from Config.config import Config


class _Response:
    def __init__(self, status=200, json_data=None):
        self.status_code = status
        self._json = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            from requests.exceptions import HTTPError

            raise HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._json or {}


class OllamaClientTest(unittest.TestCase):
    """Headless unit tests for the Ollama adapter (ROADMAP 9.2).

    requests.get/post are patched so the suite never touches the
    network; a slow/failed local Ollama must not affect correctness.
    """

    def setUp(self):
        self.base = "http://127.0.0.1:9999"
        self.client = OllamaClient(
            url=self.base,
            retries=2,
            retry_delay=0.0,
        )

    def test_ask_returns_message_content(self):
        with mock.patch(
            "AI.ollama_client.requests.post",
            return_value=_Response(json_data={
                "message": {"role": "assistant", "content": "hello there"}
            }),
        ) as post:
            answer = self.client.ask("hi")
        self.assertEqual(answer, "hello there")
        post.assert_called_once()

    def test_ask_falls_back_to_generate_response_key(self):
        with mock.patch(
            "AI.ollama_client.requests.post",
            return_value=_Response(json_data={"response": "plain reply"}),
        ) as post:
            answer = self.client.ask("hi")
        self.assertEqual(answer, "plain reply")
        post.assert_called_once()

    def test_empty_model_reply_is_empty_string(self):
        with mock.patch(
            "AI.ollama_client.requests.post",
            return_value=_Response(json_data={}),
        ):
            self.assertEqual(self.client.ask("hi"), "")

    def test_connection_error_retries_then_returns_user_facing_message(self):
        with mock.patch(
            "AI.ollama_client.requests.post",
            side_effect=RequestsConnectionError("refused"),
        ) as post:
            answer = self.client.ask("hi")
        self.assertEqual(answer, CONNECTION_ERROR_MESSAGE)
        self.assertEqual(post.call_count, 3)  # 1 initial + 2 retries

    def test_http_503_then_success_recovers(self):
        with mock.patch(
            "AI.ollama_client.requests.post",
            side_effect=[
                _Response(status=503),
                _Response(json_data={"message": {"content": "recovered"}}),
            ],
        ) as post:
            answer = self.client.ask("hi")
        self.assertEqual(answer, "recovered")
        self.assertEqual(post.call_count, 2)

    def test_timeout_retries_then_timeout_message(self):
        from requests.exceptions import Timeout

        with mock.patch(
            "AI.ollama_client.requests.post", side_effect=Timeout("slow")
        ) as post:
            answer = self.client.ask("hi")
        self.assertEqual(answer, TIMEOUT_MESSAGE)
        self.assertEqual(post.call_count, 3)

    def test_generic_error_collapses_without_retry(self):
        with mock.patch(
            "AI.ollama_client.requests.post",
            side_effect=ValueError("bad json"),
        ) as post:
            answer = self.client.ask("hi")
        self.assertEqual(answer, GENERIC_ERROR_MESSAGE)
        self.assertEqual(post.call_count, 1)

    def test_is_available_true_on_200(self):
        with mock.patch(
            "AI.ollama_client.requests.get",
            return_value=_Response(status=200),
        ) as getreq:
            self.assertTrue(self.client.is_available())
        getreq.assert_called_once()

    def test_is_available_false_on_connection_error(self):
        with mock.patch(
            "AI.ollama_client.requests.get",
            side_effect=RequestsConnectionError("down"),
        ):
            self.assertFalse(self.client.is_available())

    def test_is_available_false_on_non_200(self):
        with mock.patch(
            "AI.ollama_client.requests.get",
            return_value=_Response(status=500),
        ):
            self.assertFalse(self.client.is_available())

    def test_failure_messages_never_leak_internal_url(self):
        """SEC-05 / ROADMAP 9.9: no user-facing string may embed the URL."""
        tricky = "http://192.168.1.50:11434"
        client = OllamaClient(url=tricky, retries=0)
        from requests.exceptions import Timeout

        cases = [CONNECTION_ERROR_MESSAGE, TIMEOUT_MESSAGE, GENERIC_ERROR_MESSAGE]

        with mock.patch(
            "AI.ollama_client.requests.post",
            side_effect=RequestsConnectionError("consumed"),
        ):
            cases.append(client.ask("hi"))

        with mock.patch(
            "AI.ollama_client.requests.post", side_effect=Timeout("slow")
        ):
            cases.append(client.ask("hi"))

        with mock.patch(
            "AI.ollama_client.requests.post", side_effect=ValueError("x")
        ):
            cases.append(client.ask("hi"))

        for message in cases:
            self.assertNotIn("http", message)
            self.assertNotIn(tricky, message)
            self.assertNotIn("192.168.1.50", message)

    def test_provider_subclass_and_config_defaults(self):
        from AI.llm_provider import LLMProvider

        self.assertTrue(issubclass(OllamaClient, LLMProvider))
        cfg = Config.ai_config()
        self.assertIn("url", cfg)


if __name__ == "__main__":
    unittest.main()