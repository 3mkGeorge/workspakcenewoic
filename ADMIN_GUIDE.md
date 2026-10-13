# StorePro v1.0 – Administrator & Store Owner Guide

This guide details configuration, security administration, user account governance, audit review, and maintenance procedures for StorePro administrators and store proprietors.

---

## 1. Initial Setup & Global Settings

Navigate to **Settings** (`/settings`) to configure store identities and business policies:

### Store Profile
- **Store Name:** Printed on all invoices, receipts, and reports.
- **Store Logo:** Upload a PNG, JPG, or WebP logo (scaled automatically, stored in `static/uploads/`).
- **Contact Info:** Phone numbers, store physical address, and support email.
- **Receipt Header & Footer:** Custom notes printed on customer receipts (e.g. tax registration numbers, return policies, warranty terms).

### Financial & Localization Settings
- **Currency:** Supports `EGP`, `USD`, `EUR`, `SAR`, and `AED`. Currency formatting automatically adheres to localized decimal norms.
- **Tax Rate (%):** Default VAT/sales tax rate calculated on gross line items. Set to `0` if tax is not collected.
- **Language:** English (`en`) or Arabic (`ar`). Switching toggles full interface localization and Right-to-Left (RTL) typography.
- **Session Duration:** Idle timeout before users are logged out (range: 5 to 480 minutes; default: 60 minutes).

---

## 2. User & Access Policy Administration

StorePro enforces Role-Based Access Control (RBAC) with user-specific grants and denials.

### User Account Management (`/settings/users`)
- **Creating Users:** Click **Add User**. Provide full name, lowercase username, and a strong password (minimum 12 characters).
- **Assigning Roles:** Choose from built-in roles:
  - **Admin:** Unrestricted store management, system settings, backup controls, and user policy management.
  - **Manager:** Catalog editing, stock receiving, price updates, discounts, and reporting. Restricted from system backups and policy definitions.
  - **Cashier:** Point of Sale, customer creation, and cash drawer transactions. Restricted from reports, cost data, and settings.
- **Disabling Accounts:** Toggle **Active** off. Disabled accounts are immediately denied entry, and active browser sessions are terminated.

### Custom Policies & Granular Overrides (`/settings/permissions`)
StorePro evaluates effective permissions according to the strict rule:
$$\text{Effective Access} = (\text{Role Permissions} \cup \text{User Grants}) \setminus \text{User Denials}$$

- **Explicit Denials Override Grants:** If an administrator or cashier is explicitly assigned a *Denial* on a permission (e.g., `sales.discount` or `backups.restore`), the denial strictly wins, overriding any role permissions.
- **Editing Role Grants:** Select a role to toggle its permission baseline. Changes affect all assigned users upon their next HTTP request.
- **Granular User Overrides:** Navigate to a specific user's permission screen to grant specific exceptions (e.g. allowing a senior cashier to issue refunds without giving them manager status).

---

## 3. Product Catalog & Media Governance

### Product Creation & Stock Thresholds
- **SKU & Barcode:** Must be unique across the catalog.
- **Cost & Retail Price:** Stored in exact integer piastres/cents to prevent floating-point rounding errors.
- **Reorder Threshold (Minimum Stock):** Triggers automatic visual badges and dashboard warnings when stock drops below this number.

### Multi-Image Product Gallery
- Products support multiple high-resolution images.
- Images are automatically resized into:
  - Full-size optimized WebP/JPEG (1600x1600 max).
  - Compact table thumbnails (320x320 max).
- If an image file on disk is lost or deleted, the frontend displays an SVG package icon without throwing 500 errors.

### Bulk Import & Export (`/products`)
- **Import Catalog:** Upload CSV or JSON files. StorePro validates SKUs, categories, and numerical formats before inserting.
- **Export Catalog:** Download current catalog, pricing, and stock counts as a portable CSV or JSON archive.

---

## 4. Auditing, Compliance & Diagnostics

### Audit Log Viewer (`/settings/audit`)
Every security-sensitive or financial action is recorded in the immutable audit ledger:
- **Recorded Events:** User login attempts, password changes, permission updates, inventory adjustments, price edits, invoice revisions, and backup restorations.
- **Search & Filters:** Filter logs by action keyword, actor username, or calendar date range.

### System Diagnostics & Monitoring
The top of the Admin Settings panel displays real-time health metrics:
- **Database Engine:** Confirms SQLite WAL mode status.
- **Database File Size:** Monitored dynamically to forecast storage needs.
- **Backup Vault Health:** Displays replica status across both primary and secondary destinations.
- **Failed Backup Alerts:** Prominently flags any storage or permissions failures.

### Automated Database Maintenance
StorePro executes background maintenance according to scheduled intervals:
- **Integrity Check:** Runs `PRAGMA integrity_check` and `PRAGMA foreign_key_check`.
- **Database Vacuum & Reindex:** Reclaims unused space and rebuilds btree indices to sustain sub-millisecond query performance on large catalogs.
