# TraceAPL

TraceAPL is a Flask/SQLite web application for tracking physical samples with pre-printed QR/barcode labels, handoff records, characterization assignments, Denodo-assisted form filling, assignment notifications, reminders, and admin maintenance tools.

## Current Release: v3 Public Workflows + Admin Login + Denodo CHAR HAND OFF Sync

This release removes the requirement for normal users to log in before using TraceAPL sample-tracking workflows while retaining the built-in administrator account for admin-only functions.

### Authentication and access control

- Normal TraceAPL sample-tracking pages do **not** require TraceAPL usernames or passwords.
- Users who can reach TraceAPL through the approved network/SSO boundary can use sample creation, scanning, search, generated QR, handoffs, characterization workflows, and sample photos.
- Administrator functions still require the built-in admin login.
- The built-in administrator account is controlled by server environment variables:
  - `TRACEAPL_ADMIN_USERNAME`, default: `admin`
  - `TRACEAPL_ADMIN_PASSWORD`, default for development only: `change-me`
- The admin login protects admin-only pages such as backups, system audit, user management, sample edit/archive/restore, and Denodo CHAR HAND OFF sync controls.
- Self-registration, normal-user login, remember-device login, and user password-change workflows are disabled because normal TraceAPL access no longer uses application-level user accounts.
- Admin activity and admin access denials are logged in the TraceAPL audit trail. Public sample-tracking activity is recorded without a TraceAPL username unless a workflow field identifies a person.

### Password policy

TraceAPL enforces the following password policy for the built-in administrator password configured by `TRACEAPL_ADMIN_PASSWORD`:

- Passwords must be at least 15 characters.
- Passwords do not expire by default or by policy.
- Passwords must include at least 3 of the following 4 character types:
  - lowercase letters
  - uppercase letters
  - numbers
  - special characters
- Passwords may not include the configured admin username.
- The built-in admin password is blocked at login if `TRACEAPL_ADMIN_PASSWORD` does not meet this policy.

The minimum length can be overridden for development only with `TRACEAPL_PASSWORD_MIN_LENGTH`, but shared use should retain 15 characters or stronger.

### Core sample tracking

- Create samples from pre-printed QR/barcodes.
- Create manual samples without QR/barcodes.
- Create samples with a TraceAPL-generated QR value when no physical sticker is available.
- Scan/lookup existing samples.
- Generate/reprint QR labels for scanned-code, manual, and generated-code samples.
- Upload optional sample photos for additional material identification/tracking.
- Record sample handoffs/transfers.
- Track current owner, current location, status, notes, and Work Program.
- Export CSV data.


### Optional sample photos

TraceAPL supports optional photo uploads for each sample. Photos can be uploaded during sample creation or added later from the sample detail page. Supported image types are JPG, PNG, GIF, and WEBP. Uploaded files are stored under `sample_uploads/` and referenced by the SQLite database.

Runtime photo files are not committed to GitLab. Preserve `sample_uploads/` during VM updates and include it in local backup procedures alongside `sample_tracker_web.db`.

Configuration:

```powershell
$env:TRACEAPL_SAMPLE_PHOTO_MAX_MB="10"
```

### Generated QR labels without preprinted stickers

If a sample does not already have a physical QR/barcode sticker, use **Generate QR** or **Generate QR From Scratch**. TraceAPL creates a unique internal tracking value, saves it with the sample record, and allows the custom QR code to be printed later from the sample detail page using **Reprint QR Code**.

### Work Program behavior

- Work Program is the primary program/project grouping field.
- Older `project` and `task` columns are retained for database compatibility.
- Older project/task data migrates into `work_program` automatically at startup.
- Sample IDs only need to be unique within the same Work Program.
- The same Sample ID may exist in different Work Programs.

### Denodo autocomplete/tagging

TraceAPL supports Denodo-backed autocomplete for employee, Work Program, and location fields.

Default Denodo views/fields:

- Employee/person lookup: `dim_hr_person`
- Work Program lookup:
  - URL: `https://denodo.jhuapl.edu:9443/denodo-restfulws/addit/views/dim_work_program`
  - Field: `work_program_name`
- Location lookup:
  - URL: `https://denodo.jhuapl.edu:9443/denodo-restfulws/APL_Common/views/loc_room_locations`
  - Field: `location_display_id`

### Notifications and reminders

- Email notification when a characterization task is assigned.
- Weekly email reminders for incomplete assigned characterization tasks.
- Reminders stop when a task is marked complete.
- SMTP settings are controlled by environment variables.

### Admin tools

- Built-in admin login.
- Manual database backup.
- Download latest backup.
- Edit sample details.
- Edit characterization tasks.
- Archive samples instead of hard deleting them.
- Restore archived samples.
- View audit trail.
- Manage self-registered users.

### HTTPS/mobile scanning

- Supports ad-hoc HTTPS for testing: `TRACEAPL_SSL=adhoc`.
- Supports real cert/key pairs: `TRACEAPL_SSL=certs\\traceapl.cer,certs\\traceapl.key`.
- Mobile scanner page: `/mobile/scan`.
- Mobile barcode scanning requires `static/vendor/html5-qrcode.min.js` to be present locally.


