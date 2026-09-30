import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';

test('real grid, source comparison and provenance export',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');
 await expect(page.getByText('BASELINE METHOD',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'GFS',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'AIFS',exact:true}).click();
 await expect(page.getByText('Selected source',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Temperature',exact:true}).click();
 const pending=page.waitForEvent('download');
 await page.getByRole('button',{name:'Export real forecast point'}).click();
 const download=await pending;const path=await download.path();
 const data=JSON.parse(await readFile(path!,'utf8'));
 expect(data.data_kind).toBe('forecast');expect(data.source).toBe('AIFS');
 expect(data.variable).toBe('temperature');expect(data.calibrated).toBe(false);
 expect(Number.isFinite(data.value)).toBe(true);
 await page.screenshot({path:'test-results/real-workbench.png',fullPage:true});
 expect(errors).toEqual([]);
});

test('historical evaluation stays distinct from live forecasts',async({page})=>{
 await page.goto('/');await page.getByRole('tab',{name:'Historical benchmark'}).click();
 await page.getByRole('button',{name:'View evaluation scores'}).click();
 await expect(page.getByRole('heading',{name:'WeatherBench evaluation outside India'})).toBeVisible();
 await expect(page.getByRole('table')).toBeVisible();
 await expect(page.getByText(/not a full WeatherBench leaderboard/)).toBeVisible();
});

test('SIH evidence page and mobile layout',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.goto('/sih');
 await expect(page.getByRole('heading',{name:/Every claim inspectable/})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Remaining production acceptance gates'})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Executed release checks'})).toBeVisible();
 const dimensions=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth}));
 expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport+1);
 await page.screenshot({path:'test-results/sih-mobile.png',fullPage:true});
});

test('a corrupt checksum is an explicit error, never a synthetic fallback',async({page})=>{
 await page.route(/\/(?:data\/products|api\/public-products)\/latest\.json/,route=>route.fulfill({json:{path:'public-20260925-00-test.json',sha256:'0'.repeat(64)}}));
 await page.route(/\/(?:data\/products|api\/public-products)\/public-20260925-00-test\.json/,route=>route.fulfill({json:{not:'a forecast'}}));
 await page.goto('/');
 await expect(page.getByRole('heading',{name:'Dataset unavailable'})).toBeVisible();
 await expect(page.getByText('Product checksum failed.',{exact:true})).toBeVisible();
});

test('synthetic demo is explicitly labeled',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'Synthetic demo',exact:true}).click();
 await expect(page.getByRole('button',{name:/DEMO DATA/})).toBeVisible();
 await page.getByRole('tab',{name:'Verification',exact:true}).click();
 await expect(page.getByText(/synthetic/i).first()).toBeVisible();
});

test('runtime selects the explicitly configured archive',async({request})=>{
 const response=await request.get('/api/runtime');expect(response.ok()).toBe(true);
 const config=await response.json();
 const connected=process.env.MAUSAM_E2E_CONNECTED==='true';
 expect(config.mode).toBe(connected?'connected_archive':'packaged_snapshot');
 const pointer=await request.get(config.india_products_base+'latest.json');
 expect(pointer.ok()).toBe(true);
 const manifest=await pointer.json();expect(manifest.sha256).toMatch(/^[a-f0-9]{64}$/);
 const globalPointer=await request.get(config.global_products_base+'global-latest.json');
 expect(globalPointer.ok()).toBe(true);
 const globalManifest=await globalPointer.json();expect(globalManifest.sha256).toMatch(/^[a-f0-9]{64}$/);
});


test('SIH page exposes India sources and bounded rainfall evidence',async({page})=>{
 await page.goto('/sih');
 await expect(page.getByRole('heading',{name:'India data-source readiness'})).toBeVisible();
 await expect(page.getByText('IMD 0.25° rainfall',{exact:true})).toBeVisible();
 await expect(page.getByText('historical grid staged',{exact:true})).toBeVisible();
 await expect(page.getByText('NCUM',{exact:true})).toBeVisible();
 await expect(page.getByText('access required',{exact:true}).last()).toBeVisible();
 await expect(page.getByRole('heading',{name:'Real-data rainfall blend & replay'})).toBeVisible();
 await expect(page.getByText(/IFS-HRES \+ GraphCast 24-hour rainfall/)).toBeVisible();
 await expect(page.getByText(/only one case above 115\.6 mm\/24h/i)).toBeVisible();
 await expect(page.getByRole('link',{name:'Export rainfall evaluation'})).toHaveAttribute('href','/data/rainfall-benchmark.json');
});


