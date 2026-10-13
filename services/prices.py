"""Append-only price snapshots captured in the same transaction as product updates."""

from datetime import timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from flask import g, has_request_context, request
from sqlalchemy import event, select
from models import db, Product, PriceHistory, Setting, now


def percent(old, new):
    if not old:
        return None if new else Decimal("0")
    return (Decimal(new - old) * 100 / old).quantize(
        Decimal(".0001"), rounding=ROUND_HALF_UP
    )


@event.listens_for(Product, "before_update")
def track_price(mapper, connection, product):
    old = connection.execute(
        select(Product.__table__.c.cost, Product.__table__.c.price).where(
            Product.id == product.id
        )
    ).one()
    if old.cost == product.cost and old.price == product.price:
        return
    user = getattr(g, "user", None) if has_request_context() else None
    currency = (
        connection.execute(
            select(Setting.value).where(Setting.key == "currency")
        ).scalar()
        or "EGP"
    )
    source = (
        "Purchase receipt"
        if has_request_context()
        and request.endpoint
        in ("transactions.purchase_action", "transactions.purchase_form")
        else "Product update"
    )
    connection.execute(
        PriceHistory.__table__.insert().values(
            product_id=product.id,
            product_name=product.name,
            old_cost=old.cost,
            new_cost=product.cost,
            old_price=old.price,
            new_price=product.price,
            change_amount=product.price - old.price,
            change_percentage=percent(old.price, product.price),
            cost_change_amount=product.cost - old.cost,
            cost_change_percentage=percent(old.cost, product.cost),
            user_id=user.id if user else None,
            changed_by=user.name if user else "System",
            created_at=now(),
            currency=currency,
            source=source,
        )
    )


def local_time(value):
    return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Africa/Cairo"))


def date_text(value):
    return local_time(value).strftime("%d/%m/%Y %H:%M")


def relative_date(value):
    days = (local_time(now()).date() - local_time(value).date()).days
    return "Today" if days == 0 else "Yesterday" if days == 1 else f"{days} days ago"


def money(value, currency="EGP"):
    return f"{Decimal(value) / 100:,.2f} {currency}" + (
        " (ج.م)" if currency == "EGP" else ""
    )


def serialize(row):
    return dict(
        id=row.id,
        product_id=row.product_id,
        product_name=row.product_name,
        old_cost=row.old_cost,
        new_cost=row.new_cost,
        old_price=row.old_price,
        new_price=row.new_price,
        change_amount=row.change_amount,
        change_percentage=float(row.change_percentage)
        if row.change_percentage is not None
        else None,
        cost_change_amount=row.cost_change_amount,
        cost_change_percentage=float(row.cost_change_percentage)
        if row.cost_change_percentage is not None
        else None,
        changed_by=row.changed_by,
        user_id=row.user_id,
        date=date_text(row.created_at),
        timestamp=row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        relative=relative_date(row.created_at),
        currency=row.currency,
        source=row.source,
    )


def price_summary(product):
    query = PriceHistory.query.filter_by(product_id=product.id)
    first = query.order_by(PriceHistory.id).first()
    count, low, high, total = (
        db.session.query(
            db.func.count(PriceHistory.id),
            db.func.min(PriceHistory.new_price),
            db.func.max(PriceHistory.new_price),
            db.func.sum(PriceHistory.new_price),
        )
        .filter(PriceHistory.product_id == product.id)
        .one()
    )
    cost_count, cost_low, cost_high, cost_total = (
        db.session.query(
            db.func.count(PriceHistory.id),
            db.func.min(PriceHistory.new_cost),
            db.func.max(PriceHistory.new_cost),
            db.func.sum(PriceHistory.new_cost),
        )
        .filter(PriceHistory.product_id == product.id)
        .one()
    )
    baseline = first.old_price if first else product.price
    average = int(
        (Decimal((total or 0) + baseline) / (count + 1)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    cost_baseline = first.old_cost if first else product.cost
    cost_average = int(
        (Decimal((cost_total or 0) + cost_baseline) / (cost_count + 1)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    last = query.order_by(PriceHistory.id.desc()).first()
    recent = list(reversed(query.order_by(PriceHistory.id.desc()).limit(30).all()))
    return dict(
        current=product.price,
        current_cost=product.cost,
        lowest=min(low, baseline) if count else baseline,
        highest=max(high, baseline) if count else baseline,
        average=average,
        lowest_cost=min(cost_low, cost_baseline) if cost_count else cost_baseline,
        highest_cost=max(cost_high, cost_baseline) if cost_count else cost_baseline,
        average_cost=cost_average,
        count=count,
        latest=serialize(last) if last else None,
        trend=[serialize(h) for h in recent],
        alert=bool(
            product.price_alerts
            and last
            and (
                (
                    last.old_price > 0
                    and abs(last.change_amount) * 100 > last.old_price * 20
                )
                or (
                    last.old_cost > 0
                    and abs(last.cost_change_amount) * 100 > last.old_cost * 20
                )
            )
        ),
    )


def latest_changes(ids):
    if not ids:
        return {}
    latest = (
        db.select(db.func.max(PriceHistory.id))
        .where(PriceHistory.product_id.in_(ids))
        .group_by(PriceHistory.product_id)
    )
    return {
        r.product_id: serialize(r)
        for r in db.session.scalars(
            db.select(PriceHistory).where(PriceHistory.id.in_(latest))
        )
    }


def price_trend(product_id, days=None, limit=500):
    """Trend points for the analytics popup. No schema change; query only."""
    from datetime import timedelta

    query = PriceHistory.query.filter_by(product_id=product_id)
    if days:
        cutoff = now() - timedelta(days=days)
        query = query.filter(PriceHistory.created_at >= cutoff)
    rows = query.order_by(PriceHistory.id).limit(limit).all()
    return [serialize(r) for r in rows]
