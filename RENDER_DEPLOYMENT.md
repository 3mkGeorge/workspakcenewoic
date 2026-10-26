# Deploying StorePro on Render

This document covers the Linux/Render deployment. The Windows installation in
`DEPLOYMENT_GUIDE.md` is unchanged and remains the recommended setup for a
single shop counter.

> **Status:** the repository is prepared for Render, but no Render service has
> been created from this checkout. A Render account/workspace and billing for a
> paid instance plus disk are required before the steps below can complete.

## Architecture

| Item | Choice | Reason |
| --- | --- | --- |
| Web server | Gunicorn, one worker, four threads (`gunicorn.conf.py`) | Production WSGI server. One process because StorePro owns one SQLite file, background backup/maintenance threads and a single persistent disk. |
| App entry point | `wsgi.py` → `create_app()` | `app.py` exposes a factory, not a module-level app. |
| Database | SQLite on a Render persistent disk | The backup/restore, schema upgrade, integrity check and dual-backup code all operate on the SQLite file and its WAL. PostgreSQL would require replacing those subsystems, not just the connection string. |
| Uploads | `static/uploads/` on the same disk | Product photos, thumbnails and the legacy image path remain where the application expects them. |
| Backups | `backups/` and `backups-secondary/` on the same disk | Existing dual-backup behaviour is preserved. See the limitation below. |
| Disk layout | Disk mounted at `/var/data`; folders linked into the app root before startup | StorePro resolves all persistent paths from its installation root. |

`scripts/render_start.sh` creates the disk folders and symlinks them into the
checkout, then starts Gunicorn on `0.0.0.0:$PORT`. Render's Python runtime
exports `GUNICORN_CMD_ARGS` with `--preload`; the script clears that variable.
Preloading would create the SQLite engine and background backup threads in the
Gunicorn master and then fork them away, which is unsafe for this application.

### Why a paid instance is required

Render persistent disks are available only on paid instance types. Render's
free web services lose all local files on restart, redeploy or idle spin-down,
which would delete the store database and photos. Free Render Postgres is not a
substitute because StorePro's SQLite-specific backup and recovery tooling is
part of the product.

The Blueprint uses `0.5c-512mb` (the entry paid instance) with a 5 GB disk.
Check current Render pricing before applying it.

## Files added for deployment

- `wsgi.py` — Gunicorn entry point.
- `gunicorn.conf.py` — one worker, thread-based concurrency, `PORT` binding.
- `scripts/render_start.sh` — persistent-disk preparation and process start.
- `requirements-prod.txt` — the pinned Windows lock plus Gunicorn.
- `render.yaml` — Render Blueprint.
- `.python-version` — Python 3.13.
- `RENDER_DEPLOYMENT.md` — this document.

`app.py` gained host-header validation, optional HTTPS-only cookies, proxy
header support, a `/healthz` probe and an optional first-run setup code. All
defaults preserve local Windows behaviour.

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `STOREPRO_DATA_DIR` | Yes (Blueprint sets `/var/data`) | Disk root used by the start script. |
| `STOREPRO_DATABASE_URI` | Yes | `sqlite:////var/data/instance/store.db` (four slashes: absolute path). |
| `STOREPRO_SECRET_KEY` | Yes | Session signing key. Generate once and keep stable. Blueprint: generated value. |
| `STOREPRO_AUTH_EPOCH` | Recommended | Invalidates every session when changed. Keep stable across deploys. Blueprint: generated value. |
| `STOREPRO_SETUP_TOKEN` | Yes for public hosting | Extra code required to create the first administrator. Blueprint: generated value; read it from the Render dashboard. |
| `STOREPRO_SECURE_COOKIES` | Yes on HTTPS | `1` adds the `Secure` flag to the session cookie. |
| `STOREPRO_TRUST_PROXY` | Yes on Render | Trust one edge proxy for client IP and HTTPS scheme. |
| `STOREPRO_TRUSTED_HOSTS` | Only for custom domains | Comma-separated extra hostnames, e.g. `store.example.com`. `RENDER_EXTERNAL_HOSTNAME` is accepted automatically. |
| `STOREPRO_THREADS` | Optional | Gunicorn request threads (default 4). |
| `PYTHON_VERSION` | Optional | `3.13.15`; also pinned by `.python-version`. |
| `NEXT_CHIP_SYNC_ENABLED` / `NEXT_CHIP_SYNC_URL` / `NEXT_CHIP_SYNC_SECRET` | Optional | Website catalogue sync. Leave disabled unless configured with the storefront. |

Do not set `FLASK_DEBUG`. StorePro never enables Flask debug mode; Gunicorn
does not either.

