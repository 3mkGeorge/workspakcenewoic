"""Optional, clearly identified sample data. Never runs during normal startup."""

import random
from datetime import timedelta
from uuid import uuid4
from flask import g
from werkzeug.datastructures import MultiDict
from models import (
    Category,
    Customer,
    Expense,
    Product,
    Purchase,
    PurchaseItem,
    Sale,
    Supplier,
    db,
    now,
)
from services.core import audit, move, save_setting
from services.sales import next_number, receive_purchase, write_sale


def seed_demo(user):
    if Product.query.first() or Sale.query.first() or Purchase.query.first():
        raise ValueError(
            "Demo data can only be loaded into an empty catalog and ledger."
        )
    g.user = user
    rng = random.Random(42)
    suppliers = [
        Supplier(name=n, phone=f"+20 2 2456 {1000 + i}", address="Cairo, Egypt")
        for i, n in enumerate(
            ["TechWorld Supplies", "Global Electronics", "SmartBuy Co.", "Gadget Hub"]
        )
    ]
    db.session.add_all(suppliers)
    names = [
        "Gaming",
        "Keyboards",
        "Monitors",
        "Audio",
        "Storage",
        "Graphics Cards",
        "Processors",
        "Laptops",
        "Phones",
    ]
    categories = {n: Category(name=n) for n in names}
    db.session.add_all(categories.values())
    customers = [
        Customer(name=n, phone=f"+20 10 1234 {1000 + i}")
        for i, n in enumerate(
            [
                "Ahmed Ali",
                "Sara Hassan",
                "Mohamed Hassan",
                "Omar Khaled",
                "Nour Ahmed",
                "Ali Mahmoud",
                "Mona Said",
                "Laila Hussein",
            ]
        )
    ]
    db.session.add_all(customers)
    db.session.flush()
    rows = [
        ("Logitech G Pro X2", "LGPX2-001", "Gaming", 800, 1200, 34),
        ("Razer DeathAdder V3", "RZ-DA-003", "Gaming", 550, 800, 28),
        ("Keychron K2", "KC-K2-001", "Keyboards", 400, 650, 25),
        ("Samsung 27″ Monitor", "SM-27-005", "Monitors", 1200, 1800, 18),
        ("HyperX Cloud II", "HX-C2-004", "Audio", 750, 1200, 16),
        ("Samsung 1TB SSD", "SM-SSD-1T", "Storage", 700, 1100, 5),
        ("NVIDIA RTX 4060", "NV-4060-008", "Graphics Cards", 3100, 4200, 3),
        ("Intel i5-13600K", "INT-13600K", "Processors", 2400, 3200, 0),
        ("Lenovo IdeaPad 3", "LV-IP3-009", "Laptops", 5200, 6990, 4),
        ("iPhone 15", "APL-IP15-010", "Phones", 6400, 7990, 7),
    ]
    products = []
    from pathlib import Path
    from flask import current_app
    import shutil

    for index, (name, sku, cat, cost, price, stock) in enumerate(rows):
        image_name = f"{index + 1:032x}.png"
        source = Path(__file__).resolve().parents[1] / "static/images" / image_name
        if source.exists():
            shutil.copy2(
                source, current_app.config["ROOT"] / "static/uploads" / image_name
            )
        p = Product(
            name=name,
            sku=sku,
            barcode=str(5099206109000 + index),
            category_id=categories[cat].id,
            supplier_id=suppliers[index % 4].id,
            cost=cost * 100,
            price=price * 100,
            stock=0,
            minimum=5,
            location=f"{chr(65 + index // 3)}1-0{index % 3 + 1}",
            brand=name.split()[0],
            image=image_name if source.exists() else "",
        )
        db.session.add(p)
        db.session.flush()
        if source.exists():
            from services.product_media import migrate_legacy

            migrate_legacy(p)
            db.session.flush()
        products.append(p)
        move(p, 100, "Opening stock", "Optional demonstration data")
    for day in range(13, -1, -1):
        for count in range(rng.randint(1, 4)):
            chosen = rng.sample(products[:5], rng.randint(1, 3))
            form = MultiDict(
                [
                    ("token", uuid4().hex),
                    ("customer_id", str(rng.choice(customers).id)),
                    ("payment", rng.choice(["Cash", "Card"])),
                    ("discount", "0"),
                ]
                + [
                    (k, v)
                    for p in chosen
                    for k, v in [
                        ("product_id", str(p.id)),
                        ("quantity", str(rng.randint(1, 2))),
                    ]
                ]
            )
            sale = write_sale(form)
            sale.created_at = now() - timedelta(days=day, hours=count)
    for i in range(8):
        supplier = suppliers[i % 4]
        p = products[i % 5]
        order = Purchase(
            invoice=next_number(Purchase, "PO-"),
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            total=(i + 2) * p.cost,
            currency="EGP",
            token=uuid4().hex,
            created_at=now() - timedelta(days=i),
            status="Pending",
        )
        order.items.append(
            PurchaseItem(product_id=p.id, name=p.name, quantity=i + 2, cost=p.cost)
        )
        db.session.add(order)
        db.session.flush()
        if i not in (3, 4, 6):
            receive_purchase(order)
        elif i == 3:
            order.status = "Processing"
        elif i == 6:
            order.status = "Cancelled"
    for p, row in zip(products, rows):
        difference = row[-1] - p.stock
        if difference:
            move(p, difference, "Adjustment", "Demo ending balance")
    db.session.add(
        Expense(
            description="Store utilities — demonstration expense",
            amount=82000,
            currency="EGP",
        )
    )
    save_setting("store_name", "StorePro")
    save_setting("address", "Cairo, Egypt")
    audit("Load demo data", "Optional example catalog and ledger loaded")
    db.session.commit()
