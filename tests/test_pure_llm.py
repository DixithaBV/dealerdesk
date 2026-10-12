"""GeminiClient against a fake HTTP session (no key, no network)."""
import os, sys, time, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from assistant.llm import GeminiClient, LLMError, TOOL_DECLARATIONS, fn_response_part  # noqa: E402


class Resp:
    def __init__(self, status, body):
        self.status_code, self._b, self.text = status, body, str(body)

    def json(self):
        return self._b


class FakeHTTP:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, json=None, timeout=None, headers=None):
        self.calls.append((url, json, headers))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def ok_text(t):
    return Resp(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": t}]}}]})


def ok_call(name, args):
    return Resp(200, {"candidates": [{"content": {"role": "model", "parts": [
        {"functionCall": {"name": name, "args": args}, "thoughtSignature": "sig"}]}}]})


def gen(c):
    return c.generate("sys", [{"role": "user", "parts": [{"text": "hi"}]}], TOOL_DECLARATIONS, time.monotonic() + 30)


class GeminiClientTests(unittest.TestCase):
    def test_request_shape_uses_native_function_calling(self):
        http = FakeHTTP(ok_text("hello"))
        out = gen(GeminiClient("KEY", session=http, sleep=lambda s: None))
        url, body, headers = http.calls[0]
        self.assertIn("generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent", url)
        self.assertEqual(headers["x-goog-api-key"], "KEY")
        names = [d["name"] for d in body["tools"][0]["functionDeclarations"]]
        self.assertEqual(names, ["search_parts", "check_stock", "create_draft_order"])
        self.assertEqual(body["generationConfig"]["temperature"], 0)
        self.assertEqual(out["text"], "hello")

    def test_function_call_parsed_and_raw_content_preserved(self):
        out = gen(GeminiClient("K", session=FakeHTTP(ok_call("check_stock", {"sku": "BRK-1044"})), sleep=lambda s: None))
        self.assertEqual(out["function_calls"], [{"name": "check_stock", "args": {"sku": "BRK-1044"}}])
        self.assertEqual(out["content"]["parts"][0]["thoughtSignature"], "sig")  # echoed back to the model next step

    def test_429_retried_once_and_overload_503_fails_over_to_next_model(self):
        http = FakeHTTP(Resp(429, {}), Resp(503, {}), ok_text("fine"))
        c = GeminiClient("K", session=http, sleep=lambda s: None)
        self.assertEqual(gen(c)["text"], "fine")
        self.assertEqual(len(http.calls), 3)
        self.assertIn("gemini-flash-lite-latest", http.calls[2][0])  # 503 on the first model -> second model

    def test_retired_model_falls_back_to_next(self):
        http = FakeHTTP(Resp(404, {}), ok_text("via fallback"))
        c = GeminiClient("K", session=http, sleep=lambda s: None)
        self.assertEqual(gen(c)["text"], "via fallback")
        self.assertIn("gemini-flash-lite-latest", http.calls[1][0])
        self.assertEqual(c.good_model, "gemini-flash-lite-latest")

    def test_hard_errors_and_missing_key(self):
        with self.assertRaises(LLMError):  # a 400 that no thinking option fixes ends in an error
            gen(GeminiClient("K", session=FakeHTTP(Resp(400, {}), Resp(400, {}), Resp(400, {})), sleep=lambda s: None))
        with self.assertRaises(LLMError):
            GeminiClient("")
        with self.assertRaises(LLMError):
            gen(GeminiClient("K", session=FakeHTTP(Resp(200, {"candidates": []})), sleep=lambda s: None))

    def test_thinking_field_rejected_steps_down_and_is_remembered(self):
        http = FakeHTTP(Resp(400, {"error": "Unknown field thinkingLevel (thinking config not supported)"}),
                        Resp(400, {"error": "Request contains an invalid argument."}), ok_text("ok"), ok_text("again"))
        c = GeminiClient("K", session=http, sleep=lambda s: None)
        self.assertEqual(gen(c)["text"], "ok")
        self.assertEqual(http.calls[0][1]["generationConfig"]["thinkingConfig"], {"thinkingLevel": "minimal"})
        self.assertEqual(http.calls[1][1]["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})
        self.assertNotIn("thinkingConfig", http.calls[2][1]["generationConfig"])
        gen(c)
        self.assertNotIn("thinkingConfig", http.calls[3][1]["generationConfig"])  # remembered

    def test_timeout_retries_once_then_succeeds(self):
        import requests
        http = FakeHTTP(requests.Timeout("slow"), ok_text("fine"))
        self.assertEqual(gen(GeminiClient("K", session=http, sleep=lambda s: None))["text"], "fine")

    def test_function_response_part_shape(self):
        p = fn_response_part("check_stock", {"a": 1})
        self.assertEqual(p, {"functionResponse": {"name": "check_stock", "response": {"result": {"a": 1}}}})


if __name__ == "__main__":
    unittest.main()
