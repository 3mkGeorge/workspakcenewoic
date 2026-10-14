from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from flask import request
from models import Category, Expense, Product, Purchase, Sale, db


def local_today():
    return datetime.now(ZoneInfo("Africa/Cairo")).date()


def bounds(start, end):
    zone = ZoneInfo("Africa/Cairo")
    a = (
        datetime.combine(start, datetime.min.time(), zone)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    b = (
        datetime.combine(end + timedelta(days=1), datetime.min.time(), zone)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    return a, b


def day_bounds(value):
    """UTC (start, end) of a YYYY-MM-DD store-local day, or None if the value is not a date."""
    try:
        day = datetime.strptime((value or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return bounds(day, day)


def date_range(default_days=30):
    today = local_today()
    try:
        start = datetime.strptime(
            request.args.get("from") or str(today - timedelta(days=default_days - 1)),
            "%Y-%m-%d",
        ).date()
        end = datetime.strptime(request.args.get("to") or str(today), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Choose valid start and end dates.")
    if end < start or (end - start).days > 3660:
        raise ValueError(
            "Choose a date range of no more than 10 years, with the end after the start."
        )
    return start, end


def stock_stats():
    """Calculate inventory summary metrics using SQL aggregates without instantiating ORM objects."""
    row = (
        db.session.query(
            db.func.count(Product.id),
            db.func.coalesce(db.func.sum(Product.stock), 0),
            db.func.coalesce(db.func.sum(Product.stock * Product.cost), 0),
            db.func.coalesce(
                db.func.sum(
                    db.case(
                        (db.and_(Product.stock > 0, Product.stock <= Product.minimum), 1),
                        else_=0,
                    )
                ),
                0,
            ),
            db.func.coalesce(
                db.func.sum(db.case((Product.stock == 0, 1), else_=0)),
                0,
            ),
            db.func.coalesce(
                db.func.sum(db.case((Product.stock > Product.minimum, 1), else_=0)),
                0,
            ),
        )
        .filter(Product.active.is_(True))
        .first()
    )
    count, units, value, low, out, in_stock = row if row else (0, 0, 0, 0, 0, 0)
    return dict(
        products=[],
        count=int(count or 0),
        units=int(units or 0),
        value=int(value or 0),
        low=int(low or 0),
        out=int(out or 0),
        in_stock=int(in_stock or 0),
    )


def sale_stats(sales):
    valid = [s for s in sales if s.status == "Completed"]
    counts = defaultdict(int)
    for s in valid:
        if s.customer_id:
            counts[s.customer_id] += 1
    total = sum(s.total for s in valid)
    return dict(
        total=total,
        count=len(valid),
        average=round(total / len(valid)) if valid else 0,
        units=sum(i.quantity for s in valid for i in s.items),
        returning=sum(n > 1 for n in counts.values()),
        profit=sum(s.subtotal - s.discount - s.cost for s in valid),
    )


def trend(days=7, end=None):
    days = max(1, min(days, 365))
    end = end or local_today()
    start = end - timedelta(days=days - 1)
    a, b = bounds(start, end)
    sales = Sale.query.filter(
        Sale.created_at >= a, Sale.created_at < b, Sale.status == "Completed"
    ).all()
    purchases = Purchase.query.filter(
        Purchase.created_at >= a,
        Purchase.created_at < b,
        Purchase.status != "Cancelled",
    ).all()
    labels = [start + timedelta(days=n) for n in range(days)]

    def group(rows):
        d = defaultdict(int)
        for r in rows:
            day = (
                r.created_at.replace(tzinfo=timezone.utc)
                .astimezone(ZoneInfo("Africa/Cairo"))
                .date()
            )
            d[day] += r.total
        return [d[v] / 100 for v in labels]

    return {
        "labels": [d.strftime("%d %b") for d in labels],
        "datasets": [
            {
                "label": "Sales",
                "data": group(sales),
                "borderColor": "#0965ff",
                "backgroundColor": "#0965ff1a",
                "fill": True,
            },
            {
                "label": "Purchases",
                "data": group(purchases),
                "borderColor": "#8847ff",
                "backgroundColor": "#8847ff12",
                "fill": True,
            },
        ],
    }


def report_data(kind, start, end):
    a, b = bounds(start, end)
    sales = Sale.query.filter(
        Sale.created_at >= a, Sale.created_at < b, Sale.status == "Completed"
    ).all()
    purchases = Purchase.query.filter(
        Purchase.created_at >= a,
        Purchase.created_at < b,
        Purchase.status != "Cancelled",
    ).all()
    if request.args.get("customer_id"):
        from services.core import integer

        customer_id = integer(request.args["customer_id"], 1)
        sales = [s for s in sales if s.customer_id == customer_id]
    if request.args.get("product_id"):
        from services.core import integer

        product_id = integer(request.args["product_id"], 1)
        sales = [s for s in sales if any(i.product_id == product_id for i in s.items)]
        purchases = [
            p for p in purchases if any(i.product_id == product_id for i in p.items)
        ]
    if request.args.get("category_id"):
        from services.core import integer

        category = db.session.get(Category, integer(request.args["category_id"], 1))
        if not category:
            raise ValueError("Unknown category.")

        # Match by the product's category id, so renaming a category keeps its
        # history; the name recorded on the sale line still counts as well.
        def in_category(item):
            if item.product is not None and item.product.category_id == category.id:
                return True
            return getattr(item, "category_name", None) == category.name

        sales = [s for s in sales if any(in_category(i) for i in s.items)]
        purchases = [p for p in purchases if any(in_category(i) for i in p.items)]
    if request.args.get("supplier_id"):
        from services.core import integer

        supplier_id = integer(request.args["supplier_id"], 1)
        purchases = [p for p in purchases if p.supplier_id == supplier_id]
    expenses = Expense.query.filter(
        Expense.created_at >= a, Expense.created_at < b
    ).all()
    stats = sale_stats(sales)
    stats.update(
        purchases=sum(p.total for p in purchases),
        expenses=sum(e.amount for e in expenses),
    )
    stats["net"] = stats["profit"] - stats["expenses"]

    # Period comparison (current period vs preceding period of equal duration)
    try:
        duration = (end - start).days + 1
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=duration - 1)
        pa, pb = bounds(prev_start, prev_end)
        prev_sales = Sale.query.filter(
            Sale.created_at >= pa, Sale.created_at < pb, Sale.status == "Completed"
        ).all()
        prev_purchases = Purchase.query.filter(
            Purchase.created_at >= pa,
            Purchase.created_at < pb,
            Purchase.status != "Cancelled",
        ).all()
        prev_expenses = Expense.query.filter(
            Expense.created_at >= pa, Expense.created_at < pb
        ).all()
        prev_st = sale_stats(prev_sales)
        prev_purch_sum = sum(p.total for p in prev_purchases)
        prev_exp_sum = sum(e.amount for e in prev_expenses)
        prev_net = prev_st["profit"] - prev_exp_sum

        def calc_pct(curr, prev):
            if not prev:
                return 100.0 if curr else 0.0
            return round((curr - prev) * 100.0 / prev, 1)

        def note_str(pct):
            sign = "+" if pct > 0 else ""
            return f"{sign}{pct:.1f}% vs prev period"

        sales_pct = calc_pct(stats["total"], prev_st["total"])
        purchases_pct = calc_pct(stats["purchases"], prev_purch_sum)
        expenses_pct = calc_pct(stats["expenses"], prev_exp_sum)
        net_pct = calc_pct(stats["net"], prev_net)

        stats["comparison"] = {
            "prev_start": prev_start,
            "prev_end": prev_end,
            "sales_pct": sales_pct,
            "purchases_pct": purchases_pct,
            "expenses_pct": expenses_pct,
            "net_pct": net_pct,
            "sales_note": note_str(sales_pct),
            "purchases_note": note_str(purchases_pct),
            "expenses_note": note_str(expenses_pct),
            "net_note": note_str(net_pct),
            "prev_total": prev_st["total"],
            "prev_purchases": prev_purch_sum,
            "prev_expenses": prev_exp_sum,
            "prev_net": prev_net,
        }
    except Exception:
        stats["comparison"] = {
            "sales_note": "",
            "purchases_note": "",
            "expenses_note": "",
            "net_note": "",
            "sales_pct": 0,
            "purchases_pct": 0,
            "expenses_pct": 0,
            "net_pct": 0,
        }
    money_cols = []
    if kind == "sales":
        headers = [
            "Invoice",
            "Date",
            "Customer",
            "Items",
            "Subtotal",
            "Discount",
            "Tax",
            "Shipping",
            "Total",
            "Profit",
        ]
        # Total = Subtotal − Discount + Tax + Shipping; profit is on products only.
        rows = [
            [
                s.invoice,
                s.created_at,
                s.customer_name,
                sum(i.quantity for i in s.items),
                s.subtotal,
                s.discount,
                s.tax,
                s.shipping_charge,
                s.total,
                s.subtotal - s.discount - s.cost,
            ]
            for s in sales
        ]
        money_cols = [4, 5, 6, 7, 8, 9]
    elif kind == "purchases":
        headers = ["Invoice", "Date", "Supplier", "Items", "Status", "Total"]
        rows = [
            [
                p.invoice,
                p.created_at,
                p.supplier_name,
                sum(i.quantity for i in p.items),
                p.status,
                p.total,
            ]
            for p in purchases
        ]
        money_cols = [5]
    elif kind == "inventory":
        headers = [
            "Product",
            "SKU",
            "Category",
            "Stock",
            "Minimum Stock",
            "Cost Price",
            "Selling Price",
            "Total Value (Cost)",
        ]
        from sqlalchemy.orm import joinedload

        query = Product.query.options(joinedload(Product.category)).filter_by(active=True)
        from services.core import integer

        for key, column in [
            ("category_id", Product.category_id),
            ("product_id", Product.id),
            ("supplier_id", Product.supplier_id),
        ]:
            if request.args.get(key):
                query = query.filter(column == integer(request.args[key], 1))
        rows = [
            [
                p.name,
                p.sku,
                p.category.name,
                p.stock,
                p.minimum,
                p.cost,
                p.price,
                p.cost * p.stock,
            ]
            for p in query.all()
        ]
        money_cols = [5, 6, 7]
    elif kind == "products":
        grouped = defaultdict(lambda: [0, 0, 0])
        for s in sales:
            remaining = s.invoice_discount
            discount_base = s.subtotal - sum(item.discount for item in s.items)
            for n, i in enumerate(s.items):
                discount = (
                    remaining
                    if n == len(s.items) - 1
                    else min(
                        remaining,
                        int(
                            (
                                Decimal(remaining)
                                * (i.price * i.quantity - i.discount)
                                / discount_base
                            ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                        ),
                    )
                    if discount_base
                    else 0
                )
                remaining -= discount
                discount_base -= i.price * i.quantity - i.discount
                data = grouped[(i.product_id, i.name, i.category_name)]
                data[0] += i.quantity
                data[1] += i.price * i.quantity - i.discount - discount
                data[2] += i.quantity * i.cost
        headers = [
            "Product",
            "Category",
            "Units Sold",
            "Net sales (excluding VAT)",
            "Profit",
            "Profit Margin",
        ]
        rows = [
            [
                key[1],
                key[2],
                v[0],
                v[1],
                v[1] - v[2],
                f"{(v[1] - v[2]) * 100 / v[1]:.1f}%" if v[1] else "0.0%",
            ]
            for key, v in sorted(grouped.items(), key=lambda kv: kv[1][1], reverse=True)
        ]
        money_cols = [3, 4]
    elif kind in ("customers", "suppliers"):
        grouped = defaultdict(lambda: ["", 0, 0])
        for row in sales if kind == "customers" else purchases:
            key = row.customer_id if kind == "customers" else row.supplier_id
            grouped[key][0] = (
                (row.customer.name if row.customer else row.customer_name)
                if kind == "customers"
                else row.supplier.name
            )
            grouped[key][1] += 1
            grouped[key][2] += row.total
        headers = ["Customer" if kind == "customers" else "Supplier", "Orders", "Total"]
        rows = [v for v in sorted(grouped.values(), key=lambda v: v[2], reverse=True)]
        money_cols = [2]
    elif kind == "profit":
        headers = ["Metric", "Amount"]
        rows = [
            ["Net sales (excluding VAT)", sum(s.subtotal - s.discount for s in sales)],
            ["Cost of goods sold", sum(s.cost for s in sales)],
            ["Gross profit", stats["profit"]],
            ["Expenses", stats["expenses"]],
            ["Net Profit", stats["net"]],
            ["VAT collected", sum(s.tax for s in sales)],
            # Billed to customers; not part of product profit above.
            ["Shipping fees billed", sum(s.shipping_charge for s in sales)],
        ]
        money_cols = [1]
    elif kind == "shipping":
        from services.shipping import report_rows as shipping_rows

        ship = shipping_rows(a, b)
        headers = ["Order", "Invoice", "Customer", "City", "Courier", "Status", "Total"]
        rows = [
            [
                o.order_number,
                o.sale.invoice if o.sale else "—",
                o.customer_name,
                o.city or "—",
                o.courier or "—",
                o.status,
                o.sale.total if o.sale else 0,
            ]
            for o in ship["orders"]
        ]
        money_cols = [6]
        stats["ship"] = ship
    else:
        raise ValueError("Unknown report type.")
    return headers, rows, money_cols, stats


def sales_charts(start, end):
    headers, rows, _, _ = report_data("sales", start, end)
    group = request.args.get("group", "day")
    if group not in ("day", "week", "month"):
        raise ValueError("Choose day, week, or month grouping.")
    if (end - start).days > 180 and group == "day":
        group = "month"
    grouped = defaultdict(lambda: [0, 0])
    for r in rows:
        d = (
            r[1]
            .replace(tzinfo=timezone.utc)
            .astimezone(ZoneInfo("Africa/Cairo"))
            .date()
        )
        label = (
            d.strftime("%Y-%m")
            if group == "month"
            else (d - timedelta(days=d.weekday())).isoformat()
            if group == "week"
            else d.isoformat()
        )
        grouped[label][0] += r[8]  # Total
        grouped[label][1] += r[9]  # Profit
    keys = sorted(grouped)
    chart = {
        "labels": keys,
        "datasets": [
            {
                "label": "Sales",
                "data": [grouped[k][0] / 100 for k in keys],
                "backgroundColor": "#3c88ff",
                "borderColor": "#1671ff",
                "type": "bar",
            },
            {
                "label": "Profit",
                "data": [grouped[k][1] / 100 for k in keys],
                "borderColor": "#22be85",
                "backgroundColor": "#22be85",
                "type": "line",
            },
        ],
    }
    _, products, _, _ = report_data("products", start, end)
    categories = defaultdict(int)
    for r in products:
        categories[r[1]] += r[3]
    category = {
        "labels": list(categories),
        "datasets": [
            {
                "data": [v / 100 for v in categories.values()],
                "backgroundColor": [
                    "#0865ff",
                    "#31c48a",
                    "#ffa317",
                    "#a669fa",
                    "#9bacca",
                    "#e96987",
                    "#5eb9c9",
                    "#896cef",
                    "#a4c943",
                ],
            }
        ],
    }
    return chart, category, products[:10]
