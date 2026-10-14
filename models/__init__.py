"""Persistent ledger. Monetary amounts are integer minor units (piastres)."""

from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, event

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30), unique=True, nullable=False)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    role = db.relationship(Role)
    active = db.Column(db.Boolean, default=True, nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)


class Permission(db.Model):
    __tablename__ = "permissions"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(60), nullable=False)
    action = db.Column(db.String(60), nullable=False)


class RolePermission(db.Model):
    __tablename__ = "role_permissions"
    role_id = db.Column(
        db.Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id = db.Column(
        db.Integer,
        db.ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )


class UserPermissionGrant(db.Model):
    __tablename__ = "user_permission_grants"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id = db.Column(
        db.Integer,
        db.ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )


class UserPermissionDenial(db.Model):
    __tablename__ = "user_permission_denials"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id = db.Column(
        db.Integer,
        db.ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )


class EndpointPermission(db.Model):
    """Additional, data-defined requirements on existing Flask actions."""

    __tablename__ = "endpoint_permissions"
    endpoint = db.Column(db.String(120), primary_key=True)
    method = db.Column(db.String(10), primary_key=True)
    permission_id = db.Column(
        db.Integer,
        db.ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )


class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(500), nullable=False, default="", server_default="")
    color = db.Column(db.String(7), nullable=False, default="", server_default="")
    icon = db.Column(db.String(40), nullable=False, default="", server_default="")
    created_at = db.Column(db.DateTime, default=now)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now)


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40), default="")
    email = db.Column(db.String(120), default="")
    address = db.Column(db.String(300), default="")
    active = db.Column(db.Boolean, default=True, nullable=False)


class Customer(db.Model):
    __tablename__ = "customers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40), default="")
    email = db.Column(db.String(120), default="")
    address = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    sku = db.Column(db.String(60), unique=True, nullable=False)
    barcode = db.Column(db.String(80), unique=True)
    brand = db.Column(db.String(80), default="")
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), index=True)
    category = db.relationship(Category)
    supplier = db.relationship(Supplier)
    cost = db.Column(db.Integer, nullable=False, default=0)
    price = db.Column(db.Integer, nullable=False, default=0)
    stock = db.Column(db.Integer, nullable=False, default=0)
    minimum = db.Column(db.Integer, nullable=False, default=5)
    location = db.Column(db.String(60), default="")
    image = db.Column(db.String(120), default="")
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)
    price_alerts = db.Column(
        db.Boolean, nullable=False, default=True, server_default="1"
    )
    images = db.relationship(
        "ProductImage",
        backref="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.sort_order",
        lazy="selectin",
    )
    __table_args__ = (
        CheckConstraint("stock >= 0 AND cost >= 0 AND price >= 0 AND minimum >= 0"),
    )

    @property
    def status(self):
        return (
            "Out of Stock"
            if self.stock == 0
            else "Low Stock"
            if self.stock <= self.minimum
            else "In Stock"
        )

    @property
    def ordered_images(self):
        return sorted(list(self.images or []), key=lambda i: (i.sort_order, i.id))

    @property
    def primary_image(self):
        ordered = self.ordered_images
        if not ordered:
            return None
        for img in ordered:
            if img.is_primary:
                return img
        return ordered[0]


class ProductImage(db.Model):
    __tablename__ = "product_images"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_path = db.Column(db.String(255), nullable=False)
    file_name = db.Column(db.String(120), nullable=False)
    is_primary = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    __table_args__ = (
        db.Index("ix_product_images_product_order", "product_id", "sort_order"),
    )


class WebListing(db.Model):
    """Opt-in publication of a product to the Next Chip website.

    Absent row or published=False means the product is not offered online.
    Optional web names/descriptions fall back to the product name / empty.
    Only public, approved fields are ever exported (services/web_catalog_sync.py).
    """

    __tablename__ = "web_listings"
    product_id = db.Column(
        db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    published = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    name_en = db.Column(db.String(160), nullable=False, default="", server_default="")
    name_ar = db.Column(db.String(160), nullable=False, default="", server_default="")
    description_en = db.Column(db.String(4000), nullable=False, default="", server_default="")
    description_ar = db.Column(db.String(4000), nullable=False, default="", server_default="")
    max_per_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)
    product = db.relationship(
        Product,
        backref=db.backref("web_listing", uselist=False, cascade="all, delete-orphan"),
    )
    __table_args__ = (CheckConstraint("max_per_order >= 0 AND max_per_order <= 99"),)


