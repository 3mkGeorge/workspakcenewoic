"""Product catalog import and export service for StorePro.

Handles CSV catalog generation with Excel formula escaping, and robust
batch CSV ingestion with schema validation, formula stripping, dynamic
category/supplier resolution, and atomic transaction guarantees.
"""

import io
import csv
from flask import Response
from models import db, Product, Category, Supplier
from services.core import audit, move
from services.validation import cents, escape_formula, integer, sanitize_formula


def generate_catalog_csv():
    """Generate CSV file stream with escaped formula fields for active products."""
    products = Product.query.filter_by(active=True).order_by(Product.name.asc()).all()
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "Name", "SKU", "Barcode", "Category", "Supplier", "Brand",
        "Selling Price", "Cost Price", "Stock Units", "Minimum Stock"
    ])
    for p in products:
        writer.writerow([
            escape_formula(p.name),
            escape_formula(p.sku),
            escape_formula(p.barcode),
            escape_formula(p.category.name if p.category else ""),
            escape_formula(p.supplier.name if p.supplier else ""),
            escape_formula(p.brand),
            f"{p.price / 100:.2f}",
            f"{p.cost / 100:.2f}",
            p.stock,
            p.minimum,
        ])

    resp = Response(output.getvalue().encode("utf-8-sig"), mimetype="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=StorePro-Products.csv"
    return resp


def process_catalog_import_csv(file):
    """Parse, sanitize, validate, and import a CSV file of products.

    Returns:
        (created_count, updated_count)

    Raises:
        ValueError on any format, validation, or integrity error.
    """
    if not file or not file.filename.lower().endswith(".csv"):
        raise ValueError("Please upload a valid CSV file (.csv extension).")

    content = file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except Exception:
            raise ValueError("The CSV file could not be decoded. Ensure it is UTF-8 encoded.")

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows or len(rows) < 2:
        raise ValueError("The CSV file is empty or missing data rows.")

    header = [c.strip().lower() for c in rows[0]]
    header_map = {name: idx for idx, name in enumerate(header)}

    # Ensure required columns
    required_cols = ["name", "sku", "selling price"]
    missing = [c for c in required_cols if c not in header_map]
    if missing:
        raise ValueError(f"CSV is missing required column headers: {', '.join(missing)}")

    created_count = 0
    updated_count = 0
    seen_skus = set()

    for row_num, row in enumerate(rows[1:], start=2):
        if not row or not any(row):
            continue

        def get_col(*col_names, default=""):
            for col_name in col_names:
                idx = header_map.get(col_name)
                if idx is not None and idx < len(row):
                    return row[idx].strip()
            return default

        def present(*col_names):
            return any(c in header_map for c in col_names)

        name = sanitize_formula(get_col("name"))
        sku = sanitize_formula(get_col("sku"))
        barcode = sanitize_formula(get_col("barcode")) or None
        cat_name = sanitize_formula(get_col("category"))
        supp_name = sanitize_formula(get_col("supplier"))
        brand = sanitize_formula(get_col("brand", "description"))
        price_str = get_col("selling price", "price")
        cost_str = get_col("cost price", "cost")
        stock_str = get_col("stock units", "stock")
        min_str = get_col("minimum stock", "minimum")

        if not name:
            raise ValueError(f"Row {row_num}: Product name is required.")
        if not sku:
            raise ValueError(f"Row {row_num}: SKU is required.")

        if sku.lower() in seen_skus:
            raise ValueError(f"Row {row_num}: Duplicate SKU '{sku}' found in upload file.")
        seen_skus.add(sku.lower())

        price = cents(price_str, f"Row {row_num}: Invalid selling price '{price_str}'. Must be a positive number.")
        cost = cents(cost_str or "0", f"Row {row_num}: Invalid cost price '{cost_str}'.")
        stock = integer(stock_str or "0", 0, label=f"Row {row_num}: Invalid stock quantity '{stock_str}'.")
        minimum = integer(min_str or "5", 0, label=f"Row {row_num}: Invalid minimum stock '{min_str}'.")

        # Resolve Category (Category is required by foreign key)
        category_id = None
        if cat_name:
            cat = Category.query.filter_by(name=cat_name).first()
            if not cat:
                cat = Category(name=cat_name)
                db.session.add(cat)
                db.session.flush()
            category_id = cat.id

        # Resolve Supplier
        supplier_id = None
        if supp_name:
            supp = Supplier.query.filter_by(name=supp_name).first()
            if not supp:
                supp = Supplier(name=supp_name)
                db.session.add(supp)
                db.session.flush()
            supplier_id = supp.id

        if barcode:
            clash = Product.query.filter(Product.barcode == barcode[:60], Product.sku != sku).first()
            if clash:
                raise ValueError(f"Row {row_num}: Barcode '{barcode}' is already used by {clash.sku}.")

        # Existing products: only columns present in the file are updated.
        product = Product.query.filter_by(sku=sku).first()
        if product:
            product.name = name[:120]
            product.price = price
            if present("barcode"):
                product.barcode = barcode[:60] if barcode else None
            if present("brand", "description"):
                product.brand = brand[:80]
            if present("cost price", "cost"):
                product.cost = cost
            if present("minimum stock", "minimum"):
                product.minimum = minimum
            if category_id:
                product.category_id = category_id
            if supplier_id:
                product.supplier_id = supplier_id
            product.active = True
            db.session.flush()
            if present("stock units", "stock") and stock != product.stock:
                move(product, stock - product.stock, "Adjustment", "CSV import")
            updated_count += 1
        else:
            if not category_id:
                default_cat = Category.query.first()
                if not default_cat:
                    default_cat = Category(name="General")
                    db.session.add(default_cat)
                    db.session.flush()
                category_id = default_cat.id
            product = Product(
                name=name[:120],
                sku=sku[:60],
                barcode=barcode[:60] if barcode else None,
                brand=brand[:80],
                price=price,
                cost=cost,
                stock=0,
                minimum=minimum,
                category_id=category_id,
                supplier_id=supplier_id,
                active=True,
            )
            db.session.add(product)
            db.session.flush()
            if stock:
                move(product, stock, "Opening stock", "CSV import")
            created_count += 1

    audit("Import products CSV", f"Imported: {created_count} created, {updated_count} updated")
    db.session.commit()
    return created_count, updated_count
