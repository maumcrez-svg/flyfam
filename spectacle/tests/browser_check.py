"""Real feed browser checks. No mutation of the producer or its files."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

OUT=Path(__file__).parents[1]/'evidence'
BASE='http://localhost:8796'
results=[]
with sync_playwright() as p:
    for engine in ['chromium','webkit']:
        browser=getattr(p,engine).launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        errors=[]
        page.on('pageerror',lambda error: errors.append(str(error)))
        response=page.request.get(BASE+'/api/feed').json()
        page.goto(BASE)
        expect(page.locator('#connection')).not_to_have_text('CONNECTING')
        page.wait_for_timeout(800)
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(OUT/f'{engine}-desktop.png'),full_page=True)
        page.get_by_role('tab',name='Field notes').click()
        assert page.locator('#activity-panel .activity-row').count()>0
        page.get_by_role('tab',name='Rejected scents').click()
        assert page.locator('#rejected-panel .rejected-row').count()>0
        page.get_by_role('tab',name='The aftermath').click()
        page.get_by_role('link',name='WHY FROZEN?').click()
        assert page.locator('#about-dialog').is_visible()
        page.get_by_role('button',name='Close',exact=True).click()
        page.locator('#sound').click()
        assert page.locator('#sound').get_attribute('aria-pressed')=='true'
        page.locator('#sound').click()
        # Actual historical episode replay. No invented trading events.
        for label in ['REWARD','PUNISHMENT']:
            episode=next(e for e in response['state']['episodes'] if e['credit']['label']==label)
            button=page.locator(f'[data-replay="{episode["episode_id"]}"]')
            button.click()
            expect(page.locator('#mode-label')).to_have_text('RECORDED REPLAY')
            expect(page.locator('.arena')).to_have_attribute('data-act','sniffing')
            if engine=='chromium' and label=='REWARD':page.screenshot(path=str(OUT/'replay-sniffing.png'),full_page=True)
            expect(page.locator('.arena')).to_have_attribute('data-act','picked',timeout=12000)
            if engine=='chromium':page.screenshot(path=str(OUT/f'replay-{label.lower()}-pick.png'),full_page=True)
            expect(page.locator('.arena')).to_have_attribute('data-act','position',timeout=12000)
            expect(page.locator('#act-title')).to_have_text(label,timeout=45000)
            assert 'MEMORY DISABLED' in page.locator('#impact').inner_text()
            assert page.locator('#position-number').inner_text()=='FLAT'
            page.screenshot(path=str(OUT/f'{engine}-{label.lower()}.png'),full_page=True)
            page.locator('#back-live').click()
            expect(page.locator('#mode-label')).not_to_have_text('RECORDED REPLAY')
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_timeout(500)
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(OUT/f'{engine}-mobile.png'),full_page=True)
        # Delayed snapshot keeps actual open position and pauses its clock.
        stale=page.request.get(BASE+'/api/feed').json()
        stale['state']['updated_epoch']=1
        stale['state']['health']['last_cutoff_ts']=1
        page.route('**/api/feed?*',lambda route:route.fulfill(json=stale))
        expect(page.locator('#connection')).to_have_text('FEED DELAYED',timeout=10000)
        assert page.locator('#notice').is_visible()
        assert page.locator('#position-number').inner_text()==('OPEN' if stale['state']['position'] else 'FLAT')
        page.unroute('**/api/feed?*')
        page.route('**/api/feed?*',lambda route:route.fulfill(status=503,json={'error':'Feed temporarily unavailable'}))
        expect(page.locator('#connection')).to_have_text('FEED OFFLINE',timeout=10000)
        assert 'last received' in page.locator('#notice').inner_text()
        assert not errors, errors
        results.append({'engine':engine,'desktop':[1440,1000],'mobile':[390,844],'errors':errors,'real_reward_replay':True,'real_punishment_replay':True,'stale_and_offline':True,'overflow':False})
        browser.close()
OUT.joinpath('browser-results.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results))
