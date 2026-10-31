import pathlib, urllib.request, urllib.error, re, time
ROOT=pathlib.Path(__file__).parent
source=(ROOT/'kaynak.m3u').read_text(encoding='utf-8-sig').splitlines()
entries=[]
for i,line in enumerate(source):
    if line.startswith('#EXTINF:') and i+1<len(source):
        url=source[i+1].strip()
        if url.startswith(('https://','http://')):
            entries.append((line,url))
def check(url):
    # Only treat an actual HLS playlist as verified, not merely HTTP 200.
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/vnd.apple.mpegurl,application/x-mpegURL,*/*'})
        with urllib.request.urlopen(req,timeout=9) as r:
            if r.status!=200:return False
            body=r.read(65536).decode('utf-8-sig',errors='replace')
            return body.lstrip().startswith('#EXTM3U')
    except Exception:return False
# Preserve channel order, and keep streams if checks fail: failure may be geoblocking or temporary.
# Report results instead of silently deleting channels.
results=[]
for meta,url in entries:
    name=meta.rsplit(',',1)[-1]
    ok=check(url)
    results.append((name,ok))
    print(f'{"OK" if ok else "CHECK"}: {name}',flush=True)
(ROOT/'kontrol-raporu.md').write_text('# Yayın kontrol raporu\n\nGitHub Actions kontrolü; CHECK kesin bozuk demek değildir (coğrafi kısıtlama olabilir).\n\n'+''.join(f'- {"OK" if ok else "CHECK"}: {name}\n' for name,ok in results),encoding='utf-8')
(ROOT/'turk-tv.m3u').write_text('#EXTM3U\n\n'+''.join(f'{meta}\n{url}\n\n' for meta,url in entries),encoding='utf-8')
