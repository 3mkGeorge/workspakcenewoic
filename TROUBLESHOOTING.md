# StorePro v1.0 – Production Incident & Troubleshooting Guide

This playbook provides structured diagnostics and recovery steps for common operational, system, and hardware incidents.

---

## 1. Diagnostic Triage & Log Inspection

Whenever StorePro exhibits unexpected behavior, consult the rotating application logs located in the `instance/` directory:

- **Human-Readable Application Log:**
  ```
  instance/application.log
  ```
  Contains timestamped INFO, WARNING, and ERROR traces with incident IDs.
- **Structured JSON Telemetry Log:**
  ```
  instance/logs/application.json
  ```
  Contains machine-parsable JSON lines detailing HTTP request IDs, exception stack traces, and database execution timings.

---

## 2. Server Startup & Process Issues

### Issue A: "StorePro is already running. Close the existing server before starting another server..."
- **Root Cause:** A StorePro instance is currently running, or an orphaned Python process is holding `instance/server.lock`.
- **Resolution:**
  1. If another console window is open running `run.bat`, switch to it and close it with `Ctrl + C`.
  2. If no window is visible, run **`restart.bat`** from the application directory. `restart.bat` gracefully identifies and terminates any stranded background `app.py` process holding the virtual environment executable.
  3. Alternatively, check Windows Task Manager for `python.exe` processes and end them.

### Issue B: "Python 3.13 for Windows x64 is required..."
- **Root Cause:** The system does not have Python 3.13 64-bit installed in PATH or registered with the Windows Python Launcher (`py -3.13`).
- **Resolution:**
  1. Download and install **Python 3.13 (64-bit)** from [python.org](https://www.python.org/downloads/).
  2. Ensure the installer checkbox **"Add Python to PATH"** is checked.
  3. Rerun `run.bat`.

### Issue C: Port 5000 Already in Use
- **Root Cause:** Another local application or Windows service is listening on port `5000`.
- **Resolution:**
  1. You can launch StorePro on an alternate port by setting the `STOREPRO_PORT` environment variable:
     ```powershell
     $env:STOREPRO_PORT="5050"
     .\run.bat
     ```
  2. Navigate to `http://127.0.0.1:5050`.

---

## 3. Database & Storage Incidents

### Issue D: "The database is currently busy processing another request. Please retry in a moment." (HTTP 503)
- **Root Cause:** High-volume concurrent transactions or an intensive reporting query temporarily exceeded the SQLite busy timeout (15 seconds).
- **Resolution:**
  1. Wait a moment and refresh the page or resubmit the form. StorePro uses SQLite WAL mode, meaning multiple readers execute in parallel with writers.
  2. Ensure the SQLite database file resides on local solid-state storage (SSD/NVMe). Never place the active live database file on slow network drives or USB 2.0 thumb drives (backups can go to network/USB, but `instance/store.db` should be on local SSD).

### Issue E: Browser Redirects to `/recovery` (Database Corruption Detected)
- **Root Cause:** The database file encountered byte corruption, sudden disk write errors, or hard power cut during non-WAL disk writes.
- **Resolution:**
  1. The emergency recovery portal `/recovery` loads automatically.
  2. Select the newest healthy backup snapshot from the dropdown list.
  3. Enter your administrator username and password.
  4. Type `RESTORE` and click **Verify & Recover Store**.
  5. StorePro safely moves the damaged files to `instance/corrupt-<token>/` and restores the healthy snapshot.

### Issue F: "Disk full: insufficient space for the backup" / "Insufficient disk space to save image"
- **Root Cause:** The installation drive or secondary backup drive has run out of storage space (`ENOSPC`).
- **Resolution:**
  1. Check free disk space on drives hosting `instance/`, `backups/`, and `backups-secondary/`.
  2. If the secondary drive (e.g. USB flash drive) is full, attach a larger drive or update the secondary backup path in **Settings** -> **Backup & Recovery**.
  3. Temporary `.uploading` and `.partial` files are cleaned up automatically by StorePro to prevent compounding disk waste.

---

## 4. Authentication & User Session Incidents

### Issue G: "Your form expired. Reload the page and try again." (CSRF Error)
- **Root Cause:** A browser tab remained open for longer than the CSRF validity window (default: 8 hours), or the server restarted and renewed the secret key without persistence.
- **Resolution:**
  1. Refresh the web page in your browser. Draft data stored in the local POS cart is preserved automatically.
  2. Ensure `instance/secret.key` is persistent and not being wiped by external cleanup scripts.

### Issue H: Administrator Locked Out / Forgotten Password
- **Root Cause:** Administrator credentials were lost or inadvertently locked.
- **Resolution:**
  1. Access the workstation filesystem.
  2. Check if a secondary administrator exists or restore a recent backup where the password was known.
  3. If necessary, use Python via the virtual environment console to update the password hash:
     ```powershell
     .venv\Scripts\python -c "
     from app import create_app
     from models import db, User
     from werkzeug.security import generate_password_hash
     app = create_app()
     with app.app_context():
         admin = User.query.filter_by(username='admin').first()
         admin.password_hash = generate_password_hash('NewSecurePassword123!')
         db.session.commit()
         print('Password reset successfully.')
     "
     ```

---

## 5. Catalog & Missing Image Files

### Issue I: Product Displays Package Icon Instead of Photo
- **Root Cause:** An image file was manually removed or deleted from the `static/uploads/` directory on disk.
- **Resolution:**
  1. StorePro's resilient macro design prevents missing image files from triggering 500 errors; missing images automatically degrade to the clean SVG package icon.
  2. To restore the image, navigate to **Inventory** -> **Products**, edit the product, and upload a replacement image.
