"""Money maths in Decimal only. Django-free so it can be unit-tested anywhere."""
from decimal import ROUND_HALF_UP, Decimal

TWO = Decimal("0.01")
GST = Decimal("0.18")


def q2(x: Decimal) -> Decimal:
    return x.quantize(TWO, rounding=ROUND_HALF_UP)


def line_amounts(unit_price: Decimal, quantity: int):
    """(line_subtotal, line_tax, line_total). Tax rounded per line, ROUND_HALF_UP."""
    sub = q2(Decimal(unit_price) * int(quantity))
    tax = q2(sub * GST)
    return sub, tax, sub + tax


def fmt(x: Decimal) -> str:
    return f"{q2(Decimal(x)):.2f}"
