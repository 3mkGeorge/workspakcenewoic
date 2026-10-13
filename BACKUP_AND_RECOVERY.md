# StorePro v1.0 – Backup & Disaster Recovery Guide

StorePro includes an automated, dual-destination cryptographic backup system engineered to withstand hardware failure, storage corruption, ransomware attacks, and power outages.

---

## 1. Dual-Destination Backup Architecture

StorePro automatically creates two identical, validated backup copies on every scheduled or manual run:

```
[StorePro Live DB (store.db)]
              |
              v (Online SQLite Snapshot via source.backup())
    [Staging Temp Archive]
              |
      +-------+-------+
      |               |
      v               v
 [Primary Vault] [Secondary Vault]
(Local Disk: C:)  (External USB / UNC Share: D:)
```

### Destination Strategy
1. **Primary Destination:** Defaults to `backups/` on the local machine drive. Provides instant access for routine rollbacks.
2. **Secondary Destination:** Defaults to `backups-secondary/`. **Recommended configuration:** An external USB drive, dedicated second physical disk, or secure local network share (UNC path).
3. **Physical Separation Warning:** If both destinations share the same physical drive anchor (e.g. both on drive `C:`), StorePro displays an administrative warning urging drive separation.

---

## 2. Backup Schedules & Automation

Configure backup frequency in **Settings** -> **Backup & Recovery**:
- **Automatic Backup:** Enable or disable automatic scheduling.
- **Frequency Options:**
  - `Every 15 Minutes`
  - `Every 30 Minutes`
  - `Every Hour`
  - `Every 6 Hours`
  - `Daily`
  - `Weekly`
- **Live Change Trigger:** When enabled, any financial or catalog mutation flags the backup worker to initiate a fresh backup during the next idle tick.
- **Unlimited Retention:** StorePro deliberately never prunes or deletes historical backup archives. Archives are retained permanently unless manually deleted by an administrator with physical filesystem access.

---

## 3. Cryptographic Archive Format & Validation

StorePro backup archives are packaged as portable `.zip` containers named with strict timestamp and UUID identifiers:
`storepro-YYYYMMDD-HHMMSS-<token>.zip`

### Archive Members
- `store.db`: Complete SQLite database snapshot created via SQLite's online backup API (`source.backup()`).
- `manifest.json`: Cryptographic manifest containing backup timestamp, schema version, and individual SHA-256 hashes of all archive members.
- `settings.json` & `configuration.json`: Exported business metadata and system configuration.
- `uploads/*`: Full-resolution and thumbnail images for all catalog products and store logos.

### Security Defenses During Inspection
Every archive is validated via `inspect_archive()` before ingestion or restoration:
- **Zip Slip Defense:** Rejects any entry containing path traversal sequences (`..`, leading slashes).
- **Expansion Boundary:** Restricts archive extraction to at most 8 GB to eliminate decompression bomb attacks.
- **SHA-256 Hash Matching:** Every file in the archive must match the cryptographic hash recorded in `manifest.json`.
- **Deep Database Validation:** The internal `store.db` is inspected using `PRAGMA integrity_check` and `PRAGMA foreign_key_check` inside a sandbox before live application tables are modified.

---

## 4. Routine Restoration Procedure (Web UI)

*Use when the server is operating normally and an authorized administrator wants to revert the store to a prior recovery point.*

1. Log in as an Administrator with the `backups.approve` permission.
2. Navigate to **Settings** -> **Backup & Recovery** (`/settings#backup`).
3. In the **Available Recovery Points** list, locate the target snapshot. Verify timestamp, file size, and location.
4. Click **Restore**.
5. Type your **Administrator Password** and enter the uppercase confirmation word **`RESTORE`**.
6. Click **Verify & Restore**.
7. **What Happens Automatically:**
   - StorePro creates a pre-restore emergency rollback copy in `instance/pre-restore-<token>.sqlite3`.
   - The backup is validated in a temporary sandbox.
   - Live database connections are safely disconnected (`db.engine.dispose()`).
   - The database is replaced atomically.
   - All active user sessions are invalidated (`AUTH_EPOCH` renewal) to ensure security.
8. Re-authenticate at the sign-in screen.

---

## 5. Emergency Disaster Recovery (`/recovery`)

*Use when the database has suffered corruption, disk errors, or invalid edits, and normal sign-in is inaccessible.*

When database corruption is detected, StorePro automatically locks normal operations and redirects browser requests to:
```
http://127.0.0.1:5000/recovery
```

### Emergency Restore Steps
1. Navigate directly to `http://127.0.0.1:5000/recovery` in your browser.
2. Select a recovery point from the dropdown list (newest healthy copy listed first).
3. Enter your **Administrator Username** and **Password** (verified securely against the offline recovery cache `instance/backup-recovery.json`).
4. Type **`RESTORE`** in the confirmation field.
5. Click **Verify & Recover Store**.
6. **Forensic Safety Feature:**
   - StorePro moves the damaged database file and its WAL journals into a timestamped directory `instance/corrupt-<token>/`. No damaged data is ever deleted.
   - The validated backup replaces `store.db`.
   - `RECOVERY_MODE` is cleared, and normal operations resume immediately without restarting the server.

---

## 6. Command-Line & Bare-Metal Disaster Recovery

*Use for scripted automation or when recovering to a brand-new computer after catastrophic hardware destruction.*

### Verification via CLI
```powershell
.venv\Scripts\python manage.py verify
```
Verifies structural integrity and foreign key constraints on the current live database.

### Manual Backup via CLI
```powershell
.venv\Scripts\python manage.py backup
```
Triggers an immediate dual-destination backup and prints destination statuses.

### Restoring on Fresh Hardware
1. Unpack StorePro on the new computer.
2. Copy your backup archive (e.g. `storepro-20261002-180000-abcdef.zip`) to the machine.
3. Run the following command in PowerShell:
```powershell
.venv\Scripts\python -c "
import sys
from pathlib import Path
from app import create_app
from services.backups import restore_backup

app = create_app({'BACKUP_WORKER': False})
with app.app_context():
    archive_file = Path('path/to/your/backup.zip')
    restore_backup(archive_file, emergency=True)
    print('Restore completed successfully.')
"
```
4. Verify database health:
```powershell
.venv\Scripts\python manage.py verify
```
5. Launch `run.bat` and sign in.