class PriceHistory(db.Model):
    __tablename__ = "price_history"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey("products.id"), nullable=False, index=True
    )
    product_name = db.Column(db.String(160), nullable=False)
    old_cost = db.Column(db.Integer, nullable=False)
    new_cost = db.Column(db.Integer, nullable=False)
    old_price = db.Column(db.Integer, nullable=False)
    new_price = db.Column(db.Integer, nullable=False)
    change_amount = db.Column(db.Integer, nullable=False)
    change_percentage = db.Column(db.Numeric(18, 4))
    cost_change_amount = db.Column(db.Integer, nullable=False)
    cost_change_percentage = db.Column(db.Numeric(18, 4))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    changed_by = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)
    currency = db.Column(db.String(3), nullable=False, default="EGP")
    source = db.Column(db.String(100), nullable=False, default="Product update")
    __table_args__ = (
        CheckConstraint(
            "old_cost>=0 AND new_cost>=0 AND old_price>=0 AND new_price>=0"
        ),
        CheckConstraint(
            "change_amount=new_price-old_price AND cost_change_amount=new_cost-old_cost"
        ),
        CheckConstraint("old_cost!=new_cost OR old_price!=new_price"),
        db.Index("ix_price_history_product_recent", "product_id", "id"),
    )


@event.listens_for(Product, "before_delete")
def guard_product_hard_delete(mapper, connection, target):
    """Enforce that products with immutable price history cannot be hard deleted.
    StorePro uses soft deletion (active=False / archived) to preserve financial audits.
    """
    has_history = connection.execute(
        db.select(db.func.count(PriceHistory.id)).where(
            PriceHistory.product_id == target.id
        )
    ).scalar()
    if has_history:
        raise ValueError(
            f"Product '{target.name}' has immutable price history records and cannot be permanently deleted. "
            "Archive or deactivate the product instead."
        )


PICKUP_STATUSES = ("Pending Pickup", "Ready For Pickup", "Collected")
PICKUP_TRANSITIONS = {
    "Pending Pickup": ("Ready For Pickup",),
    "Ready For Pickup": ("Collected",),
    "Collected": (),
}


class Sale(db.Model):
    __tablename__ = "sales"
    id = db.Column(db.Integer, primary_key=True)
    invoice = db.Column(db.String(60), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"))
    customer = db.relationship(Customer)
    customer_name = db.Column(db.String(120), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    cashier = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=now, index=True, nullable=False)
    status = db.Column(db.String(20), default="Completed", nullable=False)
    payment = db.Column(db.String(30), nullable=False)
    subtotal = db.Column(db.Integer, nullable=False)
    discount = db.Column(db.Integer, default=0, nullable=False)
    tax = db.Column(db.Integer, nullable=False)
    tax_rate = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    cost = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    store_snapshot = db.Column(db.Text, nullable=False)
    note = db.Column(db.String(500), default="")
    token = db.Column(db.String(64), unique=True, nullable=False)
    revision = db.Column(db.Integer, default=1, nullable=False)
    pickup_date = db.Column(db.String(10), default="")
    pickup_notes = db.Column(db.String(300), default="")
    pickup_status = db.Column(db.String(20), default="")
    cancel_reason = db.Column(db.String(200), default="")
    cancelled_at = db.Column(db.DateTime)
    items = db.relationship(
        "SaleItem", cascade="all, delete-orphan", backref="sale", lazy="selectin"
    )
    payments = db.relationship(
        "SalePayment", cascade="all, delete-orphan", backref="sale", lazy="selectin"
    )

    @property
    def invoice_discount(self):
        return self.discount - sum(item.discount for item in self.items)

    @property
    def shipping_charge(self):
        """Shipping fee billed on this invoice, in piastres.

        Invoice total = (subtotal - discount) + tax + shipping fee, where the fee
        is never discounted and carries no VAT. It is read back from the
        persisted totals (the same figures the payments add up to), so there is
        one source of truth; invoices issued before delivery was billed give 0.
        """
        return max(0, self.total - (self.subtotal - self.discount + self.tax))

    __table_args__ = (
        CheckConstraint(
            "subtotal >= 0 AND discount >= 0 AND discount <= subtotal AND total >= 0"
        ),
        db.Index("ix_sales_status_created", "status", "created_at"),
    )


class SaleItem(db.Model):
    __tablename__ = "sale_items"
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    product = db.relationship(Product)
    name = db.Column(db.String(160), nullable=False)
    category_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Integer, nullable=False)
    cost = db.Column(db.Integer, nullable=False)
    discount = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    __table_args__ = (
        CheckConstraint("quantity > 0 AND price >= 0 AND cost >= 0"),
        CheckConstraint("discount >= 0 AND discount <= quantity * price"),
    )


