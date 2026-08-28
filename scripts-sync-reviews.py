#!/usr/bin/env python3
"""Aggregate reviews/<book-id>/*.json into reviews/all.json for the site board."""
import json
from pathlib import Path
root = Path(__file__).parent / 'reviews'
out = []
for f in sorted(root.glob('*/*.json')):
    try:
        r = json.loads(f.read_text())
        r['_file'] = str(f.relative_to(root.parent))
        out.append(r)
    except Exception as e:
        print('skip', f, e)
(root / 'all.json').write_text(json.dumps(out, indent=1) + '\n')
print(f'aggregated {len(out)} reviews -> reviews/all.json')