## Architecture Diagram Location

TraceAPL architectural diagrams are maintained in the standardized project location:

```text
docs/architecture/
```

This folder is the documented reference location for system architecture, deployment architecture, authentication flow, data flow, and external integration diagrams. Appropriate project staff with GitLab repository access should use this location for system understanding, maintenance, security review, and change-impact analysis.

Architecture diagrams are version-controlled through GitLab and should be updated when material changes affect hosting, authentication, authorization, data flows, integrations, database structure, audit logging, or CUI handling assumptions. The folder contains a dedicated `README.md` describing the available diagrams and maintenance procedure.

## Required runtime files to preserve during updates

Do not overwrite or commit these runtime/local files:

- `sample_tracker_web.db`
- `backups/`
- `.venv/`
- `.env`
- `certs/`
- `static/vendor/html5-qrcode.min.js`
- `sample_uploads/`

## Important security notes

- Do not commit credentials, certificates, private keys, `.env`, backups, or SQLite databases.
- Set a real `TRACEAPL_ADMIN_PASSWORD` before shared use. It must meet the TraceAPL password policy.
- The built-in admin account is intended to be controlled by the site owner through environment variables.
- Self-registration assumes TraceAPL is already protected by approved network/SSO controls.

## Example PowerShell launch

```powershell
cd C:\path\to\traceapl
.venv\Scripts\Activate.ps1

$env:TRACEAPL_HOST="0.0.0.0"
$env:TRACEAPL_PORT="5000"
$env:TRACEAPL_SSL="certs\traceapl.cer,certs\traceapl.key"

$env:TRACEAPL_ADMIN_USERNAME="admin"
$env:TRACEAPL_ADMIN_PASSWORD="your-private-admin-password"
$env:TRACEAPL_REMEMBER_DAYS="14"

$env:TRACEAPL_EMPLOYEE_LOOKUP_MODE="rest"
$env:DENODO_EMPLOYEE_REST_URL="https://denodo.jhuapl.edu:9443/denodo-restfulws/addit/views/dim_hr_person"
$env:DENODO_USERNAME="bregmag1"
$env:DENODO_PASSWORD="your-denodo-password"
$env:DENODO_EMPLOYEE_USE_SERVER_FILTER="true"

$env:DENODO_WORK_PROGRAM_REST_URL="https://denodo.jhuapl.edu:9443/denodo-restfulws/addit/views/dim_work_program"
$env:DENODO_LOCATION_REST_URL="https://denodo.jhuapl.edu:9443/denodo-restfulws/APL_Common/views/loc_room_locations"

$env:TRACEAPL_EMAIL_ENABLED="true"
$env:TRACEAPL_EMAIL_REMINDERS_ENABLED="true"
$env:TRACEAPL_SMTP_HOST="mymail.jhuapl.edu"
$env:TRACEAPL_SMTP_PORT="587"
$env:TRACEAPL_SMTP_TLS="1"
$env:TRACEAPL_SMTP_FROM="avi.bregman@jhuapl.edu"
$env:TRACEAPL_SMTP_USERNAME="avi.bregman@jhuapl.edu"
$env:TRACEAPL_SMTP_PASSWORD="your-email-password"

python app.py
```


## System Audit Logging

TraceAPL includes an admin-only system audit log for security and system activity monitoring. The system audit log records login success/failure, login-required redirects, admin access denials, account creation and password actions, data exports, backup creation/download, and system-audit exports. Each record includes timestamp, username, role, event type, outcome, target, source IP address, browser user agent, request method/path, and details.

System audit records are retained for two years by default. Override with:

```powershell
$env:TRACEAPL_SYSTEM_AUDIT_RETENTION_DAYS="730"
```

Admins can review the log at `/admin/system-audit` and export it as CSV.

## Personnel Action Access Procedure

TraceAPL uses application-level accounts in addition to any organizational network, VM, or SSO controls that protect access to the hosted environment. Personnel actions that affect a user's need for TraceAPL access must be reflected in TraceAPL by an administrator.

This procedure applies when a user is terminated, transfers to another role or organization, changes responsibilities, no longer has a need to use TraceAPL, or gains/loses administrator responsibilities.

### Procedure

1. The TraceAPL owner or administrator receives notice that a personnel action may affect TraceAPL access.
2. The administrator reviews the user's TraceAPL account and role.
3. If access is no longer required, the administrator disables the account in the admin-only user-management page.
4. If access is still required but responsibilities changed, the administrator updates the user's role or privileges as appropriate.
5. If there is a password or account-integrity concern, the administrator resets the user's password or disables the account until the concern is resolved.
6. The administrator verifies that the affected user no longer has inappropriate access.
7. The personnel-action update is recorded by TraceAPL system audit logging.

### TraceAPL support for personnel actions

TraceAPL provides the following controls to support personnel-action processing:

