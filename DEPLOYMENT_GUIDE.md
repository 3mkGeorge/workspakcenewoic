# StorePro v1.0 – Production Deployment & System Hardening Guide

This guide describes how to install, configure, secure, and operate StorePro in production commercial retail environments on Microsoft Windows.

---

## 1. System Requirements

### Workstation / Server Requirements
- **Operating System:** Microsoft Windows 10 (64-bit), Windows 11 (64-bit), or Windows Server 2019 / 2022.
- **CPU:** Dual-core 2.0 GHz or higher (Quad-core recommended for multi-lane network POS setups).
- **RAM:** Minimum 4 GB RAM (8 GB recommended).
- **Disk Storage:** Minimum 10 GB free space on solid-state drive (NVMe or SSD strongly recommended for SQLite WAL write performance).
- **Secondary Physical Drive:** Dedicated external USB 3.0 drive, second internal drive, or SMB/UNC network share for secondary backup vaulting.
- **Python Runtime:** Python 3.13 (64-bit).

---

## 2. Air-Gapped / Offline Installation

StorePro packages all required dependencies inside the `wheels/` directory, allowing 100% offline, air-gapped installation without internet access.

### Step-by-Step Installation
1. **Download & Extract:** Copy the StorePro application bundle to your production destination, e.g.:
   ```
   C:\StorePro
   ```
2. **Verify Python 3.13:** Open Command Prompt or PowerShell and confirm Python 3.13 64-bit:
   ```powershell
   python --version
   ```
   If Python is not installed, install it from Python's official installer, ensuring **"Add Python to PATH"** is selected.
3. **Execute `run.bat`:** Double-click `run.bat`.
   - The script creates the isolated `.venv` virtual environment.
   - It installs all 23 pinned production wheels from `wheels/` using `requirements-lock.txt`.
   - It verifies environment health, creates instance keys, and starts the production Waitress server.
4. **Access Setup:** Open your browser and navigate to `http://127.0.0.1:5000`. Complete the initial administrator registration.

---

## 3. Production Configuration & Environment Variables

StorePro can be configured using environment variables set in the host operating system or system service profile:

| Variable | Default Value | Description |
|---|---|---|
| `STOREPRO_PORT` | `5000` | TCP listening port for the web application. |
| `STOREPRO_HOST` | `127.0.0.1` | Network binding interface. Use `0.0.0.0` to permit LAN cashier access. |
| `STOREPRO_SECRET_KEY` | *(Auto-generated)* | Cryptographic session signing key. Defaults to persistent `instance/secret.key`. |
| `STOREPRO_DATABASE_URI` | `sqlite:///instance/store.db` | SQLAlchemy connection string. |
| `STOREPRO_MAX_CONTENT_LENGTH` | `33554432` (32 MB) | Maximum permitted HTTP payload size. |
| `STOREPRO_CSRF_TIME_LIMIT` | `28800` (8 hours) | Expiration time for CSRF tokens. |

---

## 4. Multi-Terminal LAN Deployment (Multiple Cash Registers)

To allow secondary cashier workstations or tablets on the same local network (LAN) to connect to the StorePro host:

1. **Bind to Local Network:** Set `STOREPRO_HOST` to `0.0.0.0` in the startup script or environment.
2. **Configure Windows Defender Firewall:**
   - Open **Windows Defender Firewall with Advanced Security**.
   - Create a **New Inbound Rule**:
     - Rule Type: **Port**
     - Protocol: **TCP**
     - Specific local ports: **5000**
     - Action: **Allow the connection**
     - Profile: **Domain / Private** (Never enable on Public networks).
     - Name: **StorePro POS Gateway**
3. **Connect Secondary Registers:** On secondary counter tablets or workstations, open the browser and navigate to the host computer's static LAN IP, e.g.:
   ```
   http://192.168.1.100:5000
   ```
4. **Login Cashiers:** Cashiers sign in with their assigned accounts. StorePro strictly isolates permissions so cashier terminals have zero access to administrative settings or financials.

---

## 5. Running StorePro as a Continuous Windows Service

To ensure StorePro automatically starts upon computer reboot without requiring an operator to stay logged in:

### Method A: Windows Task Scheduler (Recommended)
1. Open **Task Scheduler** (`taskschd.msc`).
2. Click **Create Task** (not Basic Task).
3. Name: `StorePro Retail Server`.
4. General:
   - Check **Run whether user is logged on or not**.
   - Check **Run with highest privileges**.
5. Triggers:
   - Begin the task: **At startup**.
   - Delay task for: **15 seconds** (ensures storage drives are mounted).
6. Actions:
   - Action: **Start a program**
   - Program/script: `C:\StorePro\run.bat`
   - Start in: `C:\StorePro`
7. Settings:
   - Check **If the task fails, restart every 1 minute**.
   - Uncheck **Stop the task if it runs longer than**.

### Method B: NSSM (Non-Sucking Service Manager)
```powershell
nssm install StorePro "C:\StorePro\.venv\Scripts\python.exe" "C:\StorePro\app.py"
nssm set StorePro AppDirectory "C:\StorePro"
nssm set StorePro Start SERVICE_AUTO_START
nssm start StorePro
```

---

## 6. Pre-Flight Acceptance Checklist

Before handing the workstation over for daily retail use:

- [ ] **Database Integrity:** Run `.venv\Scripts\python manage.py verify` -> confirm integrity and foreign key checks pass.
- [ ] **Dual Backup Verification:**
  - Verify Primary path (`backups/`) and Secondary path (`backups-secondary/` or USB drive) are accessible and writable.
  - Trigger manual backup via Settings and verify archive creation in both folders.
- [ ] **Admin Account Security:** Ensure the initial administrator password is at least 12 characters and stored in the store vault.
- [ ] **Crash Diagnostics Verified:** Access `/settings` to ensure disk usage, WAL status, and backup counters display green indicators.
- [ ] **Thermal Printer & Barcode Test:** Execute a test cash sale, print receipt, scan printed barcode, and confirm stock decrements accurately.
