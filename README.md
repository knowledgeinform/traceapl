# TraceAPL - Work Program + Denodo REST Employee Autocomplete

This build keeps the current TraceAPL workflow and adds a Denodo REST-backed option for the `Assign to` autocomplete field used for characterization tasks.

## What changed

- Keeps the single `Work Program` sample field.
- Keeps mobile camera scanning, barcode/QR tracking, QR reprint, admin-protected backups/removal, characterization tasks, and mock employee autocomplete.
- Adds Denodo REST support for employee autocomplete.
- Adds `TRACEAPL_EMPLOYEE_LOOKUP_MODE=mock` or `TRACEAPL_EMPLOYEE_LOOKUP_MODE=rest`.
- Adds a safe server-side Denodo lookup that returns only a small subset of fields to the browser:
  - display name
  - email
  - person/employee ID
  - user ID
  - group/org label when available
- Filters to active people by default using `person_status_code = A`.
- Requires email by default so assignments can support email notification.
- Uses environment variables for all Denodo settings and credentials.

## Important security note

Do not commit real Denodo usernames, passwords, tokens, or `.env` files to GitLab. This package includes `.env.example` only as a template.

For development, you can use your personal Denodo account via local environment variables. For shared/team use, switch to an approved service/app account with read-only access to the employee directory view.

## Required Denodo REST URL

The expected default endpoint is:

```text
https://denodo.jhuapl.edu:9443/denodo-restfulws/addit/views/dim_hr_person
```

The code expects a Denodo JSON response with a top-level `elements` list.

## Mac startup example: mock mode

```bash
cd /path/to/traceapl
source .venv/bin/activate
pip install -r requirements.txt

export TRACEAPL_HOST=0.0.0.0
export TRACEAPL_PORT=5000
export TRACEAPL_SSL=adhoc
export TRACEAPL_EMPLOYEE_LOOKUP_MODE=mock
python3 app.py
```

## Mac startup example: Denodo REST mode

```bash
cd /path/to/traceapl
source .venv/bin/activate
pip install -r requirements.txt

export TRACEAPL_HOST=0.0.0.0
export TRACEAPL_PORT=5000
export TRACEAPL_SSL=adhoc
export TRACEAPL_EMPLOYEE_LOOKUP_MODE=rest
export DENODO_EMPLOYEE_REST_URL="https://denodo.jhuapl.edu:9443/denodo-restfulws/addit/views/dim_hr_person"
export DENODO_USERNAME="your-username"
export DENODO_PASSWORD="your-password"
python3 app.py
```

## Windows startup example: Denodo REST mode

```cmd
cd C:\path\to\traceapl
.venv\Scripts\activate
pip install -r requirements.txt

set TRACEAPL_HOST=0.0.0.0
set TRACEAPL_PORT=5000
set TRACEAPL_SSL=adhoc
set TRACEAPL_EMPLOYEE_LOOKUP_MODE=rest
set DENODO_EMPLOYEE_REST_URL=https://denodo.jhuapl.edu:9443/denodo-restfulws/addit/views/dim_hr_person
set DENODO_USERNAME=your-username
set DENODO_PASSWORD=your-password
python app.py
```

## Copying safely

When copying this update into an existing TraceAPL folder, preserve:

- `sample_tracker_web.db`
- `backups/`
- `.venv/`
- `static/vendor/html5-qrcode.min.js` if you installed it locally
- any local `.env` file containing credentials

## Field mapping

Defaults are set for the observed `dim_hr_person` response:

```text
DENODO_EMPLOYEE_NAME_FIELD=preferred_full_name
DENODO_EMPLOYEE_FALLBACK_NAME_FIELD=full_name
DENODO_EMPLOYEE_EMAIL_FIELD=email_id
DENODO_EMPLOYEE_ID_FIELD=person_num
DENODO_EMPLOYEE_USER_FIELD=user_id
DENODO_EMPLOYEE_STATUS_FIELD=person_status_code
DENODO_EMPLOYEE_ACTIVE_VALUE=A
```

## Fallback

If Denodo is down or credentials are not set, switch back to mock mode:

```bash
export TRACEAPL_EMPLOYEE_LOOKUP_MODE=mock
```
