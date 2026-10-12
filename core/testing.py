from decimal import Decimal

from catalog.models import Dealer, Inventory, Product


def make_product(sku="TST-0001", price="100.00", stock=10, name=None, fitment="Universal", category="Brakes"):
    p = Product.objects.create(sku=sku, name=name or f"Test Part {sku}", price=Decimal(price), category=category,
                               brand="Acme", vehicle_fitment=fitment, description="A test part.")
    Inventory.objects.create(product=p, quantity=stock)
    return p


def make_dealer(code="DLR-T1", name="Test Dealer"):
    return Dealer.objects.create(dealer_code=code, name=name, credit_limit=Decimal("100000.00"))
