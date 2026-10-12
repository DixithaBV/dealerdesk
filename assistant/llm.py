"""Google Gemini client over the official REST endpoint (generativelanguage.googleapis.com, v1beta
`generateContent` with native function calling). Plain `requests`, so there is no SDK version to drift and the
whole client can be tested with a fake HTTP session. Django-free."""
import time

import requests

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Tried in order. GEMINI_MODEL (if set) goes first; the rest only matter if a model name is retired for new users (404).
DEFAULT_MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-flash-latest", "gemini-2.5-flash"]
# "Thinking" makes tool-calling replies slow (30 s+ on some models). Ask for the lowest setting; if the model rejects
# a field (any HTTP 400) the client steps to the next option and remembers it.
THINKING_OPTIONS = [{"thinkingLevel": "minimal"}, {"thinkingLevel": "low"}, None]
REQUEST_TIMEOUT = 30


class LLMError(Exception):
    pass


class GeminiClient:
    def __init__(self, api_key, model=None, session=None, sleep=time.sleep):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        self.key = api_key
        self.models = list(dict.fromkeys(([model] if model else []) + DEFAULT_MODELS))
        self.http = session or requests.Session()
        self.sleep = sleep
        self.good_model = None  # remember the model that worked
        self.think_idx = 0      # index into THINKING_OPTIONS that the API accepted

    def _body(self, system, contents, tool_declarations):
        gen = {"temperature": 0, "maxOutputTokens": 2048}
        if THINKING_OPTIONS[self.think_idx] is not None:
            gen["thinkingConfig"] = THINKING_OPTIONS[self.think_idx]
        return {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "tools": [{"functionDeclarations": tool_declarations}],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
            "generationConfig": gen,
        }

    def generate(self, system, contents, tool_declarations, deadline):
        """-> {"text": str, "function_calls": [{"name","args"}], "content": <raw model content to echo back>}"""
        last = "no attempt made"
        models = [self.good_model] + [m for m in self.models if m != self.good_model] if self.good_model else self.models
        for model in models:
            attempt = 0
            while attempt < 3:
                remaining = deadline - time.monotonic()
                if remaining < 3:
                    raise LLMError("time budget exhausted: " + last)
                try:
                    r = self.http.post(API.format(model=model), json=self._body(system, contents, tool_declarations),
                                       timeout=min(REQUEST_TIMEOUT, remaining),
                                       headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
                except requests.RequestException as e:
                    last = f"network error: {e}"
                    attempt += 1
                    self.sleep(min(1.0 * attempt, 3))
                    continue
                if r.status_code == 200:
                    self.good_model = model
                    return self._parse(r.json())
                last = f"{model} HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code == 400 and self.think_idx < len(THINKING_OPTIONS) - 1:
                    self.think_idx += 1  # this model does not accept that thinking field: try the next option
                    continue
                attempt += 1
                if r.status_code in (500, 502, 503, 504):
                    break  # model overloaded / erroring: fail over to the next candidate straight away
                if r.status_code == 429:
                    if attempt >= 2:
                        break  # still rate limited after one short pause: next candidate
                    self.sleep(2.0)
                    continue
                if r.status_code == 404:
                    break  # unknown / retired model name -> try the next candidate
                raise LLMError(last)  # 400 / 401 / 403: retrying cannot help
        raise LLMError(last)

    @staticmethod
    def _parse(data):
        cands = data.get("candidates") or []
        if not cands:
            raise LLMError(f"no candidates: {str(data.get('promptFeedback', data))[:200]}")
        content = cands[0].get("content") or {}
        parts = content.get("parts") or []
        text = "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))
        calls = [{"name": p["functionCall"].get("name"), "args": p["functionCall"].get("args") or {}}
                 for p in parts if "functionCall" in p]
        if not text.strip() and not calls:
            raise LLMError(f"empty response (finishReason={cands[0].get('finishReason')})")
        return {"text": text.strip(), "function_calls": calls, "content": {"role": "model", "parts": parts}}


def fn_response_part(name, result):
    return {"functionResponse": {"name": name, "response": {"result": result}}}


TOOL_DECLARATIONS = [
    {"name": "search_parts",
     "description": "Search the DealerDesk catalogue for parts. Returns SKUs that fit the vehicle (or universal parts), "
                    "with live price. Use this first for any part request.",
     "parameters": {"type": "OBJECT", "properties": {
         "query": {"type": "STRING", "description": "The part wanted, e.g. 'brake pads', 'engine oil 10W30'"},
         "vehicle": {"type": "STRING", "description": "Vehicle make/model if the dealer said one, e.g. 'Bajaj Pulsar 150'"},
         "category": {"type": "STRING", "description": "Optional category hint, e.g. 'Brakes'"}},
         "required": ["query"]}},
    {"name": "check_stock",
     "description": "Get the exact live stock quantity and current unit price for ONE SKU. Use it whenever a quantity "
                    "or availability number is needed, and before creating an order.",
     "parameters": {"type": "OBJECT", "properties": {
         "sku": {"type": "STRING", "description": "Exact SKU such as BRK-1044"},
         "quantity": {"type": "INTEGER", "description": "Optional quantity the dealer wants, to test availability"}},
         "required": ["sku"]}},
    {"name": "create_draft_order",
     "description": "Create a DRAFT order for the current dealer. Only when the dealer clearly asks to order / reserve "
                    "specific SKUs and quantities. Cannot confirm, dispatch or cancel orders.",
     "parameters": {"type": "OBJECT", "properties": {
         "items": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
             "sku": {"type": "STRING"}, "quantity": {"type": "INTEGER"}}, "required": ["sku", "quantity"]}}},
         "required": ["items"]}},
]
