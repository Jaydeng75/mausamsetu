import {test,expect,type Page} from '@playwright/test';
import {readFile} from 'node:fs/promises';
const fixture=()=>{
 const now=Date.now();const event=(id:string,place:string,latitude:number,longitude:number,magnitude:number)=>({id,place,latitude,longitude,magnitude,time:now-60000,updated:now-30000,depthKm:12,reviewStatus:'reviewed',url:'https://earthquake.usgs.gov/earthquakes/eventpage/'+id});
 return {schema_version:1,provider:'USGS',generated_at:new Date(now-1000).toISOString(),fetched_at:new Date(now).toISOString(),source_url:'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson',is_warning:false,skipped_records:0,events:[event('test-india','India browser-test fixture',25,80,4.2),event('test-japan','Japan browser-test fixture',35,140,6.2)]};
};
async function mockFeed(page:Page){await page.route('**/api/earthquakes',route=>route.fulfill({json:fixture()}));}

test('preparedness guide and checklist survive reload',async({page})=>{
 await mockFeed(page);await page.goto('/preparedness');
 await expect(page.getByRole('heading',{name:'Safety handbook',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Thunderstorms & lightning',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Thunderstorms & lightning',exact:true})).toBeVisible();
 const water=page.getByRole('checkbox',{name:/Drinking water and food/});await water.check();
 await expect(page.getByText('1 / 8 packed',{exact:true})).toBeVisible();
 await page.reload();await expect(water).toBeChecked();
 await expect(page.locator('.prep-emergency').getByRole('link',{name:'112',exact:true})).toHaveAttribute('href','tel:112');
});

test('offline handbook is standalone and works without a provider',async({page,context})=>{
 await mockFeed(page);await page.goto('/preparedness');
 await page.getByRole('checkbox',{name:/Torch and spare batteries/}).check();
 const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Save offline handbook'}).click();
 const file=await downloadPromise,content=await readFile((await file.path())!,'utf8');
 expect(content).toContain('Content-Security-Policy');expect(content).not.toMatch(/<script|<iframe|<img/i);expect(content).toContain('[✓]');
 await context.setOffline(true);await page.getByRole('button',{name:'Extreme heat',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Extreme heat',exact:true})).toBeVisible();
 await expect(page.getByText(/You are offline/)).toBeVisible();
});

test('earthquake filters preserve real coordinates and distinguish magnitude from warnings',async({page})=>{
 await mockFeed(page);await page.goto('/preparedness');
 await expect(page.getByText('1 matching records',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:/India browser-test fixture/}).click();
 await expect(page.getByText(/25.000°, 80.000°/)).toBeVisible();
 await page.getByLabel('Earthquake region').selectOption('world');
 await expect(page.getByText('2 matching records',{exact:true})).toBeVisible();
 await expect(page.locator('.prep-quake-map canvas.maplibregl-canvas')).toBeVisible();
 await page.getByLabel('Minimum magnitude').selectOption('6');
 await expect(page.getByRole('button',{name:/Japan browser-test fixture/})).toBeVisible();
 await expect(page.getByRole('button',{name:/India browser-test fixture/})).toHaveCount(0);
 await expect(page.getByText(/not earthquake prediction, a tsunami warning/)).toBeVisible();
});

test('provider outage never becomes an all-clear or a fake event',async({page})=>{
 await page.route('**/api/earthquakes',route=>route.fulfill({status:503,json:{error:'Test outage'}}));
 await page.goto('/preparedness');
 await expect(page.locator('.prep-seismic').getByRole('alert')).toContainText('not an all-clear');
 await expect(page.locator('.prep-seismic').getByRole('alert')).toContainText('No events have been substituted.');
 await expect(page.getByRole('heading',{name:'Safety handbook',exact:true})).toBeVisible();
 await expect(page.getByText('0 matching records',{exact:true})).toHaveCount(0);
});

test('preparedness is usable on a narrow screen',async({page})=>{
 await mockFeed(page);await page.setViewportSize({width:390,height:844});await page.goto('/preparedness');
 await expect(page.getByText('1 matching records',{exact:true})).toBeVisible();
 const dimensions=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth}));
 expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport+1);
 await expect(page.locator('.prep-quake-map canvas.maplibregl-canvas')).toBeVisible();
 await page.screenshot({path:'test-results/preparedness-mobile.png',fullPage:true});
});

test('storage failures do not disable the handbook',async({page})=>{
 await page.addInitScript(()=>{Storage.prototype.setItem=function(){throw new Error('Storage disabled for test');};});
 await mockFeed(page);await page.goto('/preparedness');
 await page.getByRole('checkbox',{name:/Drinking water and food/}).check();
 await expect(page.getByText(/Browser storage could not be read or saved/)).toBeVisible();
 await expect(page.getByText('1 / 8 packed',{exact:true})).toBeVisible();
});

test('source strings are text and stale catalogues are identified',async({page})=>{
 const data=fixture();data.generated_at=new Date(Date.now()-3600000).toISOString();data.events[0].place='<img src=x onerror="alert(1)">';
 await page.route('**/api/earthquakes',route=>route.fulfill({json:data}));
 await page.goto('/preparedness');
 await expect(page.getByText(/provider catalogue is older than 15 minutes/)).toBeVisible();
 await expect(page.locator('.prep-events img')).toHaveCount(0);
 await expect(page.getByRole('button',{name:/<img src=x/})).toBeVisible();
});

test('daily outlook uses published values and changes the selected lead',async({page})=>{
 await page.goto('/');
 const outlook=page.getByRole('region',{name:'Seven-day model outlook'});
 await expect(outlook).toBeVisible();await outlook.getByRole('button',{name:'Rainfall at +24 hours',exact:true}).click();
 await expect(outlook.getByRole('button',{name:'Rainfall at +24 hours',exact:true})).toHaveAttribute('aria-pressed','true');
 const metric=Number(await outlook.getByRole('button',{name:'Rainfall at +24 hours',exact:true}).locator('strong').innerText());
 await page.getByLabel('Display units').selectOption('imperial');
 await expect(outlook.getByText(/Rainfall \(in\)/)).toBeVisible();
 const imperial=Number(await outlook.getByRole('button',{name:'Rainfall at +24 hours',exact:true}).locator('strong').innerText());
 expect(Math.abs(imperial-metric/25.4)).toBeLessThan(0.1);
 await page.getByRole('link',{name:'Preparedness',exact:true}).click();
 await expect(page.getByRole('heading',{name:/Context, without guesswork/})).toBeVisible();
});
