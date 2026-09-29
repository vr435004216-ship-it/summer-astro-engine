# Summer Astro Engine

Experimental astronomical rule engine, Python API and Arabic interface.
See README_AR.md for usage, scope, and limitations.

Render build: `pip install -r requirements-lock.txt && python deployment/fetch_ephemeris.py`

Start: `python -m uvicorn summer_astro.api:app --host 0.0.0.0 --port $PORT --workers 1`

Set `SUMMER_API_TOKEN` as a secret. Runtime data and personal results are excluded from this repository. The free Render trial uses temporary SQLite storage; it is not a persistent prospective forecast archive.

License: AGPL-3.0-or-later; Swiss Ephemeris terms included.