class SalePayment(db.Model):
    __tablename__ = "sale_payments"
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(
        db.Integer, db.ForeignKey("sales.id"), nullable=False, index=True
    )
    method = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    __table_args__ = (
        CheckConstraint("amount >= 0"),
        CheckConstraint(
            "method IN ('Cash','Visa','Mastercard','Bank Transfer','Wallet','Card','Mobile Wallet')"
        ),
        db.UniqueConstraint("sale_id", "method", name="uq_sale_payment_method"),
    )


class Purchase(db.Model):
    __tablename__ = "purchases"
    id = db.Column(db.Integer, primary_key=True)
    invoice = db.Column(db.String(60), unique=True, nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False)
    supplier = db.relationship(Supplier)
    supplier_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=now, index=True, nullable=False)
    received_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default="Pending", nullable=False)
    total = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    note = db.Column(db.String(500), default="")
    token = db.Column(db.String(64), unique=True, nullable=False)
    items = db.relationship(
        "PurchaseItem",
        cascade="all, delete-orphan",
        backref="purchase",
        lazy="selectin",
    )


class PurchaseItem(db.Model):
    __tablename__ = "purchase_items"
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchases.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    product = db.relationship(Product)
    name = db.Column(db.String(160), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    cost = db.Column(db.Integer, nullable=False)
    __table_args__ = (CheckConstraint("quantity > 0 AND cost >= 0"),)


SHIPPING_STATUSES = (
    "Pending",
    "Preparing",
    "Ready For Shipment",
    "Shipped",
    "Out For Delivery",
    "Delivered",
    "Failed Delivery",
    "Returned",
    "Cancelled",
)

# Allowed next statuses per current status. Terminal: Delivered, Returned, Cancelled.
SHIPPING_TRANSITIONS = {
    # Canonical workflow: Pending → Packed → Ready For Shipment → Shipped
    # → Out For Delivery → Delivered. Tracking codes are supplied by the
    # external courier and entered when shipping; saving a tracking code on
    # a Ready order moves it to Shipped. Preparing / Failed Delivery are
    # legacy bridges so old rows stay actionable; Returned / Cancelled terminal.
    "Pending": ("Packed", "Cancelled"),
    "Packed": ("Ready For Shipment", "Cancelled"),
    "Preparing": ("Packed", "Cancelled"),
    "Ready For Shipment": ("Shipped", "Cancelled"),
    "Shipped": ("Out For Delivery", "Cancelled"),
    "Out For Delivery": ("Delivered", "Returned"),
    "Failed Delivery": ("Out For Delivery", "Returned"),
    "Returned": (),
    "Delivered": (),
    "Cancelled": (),
}

# Canonical workflow stages for progress display (status → stage index).
SHIPPING_WORKFLOW = (
    "Pending",
    "Packed",
    "Ready For Shipment",
    "Shipped",
    "Out For Delivery",
    "Delivered",
)
SHIPPING_STAGE_LABELS = {
    "Pending": "Pending",
    "Packed": "Packed",
    "Ready For Shipment": "Ready For Shipment",
    "Shipped": "Shipped",
    "Out For Delivery": "Out For Delivery",
    "Delivered": "Delivered",
}

# Courier providers. Fulfillment is provider-agnostic today: tracking codes are
# stored internally only. Adding a live integration later means adding a
# provider adapter here without touching the order ledger.
COURIER_PROVIDERS = (
    "Aramex",
    "Bosta",
    "Mylerz",
    "SMSA",
    "DHL",
    "FedEx",
)


class ShippingOrder(db.Model):
    """Delivery/shipping fulfillment linked 1:1 to a completed sale invoice."""

    __tablename__ = "shipping_orders"
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(30), unique=True, nullable=False)
    sale_id = db.Column(
        db.Integer, db.ForeignKey("sales.id"), unique=True, nullable=False, index=True
    )
    sale = db.relationship(Sale, backref=db.backref("shipping", uselist=False))
    tracking_code = db.Column(db.String(40), unique=True)
    tracking_url = db.Column(db.String(300), default="")
    status = db.Column(db.String(20), default="Pending", nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"))
    customer_name = db.Column(db.String(120), nullable=False, default="")
    phone = db.Column(db.String(40), default="")
    alt_phone = db.Column(db.String(40), default="")
    governorate = db.Column(db.String(80), default="")
    city = db.Column(db.String(80), default="")
    district = db.Column(db.String(80), default="")
    landmark = db.Column(db.String(80), default="")
    street = db.Column(db.String(160), default="")
    building = db.Column(db.String(40), default="")
    floor = db.Column(db.String(20), default="")
    apartment = db.Column(db.String(20), default="")
    postal_code = db.Column(db.String(20), default="")
    address_snapshot = db.Column(db.Text, nullable=False, default="{}")
    notes = db.Column(db.String(500), default="")
    courier = db.Column(db.String(80), default="")
    cancel_reason = db.Column(db.String(200), default="")
    cancelled_at = db.Column(db.DateTime)
    shipping_cost = db.Column(db.Integer, nullable=False, default=0)
    shipment_date = db.Column(db.String(10), default="")
    delivered_by = db.Column(db.String(120), default="")
    delivered_at = db.Column(db.DateTime)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=now, index=True, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)
    events = db.relationship(
        "ShippingEvent",
        cascade="all, delete-orphan",
        backref="order",
        order_by="ShippingEvent.id",
    )
    __table_args__ = (
        CheckConstraint("shipping_cost >= 0"),
        CheckConstraint(
            "status IN ('Pending','Packed','Preparing','Ready For Shipment','Shipped',"
            "'Out For Delivery','Delivered','Failed Delivery','Returned','Cancelled')"
        ),
        db.Index("ix_shipping_orders_status_created", "status", "created_at"),
    )


