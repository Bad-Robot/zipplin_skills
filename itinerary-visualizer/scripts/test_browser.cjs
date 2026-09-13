// Usage: PLAYWRIGHT_MODULE=/path/to/playwright node test_browser.cjs /path/to/index.html
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {pathToFileURL}=require('url');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.context().setOffline(true);
 await page.goto(pathToFileURL(process.argv[2]).href);
 for(const width of [390,768,1440]){
  await page.setViewportSize({width,height:1000});await page.waitForTimeout(450);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'page overflow');
  for(const gallery of await page.locator('.gallery-grid').all()){
   assert.equal(await gallery.evaluate(el=>getComputedStyle(el).display),'flex');
   const tops=await gallery.locator('.gallery-item').evaluateAll(es=>es.map(e=>e.getBoundingClientRect().top));
   assert(Math.max(...tops)-Math.min(...tops)<2,'gallery wraps');
  }
 }
 const count=await page.locator('.day-pill').count();
 for(let i=0;i<count;i++){
  await page.locator('.day-pill').nth(i).click();await page.waitForTimeout(900);
  assert(await page.locator('.day-pill').nth(i).evaluate(e=>e.classList.contains('active')));
  assert.equal(await page.locator('#mapStage .true-basemap').count(),1);
  assert(await page.evaluate(()=>{const v=document.querySelector('#mapViewport').getBoundingClientRect();return [...document.querySelectorAll('#mapStage .route-group')].every(e=>{const r=e.getBoundingClientRect();return r.left>=v.left-2&&r.right<=v.right+2&&r.top>=v.top-2&&r.bottom<=v.bottom+2})}),'daily route clipped');
 }
 await page.locator('#baseStyle').click();assert.equal(await page.locator('#baseStyle').getAttribute('aria-pressed'),'true');
 assert.equal(await page.locator('#mapStage .true-basemap').evaluate(e=>getComputedStyle(e).filter),'none');
 const pin=page.locator('#mapStage .map-point').first();await pin.focus();await pin.press('Enter');
 assert.equal(await page.locator('.stop-selected').count(),1);
 const images=page.locator('.gallery-item img');
 for(const img of await images.all())assert(await img.evaluate(async e=>{await e.decode();return e.naturalWidth>0&&!e.src.startsWith('data:image/svg')}));
 await page.locator('.gallery-item').last().click();assert(await page.locator('.lightbox').isVisible());
 assert.equal(await page.locator('.lightbox p a').count(),1);await page.keyboard.press('Escape');assert(!await page.locator('.lightbox').isVisible());
 await page.screenshot({path:process.argv[2].replace(/\.html$/,'.qa.png'),fullPage:false});
 await page.locator('#baseStyle').click();
 await page.evaluate(()=>scrollTo(0,0));await page.waitForTimeout(700);
 assert.equal(await page.locator('.hero h1').evaluate(e=>getComputedStyle(e).fontSize),'26px');
 assert(await page.locator('.hero').evaluate(e=>getComputedStyle(e).backgroundImage.includes('gradient')));
 await page.screenshot({path:process.argv[2].replace(/\.html$/,'.top.qa.png')});
 await page.emulateMedia({media:'print'});assert.equal(await page.locator('.print-map').count(),count);
 assert.deepEqual(errors,[]);await browser.close();console.log('Responsive / offline photos / daily basemaps / style toggle / keyboard POI / lightbox: PASS');
})().catch(e=>{console.error(e);process.exit(1)});
