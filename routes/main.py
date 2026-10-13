from flask import Blueprint, render_template, request
from models import Customer, Product, Purchase, Sale, Supplier, db
from services.dashboard import get_dashboard_data
from services.permissions import can
from services.shipping import stats as shipping_stats

main = Blueprint("main", __name__)


@main.get("/")
def dashboard():
    from services.permissions import can
    from services.dashboard import get_dashboard_data

    days = request.args.get("days", 7, type=int)
    data = get_dashboard_data(
        days=days,
        perm_can_settings=can("settings.view"),
        perm_can_sales=can("sales.view"),
    )
    return render_template(
        "dashboard/index.html",
        title="Dashboard",
        **data,
    )


@main.get("/search")
def search():
    q = request.args.get("q", "").strip()[:100]
    term = "%" + q.replace("%", "\\%").replace("_", "\\_") + "%"
    products = (
        Product.query.filter(
            Product.active == True,
            db.or_(
                Product.name.ilike(term, escape="\\"),
                Product.sku.ilike(term, escape="\\"),
                Product.barcode.ilike(term, escape="\\"),
            ),
        )
        .limit(30)
        .all()
        if q and can("products.view")
        else []
    )
    sales = (
        Sale.query.filter(
            db.or_(
                Sale.invoice.ilike(term, escape="\\"),
                Sale.customer_name.ilike(term, escape="\\"),
            )
        )
        .limit(30)
        .all()
        if q and can("sales.view")
        else []
    )
    customers = (
        Customer.query.filter(
            Customer.active == True, Customer.name.ilike(term, escape="\\")
        )
        .limit(30)
        .all()
        if q and can("customers.view")
        else []
    )
    suppliers = (
        Supplier.query.filter(
            Supplier.active == True, Supplier.name.ilike(term, escape="\\")
        )
        .limit(30)
        .all()
        if q and can("suppliers.view")
        else []
    )
    purchases = (
        Purchase.query.filter(
            db.or_(
                Purchase.invoice.ilike(term, escape="\\"),
                Purchase.supplier_name.ilike(term, escape="\\"),
            )
        )
        .limit(30)
        .all()
        if q and can("purchases.view")
        else []
    )
    return render_template(
        "search.html",
        title="Search",
        q=q,
        products=products,
        sales=sales,
        customers=customers,
        suppliers=suppliers,
        purchases=purchases,
    )


@main.get("/notifications")
def notifications():
    ship = shipping_stats() if can("sales.view") else None
    return render_template(
        "notifications.html",
        title="Alerts & Notifications",
        products=Product.query.filter(
            Product.active == True, Product.stock <= Product.minimum
        ).all()
        if can("inventory.view")
        else [],
        orders=Purchase.query.filter(
            Purchase.status.in_(["Pending", "Processing"])
        ).all()
        if can("purchases.view")
        else [],
        ship=ship,
    )


@main.get("/_debug/crash")
def debug_crash():
    from flask import current_app, abort
    if not current_app.config.get("TESTING"):
        abort(404)
    raise RuntimeError("Simulated critical system exception")
