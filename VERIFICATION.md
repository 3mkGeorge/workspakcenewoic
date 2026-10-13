# Verification record

Verified on Windows, 22 September 2026, using CPython 3.13.15.

- 57 automated tests passed (32 existing regressions and 25 POS checks).
- Python source compilation and selected fatal-error lint checks passed.
- JavaScript syntax checks passed.
- A fresh virtual environment installed all runtime dependencies with `--no-index` from the bundled wheel files.
- Dependency consistency check passed.
- The actual `run.bat` launcher created its environment, installed dependencies locally, and started the Waitress server.
- Browser checks exercised a barcode sale, verified the 14% VAT total, saved the invoice and displayed its details.
- Visually inspected dashboard, products, inventory, sales, reports and settings against the supplied references.
- Verified Arabic right-to-left settings and sale rendering; checked narrow/mobile catalog behavior.
- English and Arabic PDF/Excel exports exercised by integration tests.
- The distributed archive excludes runtime databases, passwords, session secrets, development environments, test backups, and preview credentials.

The automated suite is in `tests/test_app.py`; run it after any financial-rule or schema changes. Business conventions and supported workflow boundaries are documented in `README.md`.

## New Sale POS verification

- New Sale renders with local Bootstrap, scoped POS CSS and JavaScript; no new runtime dependency is required.
- Product search by name/SKU/barcode, Enter/arrow selection, rapid barcode entry, duplicate merging, stock limits, item/invoice discounts, F2 customer creation, split payments, F8 saving, receipt links, and refresh draft recovery were exercised in the isolated browser test store.
- Desktop, tablet, and phone layouts were inspected; no page-width overflow occurred at the narrow and tablet test sizes.
- POS integration checks cover exact VAT/profit arithmetic, invalid input and price tampering, atomic rollback, concurrent last-unit sales, payment allocation persistence, idempotent creation/confirmation recovery, stale revisions, refunds, roles, CSRF, legacy backup upgrades, and discounted product reports.
- The existing local store was upgraded with an automatic pre-upgrade SQLite backup. Every pre-existing business record was compared with the backup and preserved; integrity and foreign-key checks passed.
- Local server and POS static assets returned successfully after restart. Browser sample transactions were created only in the isolated preview store.
- Physical USB scanner hardware was not connected; scanner behavior was verified through rapid keyboard-wedge input.

## Product price tracking verification

- 69 automated tests passed: 57 existing checks and 12 price-tracking checks.
- Verified selling/cost snapshots, unchanged-price saves, rollback, purchase-driven weighted-average changes, immutable SQL history, zero-base percentages, exact-20% alert behavior, authorization/CSRF, price analytics, cursor pagination, last-30 chart bounds, exports, formula-safe spreadsheet text, and backup upgrade/restore.
- Browser checks in the isolated preview store verified the dark/light chart, price cards, arrow/percentage/amount indicators, alerts, ten-row older-history loading, and narrow-screen layout without page-width overflow.
- Generated a 34-record PDF from the actual export route and visually inspected its rendered first page.
- Live activation was not performed: Windows denied stopping the existing server process. Source files and restart.bat are ready; the live database has not been migrated by this update. Migration is tested on isolated copies and runs automatically on the next startup.


## Dual backup upgrade verification (22 September 2026)

- Release regression suite: 91 automated tests; details in tests/test_dual_backup.py and existing suites.
- Verified byte-identical concurrent copies, archive SHA-256/CRC/SQLite/image checks, two delivery log rows, media/settings/configuration inclusion, and excluded runtime session secrets.
- Verified a failed secondary destination preserves the primary copy and creates dashboard/log warnings; disk-full failures preserve older recovery points; invalid images cannot be reported as healthy archives.
- Verified retention per destination, uncompressed ZIP mode, commit-only live hooks, bulk stock hooks, no rollback/log recursion, and pending changes during an active backup.
- Verified all six schedule intervals, disabling schedules, persisted deadlines across restarts, and duplicate-job rejection.
- Slow-copy concurrency check: POS product requests and a committed customer write complete while both destination copies wait; backups hold no request lock.
- Verified normal restore from Primary and Secondary, pre-restore recovery snapshots, password and role enforcement, CSRF protection, tamper rejection, staged legacy upgrades and session invalidation.
- Simulated damaged, zero-byte and missing established databases. Recovery mode prevents accidental empty-store initialization; authenticated recovery from a healthy copy preserves the damaged files and restores login/data.
- Browser checks on an isolated seeded store: settings controls, successful manual dual backup, recovery point list, password/RESTORE modal, light/dark styling, narrow-screen cards, and no captured JavaScript errors. Measured phone DOM width 326px inside a 339px viewport, with no page overflow.
- Production database was not restored or replaced during validation. The live port-5000 process predates the source update; activation requires restarting StorePro. Physical D:/E: destinations were not selected or modified; configure them in Settings after restart.
- ZIP packages exclude instance data, upload contents, backup folders, virtual environments, caches and preview credentials. Per-file SHA-256 manifests and ZIP integrity are checked after packaging.


## Hybrid permissions — 22/09/2026

- Full regression suite: **105 passed** (53.58 seconds), including 14 hybrid authorization tests.
- Verified deny > additional grant > role; administrator denials; role changes retaining denials; custom permissions and endpoint bindings; delegated account escalation prevention; session revocation; stale-policy conflicts; reset/remove overrides; last recovery operator protection; CSRF and malformed input; price-change and purchase-receive checks; backup-settings denial; migration idempotence.
- Browser verified: searchable permission table, three distinct panels, summary cards, live role preview, existing dark appearance, and mobile/desktop layouts. No console errors observed on the permission editor. Browser work used an isolated demonstration database; no real user policies were changed.
- JavaScript syntax checks passed for permission editor, role policies, POS, and backup controls. Python authorization modules passed Ruff fatal-error checks.
- Application source and schema are updated. Restart the existing StorePro process to activate the migration and routes. The currently running process was not replaced.
