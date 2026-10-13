# StorePro Release Readiness & Operational Runbooks

This document provides checklists and operational guidelines for deploying, upgrading, and recovering StorePro instances in commercial production environments.

---

## 1. Deployment Checklist

Perform these steps when preparing a fresh or staged deployment on target Windows workstations or servers:

### Pre-Deployment Environment
- [ ] **Host OS & Architecture**: Windows 10/11 (64-bit) or Windows Server 2019/2022.
- [ ] **Runtime**: Python 3.13 (64-bit) installed or accessible via PATH / Windows py launcher (`py -3.13`).
- [ ] **Storage Footprint**: Minimum 2 GB free disk space on target installation drive (10 GB recommended for high-volume catalogs and archival backup retention).
- [ ] **Secondary Drive**: Mount or configure a separate physical drive (e.g. `D:\StorePro-Backups` or network UNC share) for dual-destination backup isolation.

### Application Configuration
- [ ] **Process Concurrency Lock**: Verify `instance/server.lock` directory permissions allow read/write for the runtime user account.
- [ ] **Storage Directories**: Confirm write permissions on:
  - `instance/` (SQLite database file `store.db`, WAL, and shared lock)
  - `backups/` (Primary encrypted backup vault)
  - `backups-secondary/` (Configured secondary backup vault)
  - `static/uploads/` (Product media, catalog thumbnails)
- [ ] **Offline Wheel Package Verification**: Confirm `wheels/` folder contains required pre-compiled offline wheels and `requirements-lock.txt` is intact.

### Database Initialization & Verification
- [ ] **Database & Migrations**: Launch `run.bat` or run `.venv\Scripts\python manage.py verify`.
- [ ] **SQLite WAL Verification**: Confirm `PRAGMA journal_mode` evaluates to `wal` and `PRAGMA foreign_keys = ON`.
- [ ] **Index Validation**: Verify high-volume indexes exist (`ix_sales_status_created`, `ix_products_sku`, `ix_products_supplier_id`, `ix_sale_items_sale_id`, `ix_sale_items_product_id`).

### Security Pre-Flight
- [ ] **First Run Admin Setup**: Navigate to `http://127.0.0.1:5000/`. Ensure the initial prompt demands strong admin credentials.
- [ ] **Secret Key & Session Cookies**: Ensure `SECRET_KEY` is persistently generated in `instance/` or configured via environment variables. Verify session cookies have `HttpOnly` and `SameSite=Lax`.
- [ ] **CSRF Protection**: Verify CSRF token enforcement is active (`WTF_CSRF_ENABLED=True` outside of automated test fixtures).
- [ ] **Role Fencing**: Verify `Cashier` role is strictly restricted to POS, Cash drawer, and basic sales history, with zero access to `/settings`, `/backup`, `/reports`, or system diagnostics.

### Smoke Testing
- [ ] Log in as Administrator.
- [ ] Verify Dashboard Diagnostics:
  - Database Status shows `Online (WAL)`
  - Database Size displays size and page count
  - Disk Usage displays free capacity
  - Backup Status displays healthy replica counts
  - Backup Alerts show `0 Alerts`
- [ ] Execute test sale in POS and verify stock movement is recorded.
- [ ] Trigger manual backup via Settings -> Backups and verify SHA-256 archive creation.

---

## 2. Upgrade Checklist

Perform these steps whenever updating an existing StorePro deployment to a new software release:

### Phase 1: Pre-Upgrade Precautions
- [ ] **Graceful Shutdown**: Stop the running StorePro server process (`Ctrl+C` in console or terminate service). Ensure `instance/server.lock` is released.
- [ ] **Full Manual Cold Snapshot**:
  - Copy `instance/store.db`, `instance/store.db-wal`, `instance/store.db-shm` to a safe temporary snapshot directory (`snapshots/pre_upgrade_<timestamp>/`).
  - Copy `backups/` and `static/uploads/` to the snapshot directory.
- [ ] **Database Integrity Pre-Check**:
  ```powershell
  .venv\Scripts\python manage.py verify
  ```
  Ensure integrity check and foreign key check both return `PASSED`.

### Phase 2: Codebase & Dependency Sync
- [ ] **Source Code Deployment**: Apply updated release files over the application root.
- [ ] **Dependency Update**:
  ```powershell
  .venv\Scripts\python -m pip install --no-index --find-links wheels -r requirements-lock.txt
  ```
