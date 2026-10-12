from django.db import models


class Product(models.Model):
    sku = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True, db_index=True)
    brand = models.CharField(max_length=100, blank=True, db_index=True)
    vehicle_fitment = models.CharField(max_length=150, blank=True, db_index=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sku"]
        constraints = [models.CheckConstraint(condition=models.Q(price__gt=0), name="product_price_positive")]

    def __str__(self):
        return self.sku


class Inventory(models.Model):
    """One row per product; the row is locked (SELECT ... FOR UPDATE) whenever stock changes."""
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="inventory")
    quantity = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gte=0), name="inventory_non_negative")]


class InventoryAdjustment(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="adjustments")
    old_quantity = models.IntegerField()
    new_quantity = models.IntegerField()
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Dealer(models.Model):
    dealer_code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=255)
    city = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.CharField(max_length=254, blank=True)
    gstin = models.CharField(max_length=20, blank=True)
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
