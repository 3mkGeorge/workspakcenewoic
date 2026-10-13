from flask import Blueprint, g, render_template, request, send_file
from models import Category, Customer, Product, Supplier
from services.analytics import date_range, report_data, sales_charts

reporting = Blueprint("reporting", __name__)
REPORTS = {
    "sales": "Sales Report",
    "purchases": "Purchases Report",
    "inventory": "Inventory Report",
    "products": "Product Report",
    "customers": "Customer Report",
    "suppliers": "Supplier Report",
    "profit": "Profit & Loss Report",
    "shipping": "Shipping Report",
}


@reporting.get("/reports")
def reports():
    start, end = date_range(14)
    kind = request.args.get("kind", "sales")
    headers, rows, money_cols, stats = report_data(kind, start, end)
    page = max(1, request.args.get("page", 1, type=int))
    chart, category_chart, top_products = sales_charts(start, end)
    _, top_customers, _, _ = report_data("customers", start, end)
    return render_template(
        "reports/index.html",
        title="Reports",
        reports=REPORTS,
        kind=kind,
        headers=headers,
        rows=rows[(page - 1) * 50 : page * 50],
        total_rows=len(rows),
        page_num=page,
        money_cols=money_cols,
        stats=stats,
        start=start,
        end=end,
        chart=chart,
        category_chart=category_chart,
        top_products=top_products,
        top_customers=top_customers[:10],
        categories=Category.query.order_by(Category.name).all(),
        products=Product.query.filter_by(active=True).order_by(Product.name).all(),
        customers=Customer.query.filter_by(active=True).order_by(Customer.name).all(),
        suppliers=Supplier.query.filter_by(active=True).order_by(Supplier.name).all(),
        export_args=request.args.to_dict(),
    )


@reporting.get("/reports/export/<fmt>")
def export(fmt):
    from services.document_exports import generate_report_xlsx, generate_report_pdf

    start, end = date_range(14)
    kind = request.args.get("kind", "sales")
    if fmt == "xlsx":
        stream, filename = generate_report_xlsx(kind, start, end, g.settings)
        return send_file(
            stream,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if fmt == "pdf":
        stream, filename = generate_report_pdf(kind, start, end, g.settings)
        return send_file(
            stream,
            as_attachment=True,
            download_name=filename,
            mimetype="application/pdf",
        )
    raise ValueError("Choose PDF or Excel export.")
