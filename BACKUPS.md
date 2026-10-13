# Dual Backup System

## Setup and upgrade

Finish active work and close the existing StorePro server. Extract the cumulative `StorePro-Dual-Backup-Update.zip` over the installation, keeping `instance`, `static/uploads`, and both backup folders. Run `run.bat`, or `restart.bat` to restart this installation. Startup saves a pre-upgrade SQLite recovery copy and transactionally adds `backup_logs`. Earlier POS and price-history database upgrades remain supported.

Open **Settings → Dual Backup Settings** or the Backup page's **Backup Destinations** section. Set absolute Primary and Secondary Backup Folder paths anywhere on the machine — for example `D:\Backups` and `E:\StoreProBackups`, external USB drives, or UNC shares such as `\\server\backup` — then Save. Blank fields use this installation's `backups` and `backups-secondary` folders. Missing folders are created after confirmation and write-tested. Use separate physical drives for disk-failure protection. The dashboard warns about matching drive letters; different drive letters alone do not prove physical independence.

## Automatic operations

Live backup, daily scheduling, compression and integrity verification are enabled by default. Every committed product, stock, invoice, purchase, customer, supplier, category, expense, account or settings change signals the worker. Rolled-back changes and backup-log writes do not trigger backups. Bursts are coalesced; changes committed during a backup schedule another snapshot. A startup snapshot captures changes left pending by shutdown. Live backup is asynchronous recovery protection, not synchronous mirroring of each transaction.

Choose Every 15 Minutes, Every 30 Minutes, Every Hour, Every 6 Hours, Daily or Weekly. Interval deadlines survive restarts and overdue runs resume when StorePro opens. Schedules run only while the application is running. Windows sleep, shutdown and unavailable storage delay completion. Failed automatic deliveries retry after one minute while live backup is enabled; failed scheduled runs remain due. One worker prevents overlapping operations.

**Backup Now** queues immediately. SQLite's online backup API creates a consistent snapshot without acquiring the application's request lock. Compression happens once. Two copy threads then deliver the same ZIP concurrently to both destinations, each with its own outcome. A disconnected destination does not prevent the other copy from succeeding. A stalled filesystem call can delay the job's final completion, but does not hold the UI/request lock.

Each destination writes a temporary file, flushes it, compares its checksum to the source archive, verifies it, and atomically renames it. Incomplete copies never appear as recovery points. The local staging drive also needs space for the SQLite snapshot and ZIP. New uploads are published atomically to prevent partially written images entering a backup.

## Archive format and retention

Version-2 archives contain:

- `store.db`: consistent SQLite snapshot, including settings and price history.
- `uploads/*.png`: immutable product images and current/historic logos.
- `settings.json`: settings from that database snapshot.
- `configuration.json`: portable, inert configuration, timezone and backup preferences.
- `manifest.json`: format version, UTC creation time and SHA-256 per member.

Runtime session secrets, cached recovery credentials, source code and virtual environments are excluded. No executable configuration is restored or executed. Keep the distributed source package separately. Backup ZIPs contain business data and database password hashes; store them in folders protected by the Windows account's permissions.

Disabling compression produces an uncompressed ZIP. Full verification checks ZIP CRCs, manifest hashes, SQLite integrity and foreign-key references. With full verification disabled, archive readability and source/destination equality remain mandatory. Restore always performs full verification.

Retention is **unlimited**: every backup copy is preserved permanently until manually deleted by the user. No automatic deletion, pruning job, or cleanup runs. Backup folders may grow without limit; the Backup page shows total copies and storage used as informational data only. Unrelated files, incomplete files and local emergency snapshots are never touched. Delivery logs remain available.

## Dashboard and logs

Settings shows the last archive time, next scheduled run, latest size, total copies, destination health, and a combined list of restore points. Dates use Cairo time in **DD/MM/YYYY HH:mm**. Choose Primary or Secondary to filter. Each row offers Download and Restore. Logs record backup ID, time, Auto/Manual type, Live/Scheduled/Manual reason, status, size, location and error per destination.

Health checks run about every 30 seconds and after jobs. The main dashboard warns about unavailable paths, failed jobs, low disk space and unreadable archives. UI requests use cached state rather than waiting on a disconnected drive. Status polling does not extend login inactivity timeouts.

## Restore

Select a copy from either location, or upload a StorePro ZIP. Enter the current administrator password and type **RESTORE**. Attempts are throttled; CSRF protection and administrator authorization are enforced. Validation runs in the background, including traversal/expansion limits, checksums, schema compatibility, automatic legacy upgrades, database integrity, active administrator presence, stock and invoice consistency, settings and image validity.

Only the final replacement acquires the request lock. Finish active sales before restoring. The current database is saved to `instance/pre-restore-*.sqlite3`; existing immutable images remain available. Normal database replacement uses SQLite's atomic backup transaction. All sessions end on success. Log in with an account from the restored backup. Store/business settings return to their saved values; this machine's backup paths and preferences are preserved. Restore outcomes also appear in Audit Logs.

Uploads are limited to **32 MB compressed**. Place larger archives in either configured folder. All archives are bounded to **8 GB expanded and 100,000 members**. Recovery duration depends on archive size and disk speed; it is not instantaneous. Version-1 StorePro archives remain supported. Image filename collisions with different contents are rejected.

## Emergency recovery

At startup, and after a detected runtime SQLite corruption error, StorePro opens `/recovery` instead of creating an empty store. Both destinations are scanned and healthy archives are offered newest first. Full restore validation still runs on the chosen archive.

The local `instance/backup-recovery.json` cache contains path configuration and hashed active-administrator credentials. It is refreshed by the worker after committed changes, allowing password confirmation when the database cannot be read. No plaintext administrator password is cached. Protect and preserve the instance folder. If corruption occurs before the cache is updated, use the credentials in its last successful update.

Recovery preserves the damaged database and journals in `instance/corrupt-*`, replaces the damaged file with a validated copy and resumes normal login without restarting the server. If recovery credentials or every healthy backup are unavailable, authenticated automatic recovery cannot proceed; preserve the instance folder for administrator-assisted recovery. Emergency and pre-restore snapshots are kept permanently alongside regular backups.

## Maintenance and API

Stop the server before running `manage.py backup`. It writes both copies, prints each result and exits with failure if either destination fails. Maintenance commands do not start a second scheduler. `manage.py schema` generates all table/index definitions and price-history protection triggers.

| Method | Route | Behavior |
| --- | --- | --- |
| POST | `/settings/backup` | Admin + CSRF; queue job, return 202 or busy 409 |
| GET | `/api/backups/status` | Admin; cached job and destination state |
| GET | `/settings/backup-logs?page=1` | Admin; paginated per-destination logs |
| GET | `/settings/backups/<name>?source=Secondary` | Admin; download from selected folder |
| POST | `/settings/restore` | Admin password + RESTORE + CSRF; queue validated restore |
| GET/POST | `/recovery` | Damaged-database recovery; POST requires cached admin credentials |
| GET | `/api/recovery/status` | Recovery-page health/progress metadata only |

Backup configuration lives in the existing `settings` table. `backup_logs` is additive; no existing business rows are rewritten. Scheduling state is persisted separately in `instance/backup-schedule.json`. The application remains localhost-only and requires no cloud service or additional Python dependency.
