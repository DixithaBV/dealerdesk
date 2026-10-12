from django.conf import settings
from django.http import HttpResponse, JsonResponse


def health(request):
    """GET /api/health/ — the grader polls this until your app is ready."""
    return JsonResponse({"status": "ok"})


def _err(status, code, message):
    return JsonResponse({"error": {"code": code, "message": message, "details": []}}, status=status)


def not_found(request, exception=None):
    return _err(404, "NOT_FOUND", "The requested resource was not found.")


def server_error(request):
    return _err(500, "INTERNAL_ERROR", "Unexpected server error.")


def portal(request):
    """Optional dealer portal (frontend/index.html), served same-origin so it needs no CORS."""
    return HttpResponse((settings.BASE_DIR / "frontend" / "index.html").read_text(encoding="utf-8"), content_type="text/html")
