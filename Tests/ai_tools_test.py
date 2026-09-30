import json
import unittest
from unittest import mock

import requests

from AI.llm_provider import LLMProvider
from AI.ollama_client import (
    CONNECTION_ERROR_MESSAGE,
    GENERIC_ERROR_MESSAGE,
    OllamaClient,
    TIMEOUT_MESSAGE,
)


def _requests_post(**kwargs):
    """Patch the HTTP call on the lazily-loaded ``requests``.

    ``AI.ollama_client`` defers importing ``requests`` until a turn
    actually talks to the LLM, so its module attribute is ``None`` until
    something calls ``_load_requests()``. Resolve it first, then patch the
    real module, which is the same object the production code ends up
    using.
    """
    import AI.ollama_client as ollama_client

    ollama_client._load_requests()
    return mock.patch.object(ollama_client.requests, "post", **kwargs)


def _response(payload, status=200):
    response = mock.Mock()
    response.status_code = status
    response.json.return_value = payload
    if status >= 400:
        # Behave like requests: an error status raises.
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=response)
    return response


class ToolCallParsingTest(unittest.TestCase):
    """A malformed call must degrade to "no call", never to a call."""

    def test_reads_a_well_formed_call(self):
        message = {"tool_calls": [{"function": {
            "name": "OPEN_APP", "arguments": {"app": "brave"}}}]}
        self.assertEqual(OllamaClient.parse_tool_call(message),
                         ("OPEN_APP", {"app": "brave"}))

    def test_parses_json_string_arguments(self):
        message = {"tool_calls": [{"function": {
            "name": "OPEN_APP",
            "arguments": '{"app": "brave"}'}}]}
        self.assertEqual(OllamaClient.parse_tool_call(message),
                         ("OPEN_APP", {"app": "brave"}))

    def test_no_tool_calls_yields_none(self):
        self.assertIsNone(OllamaClient.parse_tool_call({"content": "hi"}))
        self.assertIsNone(OllamaClient.parse_tool_call({}))
        self.assertIsNone(OllamaClient.parse_tool_call({"tool_calls": []}))

    def test_unparsable_json_arguments_yield_none(self):
        message = {"tool_calls": [{"function": {
            "name": "OPEN_APP", "arguments": "{not json"}}]}
        self.assertIsNone(OllamaClient.parse_tool_call(message))

    def test_non_object_arguments_yield_none(self):
        message = {"tool_calls": [{"function": {
            "name": "OPEN_APP", "arguments": "[1, 2]"}}]}
        self.assertIsNone(OllamaClient.parse_tool_call(message))

    def test_missing_name_yields_none(self):
        message = {"tool_calls": [{"function": {"arguments": {}}}]}
        self.assertIsNone(OllamaClient.parse_tool_call(message))

    def test_only_the_first_call_is_returned(self):
        message = {"tool_calls": [
            {"function": {"name": "TIME", "arguments": {}}},
            {"function": {"name": "SHUTDOWN", "arguments": {}}},
        ]}
        self.assertEqual(OllamaClient.parse_tool_call(message), ("TIME", {}))


class AskWithToolsTest(unittest.TestCase):
    def setUp(self):
        self.client = OllamaClient(url="http://127.0.0.1:1", retries=0,
                                   retry_delay=0)

    def test_tools_are_sent_and_a_call_is_returned(self):
        payload = {"message": {"content": "",
                               "tool_calls": [{"function": {
                                   "name": "OPEN_APP",
                                   "arguments": {"app": "brave"}}}]}}
        with _requests_post(
                        return_value=_response(payload)) as post:
            text, call = self.client.ask_with_tools(
                "open brave", [{"type": "function", "function": {
                    "name": "OPEN_APP"}}])
        self.assertEqual(call, ("OPEN_APP", {"app": "brave"}))
        self.assertEqual(text, "")
        self.assertEqual(
            post.call_args.kwargs["json"]["tools"][0]["function"]["name"],
            "OPEN_APP")

    def test_plain_answer_with_no_call(self):
        payload = {"message": {"content": "It is half past three."}}
        with _requests_post(
                        return_value=_response(payload)):
            text, call = self.client.ask_with_tools("what time is it", [])
        self.assertEqual(call, None)
        self.assertIn("half past", text)

    def test_empty_tool_list_falls_back_to_plain_ask(self):
        with _requests_post(
                        return_value=_response(
                            {"message": {"content": "sure"}})) as post:
            text, call = self.client.ask_with_tools("hello", [])
        self.assertIsNone(call)
        self.assertEqual(text, "sure")
        self.assertNotIn("tools", post.call_args.kwargs["json"])

    def test_timeout_returns_the_stable_message_and_no_call(self):
        with _requests_post(
                        side_effect=requests.exceptions.Timeout()):
            text, call = self.client.ask_with_tools("hello", [{"x": 1}])
        self.assertEqual(text, TIMEOUT_MESSAGE)
        self.assertIsNone(call)

    def test_connection_error_returns_the_stable_message(self):
        with _requests_post(
                        side_effect=requests.exceptions.ConnectionError()):
            text, call = self.client.ask_with_tools("hello", [{"x": 1}])
        self.assertEqual(text, CONNECTION_ERROR_MESSAGE)
        self.assertIsNone(call)

    def test_client_error_never_leaks_the_url(self):
        with _requests_post(
                        side_effect=requests.exceptions.HTTPError(
                            response=_response({}, status=400))):
            text, call = self.client.ask_with_tools("hello", [{"x": 1}])
        self.assertEqual(text, GENERIC_ERROR_MESSAGE)
        self.assertNotIn("127.0.0.1", text)
        self.assertNotIn("http", text)

    def test_transient_server_error_is_retried(self):
        client = OllamaClient(url="http://127.0.0.1:1", retries=1,
                              retry_delay=0)
        responses = [
            _response({}, status=503),
            _response({"message": {"content": "ok"}}),
        ]
        with _requests_post(
                        side_effect=responses) as post:
            text, call = client.ask_with_tools("hello", [{"x": 1}])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(text, "ok")


class ProviderToolFallbackTest(unittest.TestCase):
    """A provider with no tool support must degrade to prose, not crash."""

    class Plain(LLMProvider):
        def ask(self, prompt, history=None, system=None):
            return "plain answer"

        def is_available(self):
            return True

    def test_default_implementation_proposes_nothing(self):
        text, call = self.Plain().ask_with_tools("hi", [{"tool": 1}])
        self.assertEqual(text, "plain answer")
        self.assertIsNone(call)


if __name__ == "__main__":
    unittest.main()
