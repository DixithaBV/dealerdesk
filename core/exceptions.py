"""One consistent error shape: {"error": {"code", "message", "details"}} (contract section 3)."""
from django.http import Http404
from rest_framework import exceptions as drf
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler


class APIError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or []


def error_response(status, code, message, details=None):
    return Response({"error": {"code": code, "message": message, "details": details or []}}, status=status)


def _flatten(detail, prefix=""):
    """Turn DRF's nested validation errors into [{"field": ..., "message": ...}]."""
    out = []
    if isinstance(detail, dict):
        for k, v in detail.items():
            out.extend(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(detail, list):
        for i, v in enumerate(detail):
            if isinstance(v, (dict, list)):
                out.extend(_flatten(v, f"{prefix}[{i}]"))
            else:
                out.append({"field": prefix, "message": str(v)})
    else:
        out.append({"field": prefix, "message": str(detail)})
    return out


def api_exception_handler(exc, context):
    if isinstance(exc, APIError):
        return error_response(exc.status, exc.code, exc.message, exc.details)
    if isinstance(exc, drf.ValidationError):
        details = _flatten(exc.detail)
        msg = "; ".join(f"{d['field']}: {d['message']}" if d["field"] else d["message"] for d in details) or "Invalid input"
        return error_response(400, "VALIDATION_ERROR", msg, details)
    if isinstance(exc, (Http404, drf.NotFound)):
        return error_response(404, "NOT_FOUND", "The requested resource was not found.")
    if isinstance(exc, drf.ParseError):
        return error_response(400, "VALIDATION_ERROR", "Malformed JSON body.")
    if isinstance(exc, drf.UnsupportedMediaType):
        return error_response(415, "UNSUPPORTED_MEDIA_TYPE", "Send application/json.")
    if isinstance(exc, drf.MethodNotAllowed):
        return error_response(405, "METHOD_NOT_ALLOWED", str(exc.detail))
    resp = drf_default_handler(exc, context)
    if resp is not None:
        return error_response(resp.status_code, "ERROR", str(getattr(exc, "detail", exc)))
    return None  # unknown exceptions become a 500 -> core.views.server_error (JSON)