- [ ] **Automated Migration Execution**:
  - Run the application once or trigger database upgrade:
    ```powershell
    .venv\Scripts\python -c "from app import create_app; from services.migrations import run_migrations; app = create_app();"
    ```
  - Schema migrations will execute idempotently (adding any new columns, tables, and indexes without dropping existing data).
- [ ] **Regenerate Schema Contract**:
  ```powershell
  .venv\Scripts\python manage.py schema
  ```

### Phase 3: Post-Upgrade Verification
- [ ] **Verify Database Health**:
  ```powershell
  .venv\Scripts\python manage.py verify
  ```
- [ ] **Run Automated Test Suite**:
  ```powershell
  .venv\Scripts\pytest -v
  ```
- [ ] **Static Asset Cache Buster**: Verify updated JS and CSS bundles load cleanly in client browsers.
- [ ] **Start Production Process**: Run `run.bat` and verify that the dashboard loads without schema or permission errors.

### Phase 4: Rollback Procedure (If Upgrade Fails)
- [ ] Immediately stop the application process.
- [ ] Restore `instance/store.db*`, `backups/`, and `static/uploads/` from `snapshots/pre_upgrade_<timestamp>/`.
- [ ] Revert codebase to previous release tag.
- [ ] Start application and verify operational baseline.

---

## 3. Disaster Recovery Checklist

In the event of hardware failure, disk corruption, ransomware incidents, or accidental data loss, execute the following disaster recovery plan:

### Scenario A: Operational Restore via Web UI (Settings)
*Use when the application server is still operational and the administrator wishes to restore from a known-good backup snapshot.*
- [ ] Navigate to `Settings` -> `Backup & Restore` (`/settings#backup`).
- [ ] Locate the desired recovery point from the **Available Snapshots** list (verify timestamp, size, and SHA-256 fingerprint).
- [ ] Click **Restore**.
- [ ] Enter the backup encryption password.
- [ ] Wait for automated archive decompression, schema validation, and table reload.
- [ ] System automatically restarts the SQLite connection and reloads the dashboard.

### Scenario B: Emergency Recovery UI (`/recovery`)
*Use when normal authentication is compromised or database tables are damaged, but the web process is running.*
- [ ] Navigate directly to `http://127.0.0.1:5000/recovery`.
- [ ] Enter the **Recovery Key** (found in `instance/recovery.key` or physical store vault safe).
- [ ] Select or upload the target `.zip` backup archive.
- [ ] Supply the archive password.
- [ ] Click **Execute Emergency Restore**.
- [ ] The system performs:
  1. Zip slip path rejection and size boundary audit.
  2. Whitelist validation of database and media assets.
  3. Atomic replacement of `store.db`.
  4. Automatic migration to ensure forward schema compatibility.
  5. Foreign key and structural integrity verification.

### Scenario C: Headless / Command-Line Bare-Metal Recovery
*Use when setting up a replacement machine from scratch after a total hardware destruction.*
- [ ] **Step 1: Install Prerequisites**: Install Python 3.13 64-bit on the new workstation.
- [ ] **Step 2: Deploy Fresh Application Bundle**: Unpack StorePro distribution zip.
- [ ] **Step 3: Setup Virtual Environment**: Run `run.bat` once to install dependencies from `wheels/`, then terminate.
- [ ] **Step 4: Retrieve Backup Archive**: Retrieve latest encrypted `.zip` from Secondary backup disk or off-site cloud vault.
- [ ] **Step 5: Execute Offline Restore Script**:
  ```powershell
  .venv\Scripts\python -c "
  import sys
  from pathlib import Path
  from app import create_app
  from services.dual_backup import restore_backup
  app = create_app({'BACKUP_WORKER': False})
  with app.app_context():
      archive_path = Path('C:/path/to/StorePro_Backup.zip')
      password = input('Enter backup password: ').strip()
      res = restore_backup(archive_path, password=password)
      print('Restore outcome:', res)
  "
  ```
- [ ] **Step 6: Integrity Verification**:
  ```powershell
  .venv\Scripts\python manage.py verify
  ```
  Confirm output:
  - `Integrity check: PASSED`
  - `Foreign key check: PASSED`
- [ ] **Step 7: Production Service Start**: Launch `run.bat`. Verify customer records, catalog, price histories, and users.