## First deployment (Blueprint)

1. Sign in at <https://dashboard.render.com> and confirm the workspace has a
   payment method (the service and disk are paid).
2. **New → Blueprint**, connect GitHub, choose `3mkGeorge/workspakcenewoic`
   and branch `main`.
3. Review the service: `storepro`, region Frankfurt, instance `0.5c-512mb`,
   disk `storepro-data` at `/var/data` (5 GB), health check `/healthz`.
4. Apply. Render builds with `pip install -r requirements-prod.txt` and starts
   `bash scripts/render_start.sh`.
5. Open the service's **Environment** page and copy the generated
   `STOREPRO_SETUP_TOKEN`.
6. Open `https://<service>.onrender.com/setup`, enter the setup code and create
   the administrator. There is no default account or password.
7. Sign in and create the rest of the users/roles in **Settings → Users**.

### Manual service instead of a Blueprint

Use the same values:

- Runtime: Python 3
- Build command: `pip install -r requirements-prod.txt`
- Start command: `bash scripts/render_start.sh`
- Health check path: `/healthz`
- Disk: mounted at `/var/data`, 5 GB
- Environment variables: as in the table above
- Instance count: **1** (a disk cannot be shared or autoscaled)

## Bringing existing shop data

Do not commit `instance/store.db` or uploads to Git. Use StorePro's tested
backup/restore path instead:

1. On the Windows store PC, open **Backups** and create a backup; download the
   `.zip` to the machine you will use for the browser.
2. Complete the Render first-run setup above.
3. On Render, open **Backups → Restore**, choose the downloaded archive, enter
   the archive password/confirmation required by the UI and restore.
4. StorePro validates the archive, replaces the database and copies the
   photos, then signs everyone out. Sign in again.
5. Verify products, stock, orders and images before using the hosted copy as
   the live system.

Restoring replaces everything currently in the hosted database. Keep the
Windows installation and its backups until the hosted copy has been verified.

## Updates

```powershell
git add .
git commit -m "Describe the change"
git push origin main
```

With `autoDeployTrigger: commit`, Render rebuilds and redeploys on every push
to `main`. Because the service has a disk, Render stops the old instance before
starting the new one, so expect a short outage per deploy. Schema upgrades run
at startup through the existing `upgrade_sqlite` path and create a pre-upgrade
database copy on the disk.

## Persistence, uploads and backups

- **Database:** persists on the disk across restarts and deploys.
- **Uploads:** persist on the disk; `/static/uploads/...` continues to serve
  them.
- **Application logs:** `instance/logs/` on the disk; deployment logs also go to
  the Render log stream.
- **Backups:** both "primary" and "secondary" now live on the same disk. They
  survive restarts but are **not** an off-site copy. Download important
  archives regularly, or configure `backup_primary` / `backup_secondary` to two
  different writable locations if an external volume is available.
- **Render disk snapshots:** Render snapshots the disk daily and keeps seven
  days. Do not rely on a disk snapshot as the only business backup.
- **Scaling:** not supported with a disk. Do not raise the instance count, add
  autoscaling, or run a second web service against the same SQLite file.
- **Free plan:** do not use it; data is erased on every restart and idle
  spin-down.

## Health check

`GET /healthz` is public, returns `{"status":"ok","database":"ok"}` with HTTP
200 when the app and database respond, and HTTP 503 in recovery mode or when
the database is unavailable. It is exempt from login/setup redirects and does
not expose secrets.

## Security notes

- The session cookie is `HttpOnly`, `SameSite=Strict` and `Secure` on Render.
- CSRF protection remains enabled globally for state-changing requests.
- Authorization is unchanged: the existing database-backed role/permission
  system still gates every business route.
- `TRUSTED_HOSTS` rejects requests with an unexpected `Host` header. Add custom
  domains through `STOREPRO_TRUSTED_HOSTS`.
- The first-run page is public but requires `STOREPRO_SETUP_TOKEN` when that
  variable is set.
- `.env`, `instance/`, SQLite files, logs and new uploads/backups are ignored by
  Git.

## Limitations and known issues

- SQLite is single-writer. The one-worker/four-thread setup matches the
  application's design, but this deployment is not horizontally scalable.
- A disk-backed service cannot use zero-downtime deploys.
- Existing repository history still contains old sample archives under
  `backups-secondary/` and test artefacts under `.pytest_temp/`. They are not
  used at runtime, but because the repository is public they should be removed
  from history in a separate, deliberate cleanup.
- The pre-existing test failures listed in the deployment report are unrelated
  to Render and stem from tests that assume a folder named `store-app` and a
  populated local `instance/store.db`.
