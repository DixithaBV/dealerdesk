from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Dealer
from core.exceptions import APIError

from . import engine
from .llm import GeminiClient, LLMError

_client = {"c": None}


def get_llm():
    """Production LLM: Gemini with native function calling. (Tests patch this function with a scripted fake.)"""
    if _client["c"] is None:
        _client["c"] = GeminiClient(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)
    return _client["c"]


class ChatView(APIView):
    def post(self, request):
        b = request.data if isinstance(request.data, dict) else {}
        errs = []
        sid, msg, did = b.get("session_id"), b.get("message"), b.get("dealer_id")
        if not isinstance(sid, str) or not sid.strip() or len(sid) > 200:
            errs.append({"field": "session_id", "message": "session_id is required (string)"})
        if not isinstance(msg, str) or not msg.strip():
            errs.append({"field": "message", "message": "message is required (non-empty string)"})
        elif len(msg) > 2000:
            errs.append({"field": "message", "message": "message is too long (max 2000 characters)"})
        if did is not None:
            if isinstance(did, bool) or not isinstance(did, int) or not Dealer.objects.filter(pk=did).exists():
                errs.append({"field": "dealer_id", "message": "unknown dealer"})
        if errs:
            raise APIError(400, "VALIDATION_ERROR", "; ".join(e["message"] for e in errs), errs)
        try:
            llm = get_llm()
        except LLMError:
            return Response({"reply": "The assistant is not configured on this server (GEMINI_API_KEY is missing).",
                             "cited_skus": [], "tool_calls": [], "actions": []})
        return Response(engine.run_turn(sid.strip(), did, msg.strip(), llm))
