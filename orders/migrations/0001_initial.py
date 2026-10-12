import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("catalog", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="OrderSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("day", models.DateField(unique=True)),
                ("last_number", models.IntegerField(default=0)),
            ],
            options={"db_table": "orders_ordersequence"},
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order_number", models.CharField(max_length=20, unique=True)),
                ("status", models.CharField(
                    choices=[("DRAFT", "DRAFT"), ("CONFIRMED", "CONFIRMED"), ("DISPATCHED", "DISPATCHED"),
                             ("DELIVERED", "DELIVERED"), ("CANCELLED", "CANCELLED")],
                    db_index=True, default="DRAFT", max_length=12)),
                ("subtotal", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("tax_total", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("grand_total", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("stock_deducted", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("dealer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                             related_name="orders", to="catalog.dealer")),
            ],
            options={"ordering": ["-id"]},
        ),
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField()),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("line_subtotal", models.DecimalField(decimal_places=2, max_digits=14)),
                ("line_tax", models.DecimalField(decimal_places=2, max_digits=14)),
                ("line_total", models.DecimalField(decimal_places=2, max_digits=14)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                            related_name="items", to="orders.order")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                              related_name="order_items", to="catalog.product")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="IdempotencyRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=200, unique=True)),
                ("request_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("order", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                                            to="orders.order")),
            ],
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.UniqueConstraint(fields=("order", "product"), name="uniq_order_product"),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(condition=models.Q(("quantity__gte", 1)), name="orderitem_qty_positive"),
        ),
    ]
