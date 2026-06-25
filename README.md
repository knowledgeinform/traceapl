# Sample QR Tracker - Browser MVP

This is a browser-based prototype for tracking samples using pre-printed QR codes.

## Features

- Assign a pre-existing QR code to a new sample
- Scan with a browser camera using `html5-qrcode`
- Use a handheld scanner as keyboard input
- Lookup sample records by QR code
- Record Project and Task fields
- Add required characterization items when a sample is created
- Add more characterization items later from the sample page
- Mark characterization items complete with who completed them, data location, and optional notes
- Record sample handoffs
- View handoff history and scan events
- Export samples, handoffs, scan events, and characterizations to CSV

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

On macOS, use:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Phone camera testing

Open the app from the phone browser while the phone is on the same network as the computer running the app.

In `app.py`, change:

```python
app.run(host="127.0.0.1", port=5000, debug=True)
```

to:

```python
app.run(host="0.0.0.0", port=5000, debug=True)
```

Then open:

```text
http://YOUR_COMPUTER_IP:5000
```

Important: mobile browsers often require HTTPS for camera access unless the page is served from localhost. For real phone scanning, host the app behind HTTPS or use a trusted internal deployment.

## Data

The SQLite database is created as:

```text
sample_tracker_web.db
```

The QR value is unique, so the same physical QR code cannot be assigned to two sample records.

Existing databases from the first browser prototype are migrated automatically when the app starts. The app adds `project`, `task`, `characterizations`, and `data_location` storage if they are missing.
