from django.db import models

from catalog.models import Dealer, Product


class Order(models.Model):
    DRAFT, CONFIRMED, DISPATCHED, DELIVERED, CANCELLED = "DRAFT", "CONFIRMED", "DISPATCHED", "DELIVERED", "CANCELLED"
    STATUSES = [(s, s) for s in (DRAFT, CONFIRMED, DISPATCHED, DELIVERED, CANCELLED)]

    order_number = models.CharField(max_length=20, unique=True)
    dealer = models.ForeignKey(Dealer, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=12, choices=STATUSES, default=DRAFT, db_index=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    stock_deducted = models.BooleanField(default=False)  # guards "restore stock exactly once"
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    line_tax = models.DecimalField(max_digits=14, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="uniq_order_product"),
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name="orderitem_qty_positive"),
        ]


class OrderSequence(models.Model):
    """Per-day counter. Incremented with a single atomic INSERT .. ON CONFLICT .. DO UPDATE."""
    day = models.DateField(unique=True)
    last_number = models.IntegerField(default=0)

    class Meta:
        db_table = "orders_ordersequence"


class IdempotencyRecord(models.Model):
    key = models.CharField(max_length=200, unique=True)
    request_hash = models.CharField(max_length=64)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
