-- StorePro SQLite schema. Application startup creates the same schema.
PRAGMA foreign_keys = ON;


CREATE TABLE backup_logs (
	id INTEGER NOT NULL, 
	backup_id VARCHAR(80) NOT NULL, 
	created_at DATETIME NOT NULL, 
	kind VARCHAR(10) NOT NULL, 
	reason VARCHAR(40) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	file_size BIGINT NOT NULL, 
	location TEXT NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	error TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (kind IN ('Auto', 'Manual')), 
	CHECK (status IN ('Success', 'Failed')), 
	CHECK (source IN ('Primary', 'Secondary')), 
	CHECK (file_size >= 0)
)

;
CREATE INDEX ix_backup_logs_created_at ON backup_logs (created_at);
CREATE INDEX ix_backup_logs_backup_id ON backup_logs (backup_id);

CREATE TABLE categories (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	description VARCHAR(500) DEFAULT '' NOT NULL, 
	color VARCHAR(7) DEFAULT '' NOT NULL, 
	icon VARCHAR(40) DEFAULT '' NOT NULL, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (name)
)

;

CREATE TABLE customers (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	phone VARCHAR(40), 
	email VARCHAR(120), 
	address VARCHAR(300), 
	created_at DATETIME NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE TABLE expenses (
	id INTEGER NOT NULL, 
	description VARCHAR(200) NOT NULL, 
	amount INTEGER NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (amount > 0)
)

;

CREATE TABLE permissions (
	id INTEGER NOT NULL, 
	"key" VARCHAR(100) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	category VARCHAR(60) NOT NULL, 
	action VARCHAR(60) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE ("key")
)

;

CREATE TABLE roles (
	id INTEGER NOT NULL, 
	name VARCHAR(30) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
)

;

CREATE TABLE settings (
	"key" VARCHAR(60) NOT NULL, 
	value TEXT NOT NULL, 
	PRIMARY KEY ("key")
)

;

CREATE TABLE suppliers (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	phone VARCHAR(40), 
	email VARCHAR(120), 
	address VARCHAR(300), 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE TABLE endpoint_permissions (
	endpoint VARCHAR(120) NOT NULL, 
	method VARCHAR(10) NOT NULL, 
	permission_id INTEGER NOT NULL, 
	PRIMARY KEY (endpoint, method, permission_id), 
	FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE
)

;

CREATE TABLE products (
	id INTEGER NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	sku VARCHAR(60) NOT NULL, 
	barcode VARCHAR(80), 
	brand VARCHAR(80), 
	category_id INTEGER NOT NULL, 
	supplier_id INTEGER, 
	cost INTEGER NOT NULL, 
	price INTEGER NOT NULL, 
	stock INTEGER NOT NULL, 
	minimum INTEGER NOT NULL, 
	location VARCHAR(60), 
	image VARCHAR(120), 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	price_alerts BOOLEAN DEFAULT '1' NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (stock >= 0 AND cost >= 0 AND price >= 0 AND minimum >= 0), 
	UNIQUE (sku), 
	UNIQUE (barcode), 
	FOREIGN KEY(category_id) REFERENCES categories (id), 
	FOREIGN KEY(supplier_id) REFERENCES suppliers (id)
)

;
CREATE INDEX ix_products_category_id ON products (category_id);
CREATE INDEX ix_products_supplier_id ON products (supplier_id);

CREATE TABLE purchases (
	id INTEGER NOT NULL, 
	invoice VARCHAR(60) NOT NULL, 
	supplier_id INTEGER NOT NULL, 
	supplier_name VARCHAR(120) NOT NULL, 
	created_at DATETIME NOT NULL, 
	received_at DATETIME, 
	status VARCHAR(20) NOT NULL, 
	total INTEGER NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	note VARCHAR(500), 
	token VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (invoice), 
	FOREIGN KEY(supplier_id) REFERENCES suppliers (id), 
	UNIQUE (token)
)

;
CREATE INDEX ix_purchases_created_at ON purchases (created_at);

CREATE TABLE role_permissions (
	role_id INTEGER NOT NULL, 
	permission_id INTEGER NOT NULL, 
	PRIMARY KEY (role_id, permission_id), 
	FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
	FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE
)

;

CREATE TABLE users (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	username VARCHAR(80) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	role_id INTEGER NOT NULL, 
	active BOOLEAN NOT NULL, 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (username), 
	FOREIGN KEY(role_id) REFERENCES roles (id)
)

;

CREATE TABLE audit_logs (
	id INTEGER NOT NULL, 
	user_id INTEGER, 
	actor VARCHAR(100) NOT NULL, 
	action VARCHAR(80) NOT NULL, 
	details TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;

CREATE TABLE inventory_movements (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	balance INTEGER NOT NULL, 
	cost INTEGER NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	reference VARCHAR(100) NOT NULL, 
	user_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;
CREATE INDEX ix_inventory_movements_created_at ON inventory_movements (created_at);
CREATE INDEX ix_inventory_movements_product_id ON inventory_movements (product_id);

CREATE TABLE price_history (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	product_name VARCHAR(160) NOT NULL, 
	old_cost INTEGER NOT NULL, 
	new_cost INTEGER NOT NULL, 
	old_price INTEGER NOT NULL, 
	new_price INTEGER NOT NULL, 
	change_amount INTEGER NOT NULL, 
	change_percentage NUMERIC(18, 4), 
	cost_change_amount INTEGER NOT NULL, 
	cost_change_percentage NUMERIC(18, 4), 
	user_id INTEGER, 
	changed_by VARCHAR(100) NOT NULL, 
	created_at DATETIME NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	source VARCHAR(100) NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (old_cost>=0 AND new_cost>=0 AND old_price>=0 AND new_price>=0), 
	CHECK (change_amount=new_price-old_price AND cost_change_amount=new_cost-old_cost), 
	CHECK (old_cost!=new_cost OR old_price!=new_price), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;
CREATE INDEX ix_price_history_created_at ON price_history (created_at);
CREATE INDEX ix_price_history_product_recent ON price_history (product_id, id);
CREATE INDEX ix_price_history_product_id ON price_history (product_id);

CREATE TABLE product_images (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	file_path VARCHAR(255) NOT NULL, 
	file_name VARCHAR(120) NOT NULL, 
	is_primary BOOLEAN DEFAULT '0' NOT NULL, 
	sort_order INTEGER DEFAULT '0' NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_product_images_product_order ON product_images (product_id, sort_order);
CREATE INDEX ix_product_images_product_id ON product_images (product_id);

CREATE TABLE purchase_items (
	id INTEGER NOT NULL, 
	purchase_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	quantity INTEGER NOT NULL, 
	cost INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (quantity > 0 AND cost >= 0), 
	FOREIGN KEY(purchase_id) REFERENCES purchases (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
)

;
CREATE INDEX ix_purchase_items_purchase_id ON purchase_items (purchase_id);
CREATE INDEX ix_purchase_items_product_id ON purchase_items (product_id);

CREATE TABLE sales (
	id INTEGER NOT NULL, 
	invoice VARCHAR(60) NOT NULL, 
	customer_id INTEGER, 
	customer_name VARCHAR(120) NOT NULL, 
	user_id INTEGER NOT NULL, 
	cashier VARCHAR(100) NOT NULL, 
	created_at DATETIME NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	payment VARCHAR(30) NOT NULL, 
	subtotal INTEGER NOT NULL, 
	discount INTEGER NOT NULL, 
	tax INTEGER NOT NULL, 
	tax_rate INTEGER NOT NULL, 
	total INTEGER NOT NULL, 
	cost INTEGER NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	store_snapshot TEXT NOT NULL, 
	note VARCHAR(500), 
	token VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	pickup_date VARCHAR(10), 
	pickup_notes VARCHAR(300), 
	pickup_status VARCHAR(20), 
	cancel_reason VARCHAR(200), 
	cancelled_at DATETIME, 
	PRIMARY KEY (id), 
	CHECK (subtotal >= 0 AND discount >= 0 AND discount <= subtotal AND total >= 0), 
	UNIQUE (invoice), 
	FOREIGN KEY(customer_id) REFERENCES customers (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	UNIQUE (token)
)

;
CREATE INDEX ix_sales_status_created ON sales (status, created_at);
CREATE INDEX ix_sales_created_at ON sales (created_at);

CREATE TABLE user_permission_denials (
	user_id INTEGER NOT NULL, 
	permission_id INTEGER NOT NULL, 
	PRIMARY KEY (user_id, permission_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE
)

;

CREATE TABLE user_permission_grants (
	user_id INTEGER NOT NULL, 
	permission_id INTEGER NOT NULL, 
	PRIMARY KEY (user_id, permission_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE
)

;

CREATE TABLE sale_items (
	id INTEGER NOT NULL, 
	sale_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	category_name VARCHAR(100) NOT NULL, 
	quantity INTEGER NOT NULL, 
	price INTEGER NOT NULL, 
	cost INTEGER NOT NULL, 
	discount INTEGER DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (quantity > 0 AND price >= 0 AND cost >= 0), 
	CHECK (discount >= 0 AND discount <= quantity * price), 
	FOREIGN KEY(sale_id) REFERENCES sales (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
)

;
CREATE INDEX ix_sale_items_product_id ON sale_items (product_id);
CREATE INDEX ix_sale_items_sale_id ON sale_items (sale_id);

CREATE TABLE sale_payments (
	id INTEGER NOT NULL, 
	sale_id INTEGER NOT NULL, 
	method VARCHAR(30) NOT NULL, 
	amount INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (amount >= 0), 
	CHECK (method IN ('Cash','Visa','Mastercard','Bank Transfer','Wallet','Card','Mobile Wallet')), 
	CONSTRAINT uq_sale_payment_method UNIQUE (sale_id, method), 
	FOREIGN KEY(sale_id) REFERENCES sales (id)
)

;
CREATE INDEX ix_sale_payments_sale_id ON sale_payments (sale_id);

CREATE TABLE shipping_orders (
	id INTEGER NOT NULL, 
	order_number VARCHAR(30) NOT NULL, 
	sale_id INTEGER NOT NULL, 
	tracking_code VARCHAR(40), 
	tracking_url VARCHAR(300), 
	status VARCHAR(20) NOT NULL, 
	customer_id INTEGER, 
	customer_name VARCHAR(120) NOT NULL, 
	phone VARCHAR(40), 
	alt_phone VARCHAR(40), 
	governorate VARCHAR(80), 
	city VARCHAR(80), 
	district VARCHAR(80), 
	landmark VARCHAR(80), 
	street VARCHAR(160), 
	building VARCHAR(40), 
	floor VARCHAR(20), 
	apartment VARCHAR(20), 
	postal_code VARCHAR(20), 
	address_snapshot TEXT NOT NULL, 
	notes VARCHAR(500), 
	courier VARCHAR(80), 
	cancel_reason VARCHAR(200), 
	cancelled_at DATETIME, 
	shipping_cost INTEGER NOT NULL, 
	shipment_date VARCHAR(10), 
	delivered_by VARCHAR(120), 
	delivered_at DATETIME, 
	user_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (shipping_cost >= 0), 
	CHECK (status IN ('Pending','Packed','Preparing','Ready For Shipment','Shipped','Out For Delivery','Delivered','Failed Delivery','Returned','Cancelled')), 
	UNIQUE (order_number), 
	FOREIGN KEY(sale_id) REFERENCES sales (id), 
	UNIQUE (tracking_code), 
	FOREIGN KEY(customer_id) REFERENCES customers (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;
CREATE UNIQUE INDEX ix_shipping_orders_sale_id ON shipping_orders (sale_id);
CREATE INDEX ix_shipping_orders_created_at ON shipping_orders (created_at);

CREATE TABLE shipping_events (
	id INTEGER NOT NULL, 
	order_id INTEGER NOT NULL, 
	action VARCHAR(120) NOT NULL, 
	actor VARCHAR(100) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_id) REFERENCES shipping_orders (id)
)

;
CREATE INDEX ix_shipping_events_order_id ON shipping_events (order_id);
CREATE INDEX ix_shipping_events_created_at ON shipping_events (created_at);
CREATE TRIGGER IF NOT EXISTS price_history_no_update BEFORE UPDATE ON price_history BEGIN SELECT RAISE(ABORT, 'Price history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS price_history_no_delete BEFORE DELETE ON price_history BEGIN SELECT RAISE(ABORT, 'Price history is append-only'); END;
