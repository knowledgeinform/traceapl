
## v3-public-workflows-admin-login

Changed:
- Removed the requirement for normal users to log in before accessing TraceAPL sample-tracking workflows.
- Kept the built-in `admin` login for administrator-only functions.
- Updated navigation to show **Admin Login** instead of normal user login.
- Disabled self-registration and normal user password-change workflows.
- Admin-only routes continue to use `@admin_required` protection and system audit logging.
- Public sample-tracking pages remain accessible to users who can reach TraceAPL through the approved network/SSO boundary.

## v3 Sample Photos + Generated QR + Banner Removal

Added/Changed:
- Removed the page-wide APL system-use/CUI notice banner from the shared base template.
- Added optional sample photo uploads during sample creation.
- Added optional photo upload from existing sample detail pages.
- Added `sample_photos` database table for photo metadata.
- Added authenticated photo-serving route and admin-only photo deletion.
- Added `sample_uploads/` runtime storage for uploaded sample images.
- Added TraceAPL-generated tracking values for samples created when no preprinted QR/barcode sticker is available.
- Added **Generate QR** workflow and navigation option.
- Updated README to document sample photos, generated QR behavior, and the need to preserve `sample_uploads/` during updates.

# TraceAPL Changelog

## v3-denodo-char-handoff-sync

Added:
- Admin-only Denodo CHAR HAND OFF sync page at `/admin/work-auth-sync`.
- Daily sync capability after 8 AM server-local time when enabled with `TRACEAPL_WORK_AUTH_SYNC_ENABLED=true`.
- Manual dry-run and create-samples buttons for validating Denodo imports.
- Denodo REST import from `ve_wo_ops` filtered by `OPERATION_TYPE=CHAR HAND OFF`.
- Follow-on `ve_wo` lookup to build Work Program / Project ID from `WAREHOUSE_ID` + `WBS_CODE`.
- Automatic sample creation with Sample ID and Batch/Lot set to `WORKORDER_BASE_ID`.
- Duplicate prevention using active sample Work Program + Batch/Lot.
- Default location `15-W114A` for imported CHAR HAND OFF samples.
- Email notification to `avi.bregman@jhuapl.edu` for each new imported sample.
- System audit and application audit records for sync runs and created samples.
- `run_char_handoff_sync.py` for Windows Task Scheduler execution at a reliable daily time.
- `traceapl_watchdog.py` external watchdog for down/recovery email alerts.

Changed:
- README documents CHAR HAND OFF sync configuration, daily scheduling, and watchdog setup.

## v3-apl-system-use-notice

Changed:
- Replaced the short CUI handling banner with the approved APL system-use notice.
- The notice appears on every TraceAPL page through the shared base template.
- Updated banner styling to support the longer required notice text.

## v3-auth-documentation

Added:
- Required login for TraceAPL pages.
- Self-registration with username/password only.
- Built-in reserved `admin` account controlled by `TRACEAPL_ADMIN_USERNAME` and `TRACEAPL_ADMIN_PASSWORD`.
- Blocked self-registration of the reserved admin username.
- Remember-device login option with a 14-day default.
- User change-password page.
- Admin user-management page.
- Admin password reset for normal user accounts.
- Admin enable/disable controls for normal user accounts.
- Audit logging for registration, login, logout, password changes, password resets, and user enable/disable events.
- README documentation for current functionality and runtime configuration.
- CHANGELOG for version-to-version changes.

Changed:
- Admin login now happens through the main login page using the reserved admin username.
- Navigation now shows the current logged-in username and a logout button.

## v3-cui-banner

Added:
- Static banner on every page: “TraceAPL is configured for CUI handling in accordance with APL requirements.”

## v3-sample-id-unique-by-workprogram

Changed:
- Sample IDs only need to be unique within the same Work Program.
- Same Sample ID can exist in different Work Programs.
- Manual sample tracking keys include Work Program context to avoid collisions.

## v3-denodo-form-tags-field-mapping-fix

Added/Changed:
- Denodo-backed Work Program autocomplete uses `work_program_name`.
- Denodo-backed location autocomplete uses `location_display_id`.
- Location view defaults to `APL_Common/views/loc_room_locations`.

## v3-denodo-form-tags

Added:
- Denodo-backed autocomplete/tagging for Work Program fields.
- Denodo-backed autocomplete/tagging for location/storage fields.
- Denodo-backed employee lookup applied to transfer and person fields.

## v3-admin-edit-audit-softdelete-workprogram-fix

Added/Changed:
- Admin edit sample details.
- Admin edit characterization tasks.
- Audit trail for admin edits.
- Archive/restore sample behavior instead of permanent deletion.
- Work Program saves and displays consistently.
- Old project/task data migrates into Work Program.

## v3-email-denodo-reminders

Added:
- Denodo REST employee autocomplete.
- Email notification on characterization assignment.
- Weekly email reminders for incomplete assigned characterization tasks.

## v3-mobile-scanning

Added/Changed:
- Mobile scanner page.
- Rear-camera preference.
- Local `html5-qrcode.min.js` scanner library support.
- HTTPS launch support with `TRACEAPL_SSL`.

## Earlier v3 foundations

Added:
- Flask/SQLite browser app.
- QR/barcode assignment and lookup.
- Manual sample creation.
- Handoff tracking.
- Characterization checklist.
- QR label reprint.
- CSV exports.
- Admin backup/download controls.


## v3 System Audit Layer

- Added dedicated `system_audit_log` table for security/system activity records.
- Added two-year audit retention by default using `TRACEAPL_SYSTEM_AUDIT_RETENTION_DAYS=730`.
- Added admin-only system audit page and CSV export.
- Logged login success/failure, login-required redirects, admin access denial, registration, logout, password changes/resets, user enable/disable, backup create/download, and data export events.
- Added IP address, user agent, request method/path, outcome, target, and details to system audit records.

## v3 Personnel Action Documentation

Added:
- README section documenting the personnel-action access procedure for terminations, transfers, role changes, and changes in need-to-use/need-to-know.
- Documented administrator responsibilities for disabling accounts, updating roles, resetting passwords, and verifying access changes.
- Documented that TraceAPL system audit logging records user-management and access-control events.
- Clarified the relationship between organizational AD/SSO controls and TraceAPL application-level accounts.

## v3 Architecture Diagram Location

Added:
- Standardized architecture-diagram location at `docs/architecture/`.
- Architecture folder README documenting where diagrams are stored, who should use them, and when they should be updated.
- Initial Mermaid architecture diagrams for system context, deployment architecture, authentication flow, and data flow.
- Root README section identifying `docs/architecture/` as the documented reference location for architecture diagrams.


## v3 Password Policy Update

Added/Changed:
- Increased default TraceAPL password minimum length to 15 characters.
- Added password complexity enforcement requiring at least 3 of 4 character types: lowercase, uppercase, number, and special character.
- Prevented passwords from containing the user's TraceAPL/JHU/APL username.
- Documented that passwords do not expire by policy.
- Applied password validation to self-registration, user password changes, admin password resets, and the built-in admin password configured through `TRACEAPL_ADMIN_PASSWORD`.
- Updated registration, change-password, and admin user-management screens with password-policy guidance.

## v3 public workflows admin login - work auth sync fix

- Fixed the admin Work Authorization sync page error caused by missing sync helper functions.
- Added persistence for Work Authorization sync run history.
- Added Denodo CHAR HAND OFF sync implementation using field-parameter REST filtering and embedded Denodo table parsing.
