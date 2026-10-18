"""Isolated browser fixture: responsive bell and form preservation, no real services."""
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright,expect


def test_bell_dialog_mobile_and_embedded_without_losing_edits(width,height,embedded):
    payload={'ok':True,'csrf':'fixture','items':[],'unread':0,'historical':{'TOTAL_REELS':2}}
    script=Path('app/static/notification-center.js').read_text(encoding='utf-8')
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':width,'height':height})
        page.route('**/*',lambda route:route.abort())
        page.route('https://zar.test/api/notifications',lambda route:route.fulfill(content_type='application/json',body=json.dumps(payload)))
        html='<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}body.zarEmbedded .top{display:none}</style></head><body class="'+('zarEmbedded' if embedded else '')+'"><header class="top"><div class="topActions"></div></header></body></html>'
        page.route(re.compile(r'^https://zar\.test/($|\?)'),lambda route:route.fulfill(content_type='text/html',body=html))
        page.goto('https://zar.test/'+('?zar_workspace=sites' if embedded else ''))
        page.clock.install();page.add_script_tag(content=script)
        bell=page.locator('#zarNotificationBell');expect(bell).to_be_visible();bell.click()
        panel=page.locator('#zarNotificationCenter');expect(panel).to_be_visible()
        panel.get_by_text('Crear / editar Google Workspace',exact=True).click()
        title=panel.locator('[name=title]');title.fill('Keep my unsaved title')
        page.clock.fast_forward(21000)
        expect(panel.locator('[name=title]')).to_have_value('Keep my unsaved title')
        assert panel.evaluate('(e)=>e.getBoundingClientRect().width')<=width
        assert bell.evaluate('(e)=>e.getBoundingClientRect().height')>=44
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        panel.locator('[data-close]').click();expect(panel).not_to_be_visible()
        browser.close()

if __name__ == '__main__':
    for viewport in [(1440,900,False),(390,844,False),(390,844,True)]:
        test_bell_dialog_mobile_and_embedded_without_losing_edits(*viewport)
        print('PASS', viewport)
