"""Regression tests for UI defects fixed during the interface redesign."""

import re
from pathlib import Path

from test_app import app, client  # noqa: F401
from models import Category, Product, db
from services.core import save_setting

ROOT = Path(__file__).resolve().parents[1]


def use_arabic(app):
    with app.app_context():
        save_setting("language", "ar")
        db.session.commit()


def test_product_images_have_no_inline_handlers(app, client):
    """The CSP forbids inline handlers, so image fallbacks must not rely on onerror=."""
    with app.app_context():
        db.session.get(Product, 1).image = "missing-file.png"
        db.session.add(
            Product(name="No Image", sku="NOIMG-1", category_id=1, cost=100, price=200, stock=1, minimum=0)
        )
        db.session.commit()
    for path in ("/products", "/inventory"):
        html = client.get(path).text
        assert "onerror=" not in html, path
        assert 'class="product-thumb" src="/static/uploads/missing-file.png' in html
        assert '<span class="product-thumb product-icon" role="img" aria-label="No Image">' in html
    assert "onerror" not in (ROOT / "templates" / "macros.html").read_text(encoding="utf-8")


def test_no_inline_scripts_and_theme_applied_before_paint(client):
    html = client.get("/").text
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    head = html.split("</head>")[0]
    assert "/static/js/theme-init.js" in head
    assert head.index("theme-init.js") < head.index("js/app.js")


def test_sidebar_is_grouped_and_keeps_routes(client):
    html = client.get("/").text
    for group in ("Overview", "Selling", "Catalog &amp; Stock", "Administration"):
        assert f'<span class="nav-label">{group}</span>' in html
    for href in ("/", "/sales", "/orders", "/customers", "/products", "/inventory", "/purchases",
                 "/suppliers", "/reports", "/backups", "/settings/users", "/settings"):
        assert f'class="nav-item' in html and f'href="{href}"' in html
    assert ">Orders<" in html


def test_directory_form_titles_are_correct_and_translated(app, client):
    html = client.get("/categories").text
    assert "Add category" in html and "Add categorie" not in html
    assert "Add customer" in client.get("/customers").text
    assert "Add supplier" in client.get("/suppliers").text
    use_arabic(app)
    html = client.get("/customers").text
    assert "إضافة عميل" in html and "Add customer" not in html


def test_empty_lists_hide_pagination(client):
    html = client.get("/purchases?q=zzzz-no-match").text
    assert "No purchase orders found" in html
    assert "Showing 0" not in html


def test_inventory_category_chart_uses_horizontal_bars(app, client):
    with app.app_context():
        db.session.add(Category(name="A very long category name that used to overlap"))
        db.session.commit()
    html = client.get("/inventory").text
    assert 'id="category"' in html and 'data-index-axis="y"' in html


def test_report_filters_refresh_whole_report(client):
    html = client.get("/reports").text
    region = html.split('data-partial="report-table"', 1)[1]
    assert 'data-partial-form="report-table"' in region
    assert 'class="metrics four"' in region and "chart" in region
    assert html.count('data-partial="report-table"') == 1


def test_arabic_shell_and_dashboard_are_translated(app, client):
    use_arabic(app)
    html = client.get("/").text
    assert 'dir="rtl"' in html
    for arabic in ("نظرة عامة", "الإدارة", "النسخ الاحتياطية", "المستخدمون", "مبيعات اليوم"):
        assert arabic in html, arabic
    for english in ('<span class="nav-label">Overview</span>', ">Backups<", ">Users<", "Sales Today"):
        assert english not in html, english


def test_every_literal_template_string_has_arabic(app):
    """Guards against new interface text shipping without an Arabic translation."""
    from services.i18n import AR

    pattern = re.compile(r"""\bt\(\s*(['"])([^'"{}~]+?)\1\s*\)""")
    missing = set()
    for path in (ROOT / "templates").rglob("*.html"):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            key = match.group(2)
            if re.search(r"[A-Za-z]{2,}", key) and key not in AR:
                missing.add(f"{path.relative_to(ROOT)}: {key}")
    assert not missing, sorted(missing)[:20]