- Admin-only user management.
- User account disable/reactivate capability.
- Admin password reset for user accounts.
- Separation between the built-in `admin` account and normal self-registered users.
- Role separation between administrator and normal user access.
- System audit logging of user-management and access-control events.
- Two-year system audit retention by default.

### Active Directory / SSO note

If TraceAPL is deployed behind organizational Active Directory or SSO controls, AD/SSO may prevent terminated or unauthorized users from reaching the TraceAPL environment. However, because TraceAPL also maintains application-level user accounts, the TraceAPL administrator should still disable or update the corresponding TraceAPL account when a personnel action changes the user's need for application access or administrator privileges.


## Denodo CHAR HAND OFF Sync

TraceAPL can import samples from the Denodo `APL_Engineering` work-order views when a work-order operation is tagged with `CHAR HAND OFF`.

Workflow:

1. Query `ve_wo_ops` for `OPERATION_TYPE=CHAR HAND OFF`.
2. Extract `WORKORDER_BASE_ID`.
3. Query `ve_wo` with the base ID.
4. Build TraceAPL Work Program / Project ID as `WAREHOUSE_ID` + `WBS_CODE`.
5. Create a TraceAPL sample when no active sample already exists with the same Work Program and Batch/Lot.

Created samples use:

- `Sample ID` = `WORKORDER_BASE_ID`
- `Batch/Lot` = `WORKORDER_BASE_ID`
- `Work Program` = `WAREHOUSE_ID` + `WBS_CODE`
- `Location` = `15-W114A` by default
- `Sample Type` = `CHAR HAND OFF`

Duplicate prevention is based on active samples with the same `work_program` and `batch_lot` values.

### Sync environment variables

```powershell
$env:TRACEAPL_WORK_AUTH_SYNC_ENABLED="true"
$env:TRACEAPL_WORK_AUTH_SYNC_DRY_RUN="true"     # start true, then switch to false after validation
$env:TRACEAPL_WORK_AUTH_SYNC_HOUR="8"
$env:TRACEAPL_WORK_AUTH_NOTIFY_EMAIL="avi.bregman@jhuapl.edu"
$env:TRACEAPL_WORK_AUTH_DEFAULT_LOCATION="15-W114A"

$env:DENODO_WORK_AUTH_OPS_REST_URL="https://denodo.jhuapl.edu:9443/denodo-restfulws/APL_Engineering/views/ve_wo_ops"
$env:DENODO_WORK_AUTH_WO_REST_URL="https://denodo.jhuapl.edu:9443/denodo-restfulws/APL_Engineering/views/ve_wo"
$env:DENODO_WORK_AUTH_OPERATION_FIELD="OPERATION_TYPE"
$env:DENODO_WORK_AUTH_OPERATION_VALUE="CHAR HAND OFF"
$env:DENODO_WORK_AUTH_OPS_BASE_ID_FIELD="WORKORDER_BASE_ID"
$env:DENODO_WORK_AUTH_WO_BASE_ID_FIELD="BASE_ID"
$env:DENODO_WORK_AUTH_WAREHOUSE_FIELD="WAREHOUSE_ID"
$env:DENODO_WORK_AUTH_WBS_FIELD="WBS_CODE"
$env:DENODO_WORK_AUTH_PROJECT_SEPARATOR=""
```

The sync uses the existing `DENODO_USERNAME`, `DENODO_PASSWORD`, `DENODO_TIMEOUT_SECONDS`, and `DENODO_VERIFY_SSL` settings.

Admins can review and manually run the sync from:

```text
/admin/work-auth-sync
```

The embedded daily maintenance check runs after the configured hour when the app receives traffic. For a reliable exact 8 AM run, use Windows Task Scheduler to run:

```powershell
cd C:\path\to\traceapl
.venv\Scripts\Activate.ps1
python run_char_handoff_sync.py --commit
```

Omit `--commit` for dry-run mode.

## External TraceAPL watchdog

TraceAPL cannot send an alert after its own Python process has already stopped. For down alerts, use the included external watchdog script with Windows Task Scheduler.

Example settings:

```powershell
$env:TRACEAPL_WATCHDOG_URL="https://traceapl-host:5000/login"
$env:TRACEAPL_WATCHDOG_NOTIFY_EMAIL="avi.bregman@jhuapl.edu"
$env:TRACEAPL_WATCHDOG_TIMEOUT_SECONDS="20"
```

The watchdog uses the same SMTP variables as TraceAPL:

```powershell
$env:TRACEAPL_SMTP_HOST="mymail.jhuapl.edu"
$env:TRACEAPL_SMTP_PORT="587"
$env:TRACEAPL_SMTP_TLS="1"
$env:TRACEAPL_SMTP_FROM="avi.bregman@jhuapl.edu"
$env:TRACEAPL_SMTP_USERNAME="avi.bregman@jhuapl.edu"
$env:TRACEAPL_SMTP_PASSWORD = Read-Host "Email/SMTP password"
```

Run manually:

```powershell
python traceapl_watchdog.py
```

Schedule it every 5-10 minutes in Windows Task Scheduler. It sends a down email only when the state changes from reachable to unreachable, and a recovery email when TraceAPL becomes reachable again.
