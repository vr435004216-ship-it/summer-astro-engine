"""Fetch official Swiss Ephemeris files and verify the release checksums."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1] / 'summer_astro' / 'ephe'
manifest = json.loads((root / 'manifest.json').read_text())
for name, spec in manifest.items():
    target = root / name
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == spec['sha256']:
        continue
    with urlopen(spec['source'], timeout=90) as response:
        data = response.read()
    if len(data) != spec['bytes'] or hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise RuntimeError('Ephemeris integrity check failed: ' + name)
    target.write_bytes(data)
print('Swiss Ephemeris files verified')
