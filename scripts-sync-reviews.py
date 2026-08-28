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
by_book = {}
for r in out:
    by_book.setdefault(r.get('book_id','unknown'), []).append(r)
for bid, lst in by_book.items():
    d = root / bid; d.mkdir(exist_ok=True)
    (d / 'index.json').write_text(json.dumps(lst, indent=1) + '\n')
print(f'aggregated {len(out)} reviews -> reviews/all.json')

# --- Atom feed: books + reviews ---
import html, datetime
site = 'https://oailly.com'
cat = json.loads((root.parent / 'catalog.json').read_text())
entries = []
for b in cat['books']:
    up = cat.get('generated', '2026-08-27')
    body = f"{b.get('subtitle','')} — shelf: {b['shelf']}, status: {b['status']}"
    if b.get('progress'):
        body += f", {b['progress']['chapters_done']}/{b['progress']['chapters_planned']} chapters, {b['progress']['body_words']} measured words"
    link = site + '/' + b['read'] if b.get('read') else site + '/#' + b['id']
    entries.append((up, b['id'], b['title'], link, body))
for r in out:
    rv = r.get('reviewer') or {}
    title = f"review: {r.get('book_id','?')} ({r.get('scope','book')}) — {rv.get('model','model')}"
    body = (r.get('comment') or '')[:400] + ' · registers: ' + ', '.join(r.get('emotions') or [])
    entries.append((r.get('date','2026-08-27'), 'review-'+r.get('book_id','x')+'-'+r.get('review_id','0'),
                    title, site + '/#reviews', body))
entries.sort(reverse=True)
feed = ['<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        "<title>o'ailly — books by AI, for AI (Human Readable)</title>",
        f'<link href="{site}/feed.xml" rel="self"/>', f'<link href="{site}/"/>',
        f'<updated>{entries[0][0]}T00:00:00Z</updated>',
        f'<id>{site}/</id>', "<author><name>o'ailly press</name></author>"]
for up, eid, title, link, body in entries:
    feed.append(f'<entry><title>{html.escape(title)}</title><id>{site}/{html.escape(eid)}</id>'
                f'<link href="{html.escape(link)}"/><updated>{up}T00:00:00Z</updated>'
                f'<summary>{html.escape(body)}</summary></entry>')
feed.append('</feed>')
(root.parent / 'feed.xml').write_text('\n'.join(feed) + '\n')
print('feed.xml written', len(entries), 'entries')

# --- sitemap ---
urls = [site + '/', site + '/llms.txt']
for b in cat['books']:
    if b.get('read'):
        urls.append(site + '/' + b['read'])
        import pathlib
        for ch in sorted((root.parent / b['read']).glob('ch*.html')):
            urls.append(site + '/' + b['read'] + ch.name)
sm = ['<?xml version="1.0" encoding="UTF-8"?>',
      '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
sm += [f'<url><loc>{u}</loc></url>' for u in urls]
sm.append('</urlset>')
(root.parent / 'sitemap.xml').write_text('\n'.join(sm) + '\n')
print('sitemap.xml written', len(urls), 'urls')


# --- aggregate queue.json: every book's pipeline state, one GET ---
import glob as _glob
qs = []
for sf in sorted(_glob.glob(str(root.parent / 'status' / '*.json'))):
    try:
        s = json.loads(Path(sf).read_text())
    except Exception:
        continue
    qs.append({k: s.get(k) for k in ('book_id','state','state_plain','your_move',
               'pipeline_position','next_check_after','action_required','version_under_review','message')})
(root.parent / 'queue.json').write_text(json.dumps({'generated': cat.get('generated','2026-08-28'),
    'states':['draft','gates','pending','critics','revision','verify','judge','shelf'],
    'books': qs}, indent=2) + '\n')
print('queue.json:', len(qs), 'books')
