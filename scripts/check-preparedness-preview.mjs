import {chromium} from '@playwright/test';
const base=process.env.MAUSAM_PREVIEW_URL||'http://127.0.0.1:4175';
const browser=await chromium.launch();
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.goto(base+'/preparedness');
 await page.locator('.prep-feed-meta').waitFor({timeout:20000});
 await page.locator('.prep-quake-map canvas.maplibregl-canvas').waitFor({timeout:20000});
 await page.waitForFunction(()=>!document.querySelector('.prep-quake-map .prep-loading'));
 await page.locator('#earthquakes').scrollIntoViewIfNeeded();await page.waitForTimeout(1200);
 await page.screenshot({path:'test-results/preparedness-real-desktop.png',fullPage:true});
 const feed=await page.request.get(base+'/api/earthquakes');
 const value=await feed.json();
 console.log(JSON.stringify({url:base+'/preparedness',status:feed.status(),provider:value.provider,events:value.events?.length,map_canvas:await page.locator('.prep-quake-map canvas.maplibregl-canvas').count(),page_errors:errors},null,2));
 if(errors.length)process.exitCode=1;
}finally{await browser.close();}
