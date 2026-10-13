import sys
import re
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tempfile
from app import create_app
from models import db, Role, User, Category, Supplier, Customer, Product
from werkzeug.security import generate_password_hash

def get_luminance(hex_str):
    hex_str = hex_str.strip().lstrip('#')
    if len(hex_str) == 3:
        hex_str = ''.join([c*2 for c in hex_str])
    if len(hex_str) != 6:
        return 0.5
    r, g, b = [int(hex_str[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
    def adjust(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * adjust(r) + 0.7152 * adjust(g) + 0.0722 * adjust(b)

def get_contrast_ratio(hex1, hex2):
    l1 = get_luminance(hex1)
    l2 = get_luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)

def run_comprehensive_audit():
    tmp_path = Path(tempfile.mkdtemp())
    (tmp_path / "backups").mkdir(parents=True, exist_ok=True)
    (tmp_path / "static/uploads").mkdir(parents=True, exist_ok=True)

    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "ROOT": tmp_path,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "test_audit.db"),
    })

    with app.app_context():
        roles = [Role(name=n) for n in ["Admin", "Manager", "Cashier"]]
        db.session.add_all(roles)
        db.session.flush()
        admin_user = User(
            name="Admin",
            username="admin",
            password_hash=generate_password_hash("test-password-123"),
            role_id=roles[0].id,
        )
        db.session.add(admin_user)
        cat = Category(name="Electronics")
        db.session.add(cat)
        sup = Supplier(name="Main Supplier")
        db.session.add(sup)
        cust = Customer(name="John Doe", phone="01012345678", email="john@example.com")
        db.session.add(cust)
        db.session.flush()
        db.session.add(Product(
            name="Laptop Pro 15",
            sku="LAP-001",
            barcode="9988776655",
            category_id=cat.id,
            supplier_id=sup.id,
            cost=20000,
            price=25000,
            stock=15,
            minimum=5,
        ))
        db.session.commit()

    client = app.test_client()
    login_res = client.post('/login', data={'username': 'admin', 'password': 'test-password-123'}, follow_redirects=True)
    assert login_res.status_code == 200, f"Login failed with status {login_res.status_code}"

    routes = [
        ('/', 'Dashboard'),
        ('/products', 'Products Catalog'),
        ('/products/new', 'New Product Form'),
        ('/categories', 'Categories Directory'),
        ('/inventory', 'Inventory Hub'),
        ('/inventory/adjust', 'Stock Adjustment'),
        ('/sales', 'Sales Invoices'),
        ('/sales/new', 'Point of Sale'),
        ('/shipping', 'Shipping Operations'),
        ('/orders', 'Order Fulfillment'),
        ('/reports', 'Reports & Analytics'),
        ('/settings', 'Settings'),
        ('/settings/users', 'Users & Roles'),
        ('/settings/audit', 'Audit Trail'),
        ('/settings/telemetry', 'System Telemetry'),
    ]

    report = {
        'routes_tested': len(routes),
        'a11y_form_issues': [],
        'a11y_button_issues': [],
        'a11y_img_issues': [],
        'table_responsive_issues': [],
        'heading_hierarchy_issues': [],
        'viewport_tests': {},
        'contrast_checks': {},
    }

    print(f"Auditing {len(routes)} screens...")

    for route, label in routes:
        res = client.get(route)
        if res.status_code != 200:
            print(f"WARNING: Route {route} ({label}) returned {res.status_code}")
            continue
        html = res.text

        # 1. FORM LABELS (WCAG 1.3.1, 4.1.2)
        # Check inputs, selects, textareas
        for m in re.finditer(r'<(input|select|textarea)([^>]+)>', html, re.IGNORECASE):
            tag, attrs = m.group(1), m.group(2)
            if any(t in attrs for t in ['type="hidden"', 'type="submit"', 'type="button"', 'type="checkbox" and class="form-check-input"']):
                continue
            has_aria = 'aria-label=' in attrs or 'aria-labelledby=' in attrs
            id_m = re.search(r'id=["\']([^"\']+)["\']', attrs)
            elem_id = id_m.group(1) if id_m else None
            has_for = bool(elem_id and (f'for="{elem_id}"' in html or f"for='{elem_id}'" in html))
            
            # Check enclosing label
            # Look backwards up to 300 chars for unclosed <label
            start = max(0, m.start() - 300)
            prefix = html[start:m.start()]
            enclosed_in_label = ('<label' in prefix and prefix.rfind('<label') > prefix.rfind('</label'))
            
            if not (has_aria or has_for or enclosed_in_label):
                report['a11y_form_issues'].append({
                    'route': route,
                    'label': label,
                    'tag': tag,
                    'snippet': f"<{tag} {attrs[:70].strip()}>"
                })

        # 2. BUTTON ACCESSIBILITY
        for m in re.finditer(r'<button([^>]*)>(.*?)</button>', html, re.IGNORECASE | re.DOTALL):
            b_attrs, b_content = m.group(1), m.group(2).strip()
            # If button only has an icon (<i data-lucide="..." or <svg) and no text or aria-label
            text_only = re.sub(r'<[^>]+>', '', b_content).strip()
            has_aria = 'aria-label=' in b_attrs or 'aria-labelledby=' in b_attrs or 'title=' in b_attrs
            if not text_only and not has_aria:
                report['a11y_button_issues'].append({
                    'route': route,
                    'label': label,
                    'snippet': f"<button {b_attrs[:50]}>{b_content[:30]}</button>"
                })

        # 3. IMAGE ALT ATTRIBUTES
        for m in re.finditer(r'<img([^>]+)>', html, re.IGNORECASE):
            attrs = m.group(1)
            if 'alt=' not in attrs:
                report['a11y_img_issues'].append({
                    'route': route,
                    'label': label,
                    'snippet': f"<img {attrs[:60]}>"
                })

        # 4. TABLES INSIDE SCROLL CONTAINERS
        for m in re.finditer(r'<table([^>]*)>', html, re.IGNORECASE):
            t_attrs = m.group(1)
            start = max(0, m.start() - 400)
            prefix = html[start:m.start()]
            if 'table-responsive' not in prefix and 'pos-table-scroll' not in prefix and 'ph-table-scroll' not in prefix:
                report['table_responsive_issues'].append({
                    'route': route,
                    'label': label,
                    'snippet': f"<table {t_attrs[:50]}>"
                })

    # CONTRAST AUDIT
    theme_colors = [
        ('Primary on Canvas', '#2563eb', '#f8fafc'),
        ('Primary on Panel', '#2563eb', '#ffffff'),
        ('Ink on Canvas (Light)', '#0f172a', '#f8fafc'),
        ('Ink on Panel (Light)', '#0f172a', '#ffffff'),
        ('Muted on Panel (Light)', '#64748b', '#ffffff'),
        ('Ink on Canvas (Dark)', '#f1f5f9', '#0b1120'),
        ('Ink on Panel (Dark)', '#f1f5f9', '#131d33'),
        ('Muted on Panel (Dark)', '#94a3b8', '#131d33'),
        ('Success badge green text on soft green', '#15803d', '#dcfce7'),
        ('Danger badge red text on soft red', '#b91c1c', '#fee2e2'),
        ('Warning badge amber text on soft amber', '#b45309', '#fef3c7'),
    ]
    for name, fg, bg in theme_colors:
        ratio = get_contrast_ratio(fg, bg)
        passes_aa = ratio >= 4.5
        passes_aaa = ratio >= 7.0
        report['contrast_checks'][name] = {
            'fg': fg,
            'bg': bg,
            'ratio': round(ratio, 2),
            'WCAG_AA': passes_aa,
            'WCAG_AAA': passes_aaa,
        }

    return report

if __name__ == '__main__':
    r = run_comprehensive_audit()
    print("\n=== AUDIT RESULTS ===")
    print(f"Screens verified: {r['routes_tested']}")
    print(f"Form label issues: {len(r['a11y_form_issues'])}")
    for item in r['a11y_form_issues']:
        print("  -", item['label'], item['snippet'])
    print(f"Button a11y issues: {len(r['a11y_button_issues'])}")
    for item in r['a11y_button_issues']:
        print("  -", item['label'], item['snippet'])
    print(f"Image alt issues: {len(r['a11y_img_issues'])}")
    for item in r['a11y_img_issues']:
        print("  -", item['label'], item['snippet'])
    print(f"Tables outside responsive wrapper: {len(r['table_responsive_issues'])}")
    for item in r['table_responsive_issues']:
        print("  -", item['label'], item['snippet'])
    print("\n=== CONTRAST CHECKS ===")
    for k, v in r['contrast_checks'].items():
        status = "AAA" if v['WCAG_AAA'] else ("AA" if v['WCAG_AA'] else "FAIL")
        print(f"  {k}: {v['ratio']}:1 [{status}] (fg: {v['fg']}, bg: {v['bg']})")
