from decimal import Decimal

from rest_framework import serializers

from .models import Dealer, Product

PRICE = dict(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), coerce_to_string=True)


def product_dict(p, stock=None):
    inv = getattr(p, "inventory", None)
    return {
        "sku": p.sku, "name": p.name, "category": p.category, "brand": p.brand,
        "vehicle_fitment": p.vehicle_fitment, "price": f"{p.price:.2f}",
        "stock": stock if stock is not None else (inv.quantity if inv else 0),
        "description": p.description,
    }


def dealer_dict(d):
    return {"id": d.id, "dealer_code": d.dealer_code, "name": d.name, "city": d.city, "phone": d.phone,
            "email": d.email, "gstin": d.gstin, "credit_limit": f"{d.credit_limit:.2f}"}


class ProductWriteSerializer(serializers.Serializer):
    sku = serializers.CharField(max_length=40)
    name = serializers.CharField(max_length=255)
    category = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    brand = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    vehicle_fitment = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    price = serializers.DecimalField(**PRICE)
    description = serializers.CharField(required=False, allow_blank=True, default="")


class DealerWriteSerializer(serializers.Serializer):
    dealer_code = serializers.CharField(max_length=40)
    name = serializers.CharField(max_length=255)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    email = serializers.CharField(max_length=254, required=False, allow_blank=True, default="")
    gstin = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    credit_limit = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"),
                                            required=False, default=Decimal("0.00"))
