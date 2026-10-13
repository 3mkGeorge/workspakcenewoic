# StorePro v1.0.0 "Rock of Gibraltar" – Official Release Notes

**Release Date:** October 2, 2026  
**Version:** 1.0.0  
**Build Status:** Production Ready (216 Passed / 0 Regressions)  
**Supported Platforms:** Windows 10, Windows 11, Windows Server 2019/2022 (x64)

---

## 1. Overview

StorePro v1.0.0 represents the inaugural long-term stable (LTS) release of the StorePro retail management and Point of Sale (POS) workstation application. Designed from first principles for mission-critical retail environments, StorePro combines local-first offline resilience, zero-cloud dependency, strict SQLite ACID transactions, cryptographic dual-destination backups, and an accessible, modern SaaS interface.

---

## 2. Key Capabilities & Feature Highlights

### Point of Sale (POS) & Checkout
- **Instant Product Lookups:** Barcode scanner ready with fast sub-millisecond prefix, SKU, and full-text searches.
- **Transactional Atomicity:** Zero stock drift and zero orphaned invoice items under power loss or sudden process termination.
- **Split Payment Processing:** Seamlessly split bills across Cash, Visa, Mastercard, Bank Transfer, and Digital Wallets with penny-exact balance validation.
- **Invoice & Thermal Receipt Generation:** Automated bilingual (English & Arabic) printable invoices with barcode visualizer and print-preview modes.
- **Order Fulfillment:** Direct support for in-store pickup and doorstep delivery tracking with status transitions.

### Inventory & Catalog Management
- **Multi-Image Product Gallery:** High-performance media pipeline generating optimized WebP thumbnails and modal galleries with automatic fallback to vector SVG icons when files are missing.
- **Strict Stock Controls:** Real-time stock alerts (In Stock, Low Stock, Out of Stock), batch inventory adjustments, and immutable inventory movement ledgers.
- **Pricing & Promotion Engine:** Support for markup/margin tracking, customer tier pricing, and automated price change history audit triggers.
- **Bulk Import/Export:** Two-way CSV and JSON catalog import and export with strict schema validation.

### Security & Access Control (RBAC)
- **Granular Permissions Engine:** Explicit role policies (`Admin`, `Manager`, `Cashier`) augmented by user-specific grants and overrides.
- **Denial Priority Rule:** `Deny > Grant > Role`. Explicit denials override role privileges for all accounts, including administrators.
- **Session Revocation Epochs:** Instant invalidation of active sessions across all devices upon password alteration, account disabling, or backup restore.
- **Protection Architecture:** Zero-trust HTTP security headers, SameSite strict cookie scoping, scrypt password hashing, and CSRF token defenses.

### Dual-Destination Backup & Disaster Recovery
- **Automatic Dual Archiving:** Parallel replication to Primary and Secondary physical paths (e.g., local disk + external USB drive or network share).
- **Cryptographic Verification:** SHA-256 manifest checks, Zip Slip path traversal defenses, zip bomb expansion caps (8 GB limit), and SQLite deep integrity checks.
- **Emergency Recovery Portal (`/recovery`):** Standalone web recovery portal operational even when the primary database is damaged or unreadable.
- **Forensic Preservation:** Corrupted databases and journals are automatically preserved in `instance/corrupt-*` before restoring validated backups.

### Telemetry, Maintenance & Operations
- **Diagnostic Dashboard:** Live system health indicators (Database Status, Backup Health, Storage Usage, Latency, and Alerts).
- **Automated DB Maintenance:** Configurable background maintenance scheduler executing SQLite `VACUUM`, `REINDEX`, `PRAGMA integrity_check`, and WAL checkpointing.
- **Structured Logging:** Dual output logging to human-readable text and machine-parsable JSON lines with automatic 2 MB log rotation.
- **Single-Instance Enforcement:** Kernel-level file locking (`msvcrt.locking`) preventing concurrent process database corruption while guaranteeing automatic release upon sudden process exit.

---

## 3. Versioning Strategy

StorePro follows **Semantic Versioning 2.0.0** (`MAJOR.MINOR.PATCH`):
- **MAJOR (v1.x -> v2.0):** Incompatible schema rewrites or major architectural shifts requiring offline manual migration.
- **MINOR (v1.0 -> v1.1):** Additive features, non-breaking schema additions, and new report or hardware integrations.
- **PATCH (v1.0.0 -> v1.0.1):** Bug fixes, performance optimizations, security patches, and localized translations.

### Schema Migration Contract
Database schema upgrades are strictly forward-compatible and additive. Application startup inspects database version metadata and executes non-destructive SQLite migrations automatically (`services/migrations.py`). Downgrades are accomplished by restoring the pre-upgrade snapshot saved in `backups/`.

---

## 4. Quality & Reliability Verification

StorePro v1.0.0 has completed rigorous verification cycles:
- **Test Suite Results:** **216 passed tests in 150.40s** (100% pass rate).
- **Real-World Failure Simulations (Step 0):**
  - Sudden shutdown & power loss during active sale (verified zero stock drift).
  - Power loss during backup creation (verified `.partial` staging isolation).
  - Catastrophic database corruption (verified automated `/recovery` portal detection and restore).
  - Corrupt zip archives & bad credentials (verified 100% live database preservation).
  - Storage exhaustion (`ENOSPC`) across uploads and backups.
  - SQLite lock contention (verified HTTP 503 retry without false-positive recovery triggers).
- **Accessibility & UX QA:** WCAG 2.1 AA/AAA compliance, `:focus-visible` keyboard rings, skip links, and full responsiveness across 5 viewports (Mobile 375px to Ultrawide 1920px+).

---

## 5. Upgrade & Deployment Summary

- **Prerequisites:** Windows 10/11 or Windows Server (x64), Python 3.13 (x64).
- **Distribution:** Offline wheel package included in `wheels/` allowing zero-internet air-gapped installation.
- **Execution:** Launch `run.bat` for standard execution or `restart.bat` to cycle the background server.
