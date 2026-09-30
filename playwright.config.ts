import {defineConfig,devices} from '@playwright/test';
const port=Number(process.env.MAUSAM_E2E_PORT||4173);
if(!Number.isInteger(port)||port<1024||port>65535)throw Error('Invalid browser-test port');
const baseURL='http://127.0.0.1:'+port;
export default defineConfig({
 testDir:'./tests/e2e',
 timeout:60000,
 expect:{timeout:20000},
 fullyParallel:false,
 workers:1,
 retries:process.env.CI?1:0,
 reporter:[['list'],['json',{outputFile:'test-results/e2e-results.json'}]],
 use:{baseURL,trace:'retain-on-failure',screenshot:'only-on-failure'},
 projects:[{name:'chromium',use:{...devices['Desktop Chrome']}}],
 webServer:{command:'npm run start -- --hostname 127.0.0.1 --port '+port,env:{MAUSAM_PUBLIC_BACKEND_URL:process.env.MAUSAM_E2E_CONNECTED==='true'?'http://127.0.0.1:8000':''},url:baseURL,reuseExistingServer:process.env.MAUSAM_E2E_RUNNING==='true',timeout:120000},
});