test('live global mode serves current GFS GEFS IFS and AIFS forecasts',async({page})=>{
 await page.goto('/');
 await page.getByRole('tab',{name:'Global live'}).click();
 await expect(page.getByText('GLOBAL DOMAIN',{exact:true})).toBeVisible();
 await expect(page.getByText('2° display sampling',{exact:false})).toBeVisible();
 await expect(page.getByRole('button',{name:'GFS',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'GEFS ensemble mean',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'IFS',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'AIFS',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Temperature',exact:true}).click();
 await page.getByRole('button',{name:'AIFS',exact:true}).click();
 const pending=page.waitForEvent('download');
 await page.getByRole('button',{name:'Export real forecast point'}).click();
 const download=await pending, path=await download.path();
 const data=JSON.parse(await readFile(path!,'utf8'));
 expect(data.data_kind).toBe('forecast');
 expect(data.coverage).toBe('global');
 expect(data.source).toBe('AIFS');
 expect(Number.isFinite(data.value)).toBe(true);
});


test('research shadow sidecar respects the trained initialization domain',async({page,request})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'+24h',exact:true}).click();
 await expect(page.getByText(/MULTI-VARIABLE RESEARCH SHADOW · NOT ACTIVE/)).toBeVisible();
 const runtime=await (await request.get('/api/runtime')).json();
 const pointer=await (await request.get(runtime.india_products_base+'latest.json')).json();
 const product=await (await request.get(runtime.india_products_base+pointer.path)).json();
 const hour=new Date(product.initialization).getUTCHours();
 if(hour===0&&process.env.MAUSAM_E2E_CONNECTED==='true'){
  await expect(page.locator('.shadow-point-weights')).toBeVisible();
  await expect(page.getByText(/public equal baseline remains active/i)).toBeVisible();
 }else{
  await expect(page.getByText(new RegExp('withheld for this '+String(hour).padStart(2,'0')+' UTC run','i'))).toBeVisible();
 }
});


test('SIH multi-shadow matrix exposes lead outage and extreme gates',async({page})=>{
 await page.route('**/api/multi-shadow',route=>route.fulfill({json:{
  schema_version:1,generated_at:'2026-09-27T00:00:00Z',prospective_start:'2026-09-27T00:51:19Z',production_active:false,
  summary:{candidate_models:9,production_accepted_models:0,missing_source_patterns_tested_per_candidate:10,production_note:'research only'},
  variables:{
   rain:{'24':{state:'shadow_candidate',variable:'rain',lead:24,event_blocks:6,bootstrap_event_blocks:6,prospective_event_blocks:0,train_event_blocks:3,selection_event_blocks:1,test_event_blocks:2,acceptance_passed:false,numerical_gate_passed:false,
    scores:[{model:'Static point mixture',crps:4.3},{model:'Adaptive point mixture',crps:4.2}],adaptive_minus_static_95ci:[-.1,.01],
    missing_source_gate_passed:false,missing_source_matrix:Array.from({length:10},(_,i)=>({missing:['x'],bootstrap_pass:i<8,adaptive_minus_equal_95ci:[-.1,0]})),
    extreme_event_gate_passed:false,extreme_event_evidence:{'64.5':{threshold_mm:64.5,event_blocks_with_observed_event:2,minimum_event_blocks:4,support_pass:false,skill_pass:true,acceptance_pass:false}}}},
   temperature:{'48':{state:'shadow_candidate',variable:'temperature',lead:48,event_blocks:6,bootstrap_event_blocks:6,prospective_event_blocks:0,test_event_blocks:2,acceptance_passed:false,scores:[],missing_source_gate_passed:false,missing_source_matrix:[]}},
   wind:{'72':{state:'shadow_candidate',variable:'wind',lead:72,event_blocks:6,bootstrap_event_blocks:6,prospective_event_blocks:0,test_event_blocks:2,acceptance_passed:false,scores:[],missing_source_gate_passed:false,missing_source_matrix:[]}}
  }
 }}));
 await page.goto('/sih');
 await expect(page.getByRole('heading',{name:'Multi-variable shadow acceptance matrix'})).toBeVisible();
 await expect(page.getByText('9/9',{exact:true})).toBeVisible();
 await expect(page.getByRole('columnheader',{name:'Outage gate'})).toBeVisible();
 await expect(page.getByRole('columnheader',{name:'Extreme gate'})).toBeVisible();
 await expect(page.getByText('Rainfall · +24h',{exact:true})).toBeVisible();
});

test('SIH IMD panel preserves exact gauge-grid window semantics',async({page})=>{
 await page.route('**/api/imd-gauge',route=>route.fulfill({json:{
  schema_version:1,generated_at:'2026-09-27T00:00:00Z',state:'operational_reference_pipeline',reference_id:'imd-gauge-grid-025-realtime',
  policy:'IMD gauge-grid comparisons use exact 03:00-03:00 UTC accumulation windows; no 00:00-00:00 substitution is permitted.',
  rows:[{initialization:'2026-09-26T00:00:00+00:00',nominal_lead_hours:24,forecast_window_start:'2026-09-26T03:00:00+00:00',forecast_window_end:'2026-09-27T03:00:00+00:00',collocated_cells:316,limitation:'Gauge-gridded analysis; not raw station truth.',
   scores:['GFS','GEFS','IFS','AIFS','Equal point mixture'].map((model,i)=>({model,crps:0,rmse:10-i,mae:4-i/10,bias:0,thresholds:{}}))}]
 }}));
 await page.goto('/sih');
 const heading=page.getByRole('heading',{name:'IMD gauge-grid exact-window verification'});
 await expect(heading).toBeVisible();
 const card=heading.locator('..').locator('..');
 await expect(card.getByText(/03:00→03:00 UTC/)).toBeVisible();
 await expect(card.getByText(/not raw station truth/i)).toBeVisible();
 await expect(card.getByText('316',{exact:true})).toBeVisible();
});
