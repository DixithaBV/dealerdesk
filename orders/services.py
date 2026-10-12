"""Order business rules. Every state change runs inside one transaction and locks the rows it touches:
order row first, then inventory rows in ascending product_id order (a fixed order prevents deadlocks)."""
import hashlib
import json
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from catalog.models import Dealer, Inventory, Product
from core.exceptions import APIError

from .models import IdempotencyRecord, Order, OrderItem
from .money import fmt, line_amounts

IST = ZoneInfo("Asia/Kolkata")
TRANSITIONS = {"confirm": ("DRAFT", "CONFIRMED"), "dispatch": ("CONFIRMED", "DISPATCHED"),
               "deliver": ("DISPATCHED", "DELIVERED")}


# ------------------------------------------------------------------ validation
def _bad(message, details):
    raise APIError(400, "VALIDATION_ERROR", message, details)


def validate_items(items):
    """Shape checks only (no DB). Returns [(sku, qty)]."""
    errs = []
    if not isinstance(items, list) or not items:
        _bad("At least one item is required.", [{"field": "items", "message": "at least one item is required"}])
    out, seen = [], set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            errs.append({"field": f"items[{i}]", "message": "must be an object"}); continue
        sku, qty = it.get("sku"), it.get("quantity")
        if not isinstance(sku, str) or not sku.strip():
            errs.append({"field": f"items[{i}].sku", "message": "sku is required"}); continue
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            errs.append({"field": f"items[{i}].quantity", "message": "quantity must be an integer >= 1"}); continue
        if sku in seen:
            errs.append({"field": f"items[{i}].sku", "message": f"duplicate SKU {sku}"}); continue
        seen.add(sku)
        out.append((sku, qty))
    if errs:
        _bad("; ".join(e["message"] for e in errs), errs)
    return out


def resolve_products(pairs):
    products = {p.sku: p for p in Product.objects.filter(sku__in=[s for s, _ in pairs])}
    unknown = [s for s, _ in pairs if s not in products]
    if unknown:
        _bad("Unknown SKU: " + ", ".join(unknown), [{"field": "items.sku", "message": f"unknown SKU {s}"} for s in unknown])
    return products


# ------------------------------------------------------------------ order numbers
def next_order_number(now=None):
    """ORD-YYYYMMDD-NNNN (IST date). One atomic upsert; the row lock serialises concurrent creators."""
    day = (now or timezone.now()).astimezone(IST).date()
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO orders_ordersequence (day, last_number) VALUES (%s, 1) "
            "ON CONFLICT (day) DO UPDATE SET last_number = orders_ordersequence.last_number + 1 "
            "RETURNING last_number", [day])
        n = cur.fetchone()[0]
    return f"ORD-{day:%Y%m%d}-{n:04d}"


# ------------------------------------------------------------------ serialisation
def _lines(order):
    """DRAFT orders always show the product's CURRENT price; other statuses show the stored (locked) price."""
    for it in order.items.all():  # (prefetch items__product in the caller)
        if order.status == Order.DRAFT:
            price = it.product.price
            sub, tax, tot = line_amounts(price, it.quantity)
        else:
            price, sub, tax, tot = it.unit_price, it.line_subtotal, it.line_tax, it.line_total
        yield it, price, sub, tax, tot


def order_dict(order):
    items, S, T = [], Decimal("0"), Decimal("0")
    for it, price, sub, tax, tot in _lines(order):
        S, T = S + sub, T + tax
        items.append({"sku": it.product.sku, "name": it.product.name, "quantity": it.quantity,
                      "unit_price": fmt(price), "line_subtotal": fmt(sub), "line_tax": fmt(tax), "line_total": fmt(tot)})
    loc = lambda d: timezone.localtime(d, IST).isoformat()
    return {"order_number": order.order_number, "dealer_id": order.dealer_id, "status": order.status, "items": items,
            "subtotal": fmt(S), "tax_total": fmt(T), "grand_total": fmt(S + T),
            "created_at": loc(order.created_at), "updated_at": loc(order.updated_at)}


def load_order(order_number):
    try:
        return Order.objects.prefetch_related("items__product").get(order_number=order_number)
    except Order.DoesNotExist:
        raise APIError(404, "NOT_FOUND", f"Order {order_number} not found.")


def _persist_totals(order, amounts):
    """amounts: [(line_subtotal, line_tax), ...]"""
    S = sum((a[0] for a in amounts), Decimal("0")); T = sum((a[1] for a in amounts), Decimal("0"))
    order.subtotal, order.tax_total, order.grand_total = S, T, S + T