class ShippingEvent(db.Model):
    __tablename__ = "shipping_events"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(
        db.Integer,
        db.ForeignKey("shipping_orders.id"),
        nullable=False,
        index=True,
    )
    action = db.Column(db.String(120), nullable=False)
    actor = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=now, index=True, nullable=False)


class InventoryMovement(db.Model):
    __tablename__ = "inventory_movements"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    product = db.relationship(Product)
    quantity = db.Column(db.Integer, nullable=False)
    balance = db.Column(db.Integer, nullable=False)
    cost = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    reference = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=now, index=True, nullable=False)
    __table_args__ = (
        db.Index("ix_inventory_movements_product_created", "product_id", "created_at"),
    )


class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.Text, nullable=False)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    actor = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    details = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)


class BackupLog(db.Model):
    __tablename__ = "backup_logs"
    id = db.Column(db.Integer, primary_key=True)
    backup_id = db.Column(db.String(80), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)
    reason = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    file_size = db.Column(db.BigInteger, nullable=False, default=0)
    location = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(20), nullable=False)
    error = db.Column(db.Text, nullable=False, default="")
    __table_args__ = (
        CheckConstraint("kind IN ('Auto', 'Manual')"),
        CheckConstraint("status IN ('Success', 'Failed')"),
        CheckConstraint("source IN ('Primary', 'Secondary')"),
        CheckConstraint("file_size >= 0"),
    )


class Expense(db.Model):
    __tablename__ = "expenses"
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    __table_args__ = (CheckConstraint("amount > 0"),)
