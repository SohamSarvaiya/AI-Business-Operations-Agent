"""Demo data: ~120 days of orders. Some products trend down, some up. python -m app.seed [--reset]"""
import random
import sys
from datetime import date, timedelta

from sqlalchemy import delete, func, select

from app.db import init_db, write_session
from app.models import Customer, Order, OrderItem, Product, RestockDraft

# sku, name, category, price, stock, reorder_level, base_weight, trend (-ve = declining)
PRODUCTS = [
    ("EL-001", "Wireless Earbuds Pro", "Electronics", 2999, 120, 40, 10, -0.60),
    ("EL-002", "Smart Fitness Band", "Electronics", 1999, 15, 30, 9, 0.50),
    ("EL-003", "Bluetooth Speaker", "Electronics", 2499, 80, 25, 8, -0.45),
    ("EL-004", "USB-C Hub", "Electronics", 1499, 200, 50, 8, 0.0),
    ("HO-001", "Ergonomic Office Chair", "Home & Office", 8999, 25, 10, 3, 0.20),
    ("HO-002", "Desk Mat XL", "Home & Office", 1299, 150, 30, 7, -0.55),
    ("HO-003", "LED Desk Lamp", "Home & Office", 999, 90, 30, 8, 0.0),
    ("FI-001", "Yoga Mat", "Fitness", 799, 8, 25, 9, 0.30),
    ("FI-002", "Resistance Bands Set", "Fitness", 599, 140, 40, 8, -0.35),
    ("FI-003", "Protein Shaker", "Fitness", 349, 300, 60, 8, 0.0),
    ("ST-001", "Notebook Pack", "Stationery", 249, 500, 100, 14, 0.0),
    ("ST-002", "Gel Pen Box", "Stationery", 199, 400, 100, 12, -0.30),
]
REGIONS = ["North", "South", "East", "West", "Central"]


def seed(reset: bool = False, days: int = 120, today: date | None = None, rng_seed: int = 42) -> str:
    init_db()
    today = today or date.today()
    rng = random.Random(rng_seed)
    with write_session() as s:
        if reset:
            for model in (RestockDraft, OrderItem, Order, Customer, Product):
                s.execute(delete(model))
        if s.scalar(select(func.count(Product.id))):
            return "Database already seeded (use --reset to re-create)."
        products = []
        for sku, name, cat, price, stock, reorder, _w, _t in PRODUCTS:
            p = Product(sku=sku, name=name, category=cat, price=price, stock_quantity=stock, reorder_level=reorder)
            s.add(p)
            products.append(p)
        customers = [Customer(name=f"Customer {i:02d}", region=rng.choice(REGIONS)) for i in range(1, 41)]
        s.add_all(customers)
        s.flush()
        for d in range(days, -1, -1):
            day = today - timedelta(days=d)
            weights = [w * max(0.05, 1 + t * (days - d) / days) for (*_x, w, t) in PRODUCTS]
            for _ in range(rng.randint(8, 16)):
                order = Order(customer_id=rng.choice(customers).id, order_date=day,
                              status=rng.choices(["completed", "cancelled", "refunded"], [0.92, 0.05, 0.03])[0])
                s.add(order)
                s.flush()
                for p in set(rng.choices(products, weights=weights, k=rng.choice([1, 1, 2, 3]))):
                    s.add(OrderItem(order_id=order.id, product_id=p.id, quantity=rng.randint(1, 4), unit_price=p.price))
    return "Seeded demo data."


if __name__ == "__main__":
    print(seed(reset="--reset" in sys.argv))