# ------------------------------------------------------------------ create / edit
def _request_hash(dealer_id, pairs):
    canon = json.dumps({"dealer_id": dealer_id, "items": sorted([[s, q] for s, q in pairs])}, sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()


def create_order(dealer_id, items, idempotency_key=None):
    """Returns (order_number, created_new). Raises APIError."""
    if isinstance(dealer_id, bool) or not isinstance(dealer_id, int):
        _bad("dealer_id must be an integer.", [{"field": "dealer_id", "message": "dealer_id must be an integer"}])
    pairs = validate_items(items)
    h = _request_hash(dealer_id, pairs)
    with transaction.atomic():
        if idempotency_key:
            try:
                with transaction.atomic():  # savepoint: a concurrent duplicate blocks here until the first commits
                    IdempotencyRecord.objects.create(key=idempotency_key, request_hash=h)
            except IntegrityError:
                rec = IdempotencyRecord.objects.get(key=idempotency_key)
                if rec.request_hash != h:
                    raise APIError(409, "IDEMPOTENCY_CONFLICT", "Idempotency-Key was already used with a different request body.")
                return rec.order.order_number, False
        if not Dealer.objects.filter(pk=dealer_id).exists():
            _bad(f"Unknown dealer {dealer_id}.", [{"field": "dealer_id", "message": "unknown dealer"}])
        products = resolve_products(pairs)
        order = Order(order_number=next_order_number(), dealer_id=dealer_id)
        amounts = [line_amounts(products[s].price, q) for s, q in pairs]  # (sub, tax, total)
        _persist_totals(order, amounts)
        order.save()
        OrderItem.objects.bulk_create([
            OrderItem(order=order, product=products[s], quantity=q, unit_price=products[s].price,
                      line_subtotal=a[0], line_tax=a[1], line_total=a[2]) for (s, q), a in zip(pairs, amounts)])
        if idempotency_key:
            IdempotencyRecord.objects.filter(key=idempotency_key).update(order=order)
    return order.order_number, True


def replace_items(order_number, items):
    pairs = validate_items(items)
    with transaction.atomic():
        order = _lock(order_number)
        if order.status != Order.DRAFT:
            raise APIError(409, "ORDER_LOCKED", f"Order {order_number} is {order.status} and can no longer be edited.")
        products = resolve_products(pairs)
        order.items.all().delete()
        rows, lines = [], []
        for s, q in pairs:
            sub, tax, tot = line_amounts(products[s].price, q)
            lines.append((sub, tax))
            rows.append(OrderItem(order=order, product=products[s], quantity=q, unit_price=products[s].price,
                                  line_subtotal=sub, line_tax=tax, line_total=tot))
        OrderItem.objects.bulk_create(rows)
        _persist_totals(order, lines)
        order.save()
    return order_number


def _lock(order_number):
    try:
        return Order.objects.select_for_update().get(order_number=order_number)
    except Order.DoesNotExist:
        raise APIError(404, "NOT_FOUND", f"Order {order_number} not found.")


def _invalid(order, action):
    raise APIError(409, "INVALID_TRANSITION", f"Cannot {action} an order that is {order.status}.")


# ------------------------------------------------------------------ lifecycle
def confirm(order_number):
    with transaction.atomic():
        order = _lock(order_number)
        if order.status != Order.DRAFT:
            _invalid(order, "confirm")
        items = list(order.items.select_related("product").order_by("product_id"))
        inv = {i.product_id: i for i in
               Inventory.objects.select_for_update().filter(product_id__in=[it.product_id for it in items]).order_by("product_id")}
        short = [{"sku": it.product.sku, "requested": it.quantity, "available": inv[it.product_id].quantity if it.product_id in inv else 0}
                 for it in items if (inv[it.product_id].quantity if it.product_id in inv else 0) < it.quantity]
        if short:
            names = {it.product.sku: it.product.name for it in items}
            msg = ". ".join(f"Insufficient stock for {names[s['sku']]}. Available: {s['available']}, Requested: {s['requested']}"
                            for s in short)
            raise APIError(409, "INSUFFICIENT_STOCK", msg, short)
        lines = []
        for it in items:
            inv[it.product_id].quantity -= it.quantity
            inv[it.product_id].save(update_fields=["quantity", "updated_at"])
            it.unit_price = it.product.price  # price locked from here on
            it.line_subtotal, it.line_tax, it.line_total = line_amounts(it.unit_price, it.quantity)
            it.save()
            lines.append((it.line_subtotal, it.line_tax))
        _persist_totals(order, lines)
        order.status, order.stock_deducted = Order.CONFIRMED, True
        order.save()
    return order_number


def cancel(order_number):
    with transaction.atomic():
        order = _lock(order_number)
        if order.status == Order.DRAFT:
            pass
        elif order.status == Order.CONFIRMED:
            if order.stock_deducted:
                items = list(order.items.order_by("product_id"))
                inv = Inventory.objects.select_for_update().filter(product_id__in=[i.product_id for i in items]).order_by("product_id")
                by_pid = {i.product_id: i for i in inv}
                for it in items:
                    by_pid[it.product_id].quantity += it.quantity
                    by_pid[it.product_id].save(update_fields=["quantity", "updated_at"])
                order.stock_deducted = False
        else:
            _invalid(order, "cancel")
        order.status = Order.CANCELLED
        order.save()
    return order_number


def advance(order_number, action):
    src, dst = TRANSITIONS[action]
    with transaction.atomic():
        order = _lock(order_number)
        if order.status != src:
            _invalid(order, action)
        order.status = dst
        order.save()
    return order_number
