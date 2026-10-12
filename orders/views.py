from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import APIError
from core.pagination import StandardPagination

from . import services as svc
from .models import Order


def _body(request):
    if not isinstance(request.data, dict):
        raise APIError(400, "VALIDATION_ERROR", "Request body must be a JSON object.",
                       [{"field": "", "message": "expected a JSON object"}])
    return request.data


class OrderListView(APIView):
    def get(self, request):
        qs = Order.objects.prefetch_related("items__product").order_by("-id")
        q = request.query_params
        if q.get("dealer_id"):
            if not q["dealer_id"].isdigit():
                raise APIError(400, "VALIDATION_ERROR", "dealer_id must be an integer.",
                               [{"field": "dealer_id", "message": "must be an integer"}])
            qs = qs.filter(dealer_id=int(q["dealer_id"]))
        if q.get("status"):
            st = q["status"].upper()
            if st not in dict(Order.STATUSES):
                raise APIError(400, "VALIDATION_ERROR", f"Unknown status {q['status']}.",
                               [{"field": "status", "message": "unknown status"}])
            qs = qs.filter(status=st)
        pager = StandardPagination()
        page = pager.paginate_queryset(qs, request, view=self)
        return pager.get_paginated_response([svc.order_dict(o) for o in page])

    def post(self, request):
        body = _body(request)
        number, created = svc.create_order(body.get("dealer_id"), body.get("items"),
                                           request.headers.get("Idempotency-Key") or None)
        return Response(svc.order_dict(svc.load_order(number)), status=201 if created else 200)


class OrderDetailView(APIView):
    def get(self, request, order_number):
        return Response(svc.order_dict(svc.load_order(order_number)))

    def put(self, request, order_number):
        svc.load_order(order_number)  # 404 first
        svc.replace_items(order_number, _body(request).get("items"))
        return Response(svc.order_dict(svc.load_order(order_number)))


class OrderActionView(APIView):
    action = None

    def post(self, request, order_number):
        if self.action == "cancel":
            svc.cancel(order_number)
        elif self.action == "confirm":
            svc.confirm(order_number)
        else:
            svc.advance(order_number, self.action)
        return Response(svc.order_dict(svc.load_order(order_number)))
