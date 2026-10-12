from django.db import IntegrityError, transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import APIError
from core.pagination import StandardPagination

from .models import Dealer, Inventory, InventoryAdjustment, Product
from .serializers import (DealerWriteSerializer, ProductWriteSerializer, dealer_dict, product_dict)


def _body(request):
    data = request.data
    if not isinstance(data, dict):
        raise APIError(400, "VALIDATION_ERROR", "Request body must be a JSON object.",
                       [{"field": "", "message": "expected a JSON object"}])
    return data


def get_product_or_404(sku):
    try:
        return Product.objects.select_related("inventory").get(sku=sku)
    except Product.DoesNotExist:
        raise APIError(404, "NOT_FOUND", f"Product {sku} not found.")


class ProductListView(APIView):
    def get(self, request):
        qs = Product.objects.select_related("inventory").order_by("sku")
        q = request.query_params
        if q.get("search"):
            s = q["search"]
            from django.db.models import Q
            qs = qs.filter(Q(sku__icontains=s) | Q(name__icontains=s) | Q(brand__icontains=s))
        if q.get("category"):
            qs = qs.filter(category=q["category"])
        if q.get("vehicle"):
            qs = qs.filter(vehicle_fitment__icontains=q["vehicle"])
        pager = StandardPagination()
        page = pager.paginate_queryset(qs, request, view=self)
        return pager.get_paginated_response([product_dict(p) for p in page])

    def post(self, request):
        ser = ProductWriteSerializer(data=_body(request))
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            with transaction.atomic():
                if Product.objects.filter(sku=d["sku"]).exists():
                    raise IntegrityError
                p = Product.objects.create(**d)
                Inventory.objects.create(product=p, quantity=0)
        except IntegrityError:
            raise APIError(409, "DUPLICATE", f"A product with SKU {d['sku']} already exists.")
        return Response(product_dict(get_product_or_404(p.sku)), status=201)


class ProductDetailView(APIView):
    def get(self, request, sku):
        return Response(product_dict(get_product_or_404(sku)))

    def patch(self, request, sku):
        p = get_product_or_404(sku)
        body = _body(request)
        if "sku" in body and body["sku"] != p.sku:
            raise APIError(400, "VALIDATION_ERROR", "SKU cannot be changed.",
                           [{"field": "sku", "message": "SKU cannot be changed."}])
        merged = {k: getattr(p, k) for k in ("sku", "name", "category", "brand", "vehicle_fitment", "price", "description")}
        merged.update({k: v for k, v in body.items() if k in merged})
        ser = ProductWriteSerializer(data={**merged, "price": body.get("price", f"{p.price:.2f}")})
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        with transaction.atomic():
            p = Product.objects.select_for_update().get(pk=p.pk)
            for k in ("name", "category", "brand", "vehicle_fitment", "price", "description"):
                setattr(p, k, d[k])
            p.save()
        return Response(product_dict(get_product_or_404(sku)))


class InventoryView(APIView):
    def put(self, request, sku):
        body = _body(request)
        q = body.get("quantity")
        if isinstance(q, bool) or not isinstance(q, int) or q < 0:
            get_product_or_404(sku)  # unknown SKU is a 404 even with a bad body
            raise APIError(400, "VALIDATION_ERROR", "quantity must be an integer >= 0.",
                           [{"field": "quantity", "message": "must be an integer >= 0"}])
        reason = body.get("reason", "")
        reason = reason if isinstance(reason, str) else str(reason)
        with transaction.atomic():
            try:
                inv = Inventory.objects.select_for_update().select_related("product").get(product__sku=sku)
            except Inventory.DoesNotExist:
                raise APIError(404, "NOT_FOUND", f"Product {sku} not found.")
            InventoryAdjustment.objects.create(product=inv.product, old_quantity=inv.quantity,
                                               new_quantity=q, reason=reason[:255])
            inv.quantity = q
            inv.save()
        return Response({"sku": sku, "quantity": q})


class DealerListView(APIView):
    def get(self, request):
        pager = StandardPagination()
        page = pager.paginate_queryset(Dealer.objects.order_by("id"), request, view=self)
        return pager.get_paginated_response([dealer_dict(d) for d in page])

    def post(self, request):
        ser = DealerWriteSerializer(data=_body(request))
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            with transaction.atomic():
                if Dealer.objects.filter(dealer_code=d["dealer_code"]).exists():
                    raise IntegrityError
                dealer = Dealer.objects.create(**d)
        except IntegrityError:
            raise APIError(409, "DUPLICATE", f"Dealer code {d['dealer_code']} already exists.")
        return Response(dealer_dict(dealer), status=201)


class DealerDetailView(APIView):
    def get(self, request, pk):
        try:
            return Response(dealer_dict(Dealer.objects.get(pk=pk)))
        except Dealer.DoesNotExist:
            raise APIError(404, "NOT_FOUND", f"Dealer {pk} not found.")
