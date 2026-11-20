#!/usr/bin/env python3
"""Download a freely licensed photo from Wikimedia Commons for a search query
(or an exact File: title) and record its license + author for the credit line.

  python3 tools/fetch_photo.py "server rack data center" -o /tmp/reel/photo1.jpg
  python3 tools/fetch_photo.py --title "File:Datacenter Server Racks (22370909788).jpg" -o x.jpg

Writes <out>.jpg and <out>.json  {title, artist, license, license_url, page, credit}.
Only CC0 / Public domain / CC BY / CC BY-SA files are accepted (no NC/ND, no fair use).
Prints the JSON. Use the "credit" string as the scene's photo credit.
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request
API = 'https://commons.wikimedia.org/w/api.php'
UA = {'User-Agent': 'K4CodingAcademyBot/1.0 (https://github.com/k4coding1985/social-media-assets)'}
OK_LIC = re.compile(r'^(cc0|public domain|pd|cc by(-sa)? ?[0-9.]*( [a-z]+)?)$', re.I)

def api(**p):
    p.update(format='json', formatversion=1)
    for i in range(4):
        try:
            r = urllib.request.urlopen(urllib.request.Request(API + '?' + urllib.parse.urlencode(p), headers=UA), timeout=30)
            return json.load(r)
        except Exception as e:
            if i == 3: raise
            time.sleep(2 + 3 * i)

def strip(s): return re.sub(r'\s+', ' ', re.sub('<[^>]+>', '', s or '')).strip()

def info(pages, min_w):
    out = []
    for p in pages:
        if 'imageinfo' not in p: continue
        ii = p['imageinfo'][0]; m = ii.get('extmetadata', {})
        lic = strip(m.get('LicenseShortName', {}).get('value', ''))
        if ii.get('mime') not in ('image/jpeg', 'image/png'): continue
        if not OK_LIC.match(lic) or re.search(r'\b(nc|nd)\b', lic, re.I): continue
        if ii.get('width', 0) < min_w: continue
        artist = strip(m.get('Artist', {}).get('value', '')) or 'Unknown author'
        artist = artist[:60]
        out.append(dict(title=p['title'].replace('File:', ''), artist=artist, license=lic,
                        license_url=m.get('LicenseUrl', {}).get('value', ''), page=ii['descriptionurl'],
                        url=ii.get('thumburl') or ii['url'], width=ii['width'], height=ii['height'],
                        credit=f"Photo: {artist} / Wikimedia Commons · {lic}", index=p.get('index', 0)))
    return sorted(out, key=lambda x: x['index'])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('query', nargs='?'); ap.add_argument('--title'); ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--pick', type=int, default=0, help='take the Nth acceptable result')
    ap.add_argument('--min-width', type=int, default=1200); ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    common = dict(prop='imageinfo', iiprop='url|size|mime|extmetadata', iiurlwidth=1600)
    if a.title:
        t = a.title if a.title.startswith('File:') else 'File:' + a.title
        r = api(action='query', titles=t, **common)
    else:
        r = api(action='query', generator='search', gsrsearch=f'{a.query} filetype:bitmap', gsrnamespace=6, gsrlimit=30, **common)
    res = info(list(r.get('query', {}).get('pages', {}).values()), a.min_width)
    if a.list:
        for i, x in enumerate(res): print(i, x['license'], x['width'], x['title'])
        return
    if not res: sys.exit('no freely licensed photo found for: ' + (a.title or a.query))
    x = res[min(a.pick, len(res) - 1)]
    data = urllib.request.urlopen(urllib.request.Request(x['url'], headers=UA), timeout=60).read()
    out = a.out if a.out.lower().endswith(('.jpg', '.png')) else a.out + '.jpg'
    open(out, 'wb').write(data)
    meta = {k: x[k] for k in ('title', 'artist', 'license', 'license_url', 'page', 'credit')}
    json.dump(meta, open(re.sub(r'\.(jpg|png)$', '.json', out), 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(meta, ensure_ascii=False))

if __name__ == '__main__': main()
