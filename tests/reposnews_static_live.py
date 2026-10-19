import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.reposnews_static_host import verify, artifact_digest, PREVIEW
from playwright.async_api import async_playwright

out = ROOT/'.local/reposnews-static-verification'
out.mkdir(exist_ok=True)
build = ROOT/'dist/reposnews'
report = {'http': verify(build), 'artifact_sha256': artifact_digest(build)}
paths = [urlsplit(el.text).path for el in ET.fromstring((build/'sitemap.xml').read_bytes()).iter() if el.tag.split('}')[-1] == 'loc']
articles = [p for p in paths if '/repositorios/' in p or p.startswith('/en/repositories/') and p != '/en/repositories/']

from html.parser import HTMLParser
class SEO(HTMLParser):
    def __init__(self): super().__init__(); self.tags=[]; self.links=[]; self.capture=False; self.data=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=='meta' or tag=='link' and a.get('rel') in {'canonical','alternate'}: self.tags.append((tag, sorted(a.items())))
        if tag=='a': self.links.append(a.get('href'))
        if tag=='title' or tag=='script' and a.get('type')=='application/ld+json': self.capture=True
    def handle_endtag(self, tag):
        if tag in {'title','script'}: self.capture=False
    def handle_data(self, value):
        if self.capture: self.data.append(value)

for path in paths:
    with urlopen('https://www.reposnews.com'+path, timeout=30) as response: live=response.read().decode()
    static=(build/path.strip('/')/'index.html').read_text(encoding='utf-8')
    a,b=SEO(),SEO();a.feed(live);b.feed(static)
    assert a.tags==b.tags and a.data==b.data, ('SEO mismatch',path)
    assert a.links==b.links, ('link mismatch',path)
    for href in b.links:
        if not href or not href.startswith('/') or href.startswith('//'):continue
        target=urlsplit(href).path
        assert target in paths or target=='/' or (build/target.lstrip('/')).is_file(), ('broken internal link',path,href)
report.update(seo_parity_pages=len(paths), link_parity_pages=len(paths), broken_internal_links=0, external_sources_and_reels='identical hrefs to current production; no social requests performed')

async def browser_checks():
    rows=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        for width,height in [(1440,900),(390,844)]:
            for path in ['/es/','/en/',next(p for p in articles if p.startswith('/es/')),next(p for p in articles if p.startswith('/en/'))]:
                pictures=[]; layouts=[]
                for label,origin in [('current','https://www.reposnews.com'),('static',PREVIEW)]:
                    context=await browser.new_context(viewport={'width':width,'height':height},device_scale_factor=1)
                    blocked=[]
                    if label=='static':
                        async def route(request):
                            if urlsplit(request.request.url).hostname!='solana031.github.io':
                                blocked.append(request.request.url);await request.abort()
                            else:await request.continue_()
                        await context.route('**/*',route)
                    page=await context.new_page()
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    await page.goto(origin+path,wait_until='networkidle')
                    await page.evaluate("async()=>{await document.fonts.ready;for(const i of document.images){i.loading='eager';}await Promise.all([...document.images].map(i=>i.decode().catch(()=>{})));}")
                    assert await page.locator('img').evaluate_all('(imgs)=>imgs.every(i=>i.complete&&i.naturalWidth>0)'), (label,path,'image broken')
                    layouts.append(await page.evaluate("()=>({width:document.documentElement.scrollWidth,height:document.body.scrollHeight,text:document.querySelector('h1').textContent,colors:[getComputedStyle(document.body).backgroundColor,getComputedStyle(document.body).color],font:getComputedStyle(document.body).fontFamily,images:[...document.images].map(i=>({src:i.getAttribute('src'),w:i.width,h:i.height}))})"))
                    image=out/(label+'-'+str(width)+'-'+path.strip('/').replace('/','-')+'.png')
                    await page.screenshot(path=str(image),full_page=True);pictures.append(image)
                    assert not errors,(label,path,errors)
                    assert not blocked,(path,blocked)
                    if label=='static' and path=='/es/':
                        await page.locator('form.search input').fill('zzzz-no-matching-article')
                        await page.locator('form.search button').click()
                        assert await page.locator('.grid>.card:visible').count()==0
                        await page.locator('form.search input').fill('')
                        await page.locator('form.search button').click()
                        assert await page.locator('.grid>.card:visible').count()==json.loads((build/'build-manifest.json').read_text())['published_articles']
                        await page.locator('.card h2 a').first.click();await page.wait_for_load_state('networkidle')
                        assert '/es/repositorios/' in page.url
                        await page.locator('[data-lang=en]').click();await page.wait_for_load_state('networkidle')
                        assert '/en/repositories/' in page.url
                        await page.locator('.related .card h2 a').first.click();await page.wait_for_load_state('networkidle')
                        assert '/en/repositories/' in page.url
                    await context.close()
                assert layouts[0]==layouts[1],('layout mismatch',width,path)
                with Image.open(pictures[0]) as first,Image.open(pictures[1]) as second:
                    assert first.size==second.size
                    diff=ImageChops.difference(first.convert('RGB'),second.convert('RGB'))
                    equal=diff.getbbox() is None
                assert equal,('screenshot mismatch',width,path)
                rows.append({'width':width,'path':path,'pixel_identical':equal,'all_images_loaded':True,'railway_blocked':True})
        await browser.close()
    return rows

report['visual']=asyncio.run(browser_checks())
report['search']='static client filtering verified at desktop/mobile'
report['navigation']='home/article, related article, ES/EN verified at desktop/mobile'
(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
