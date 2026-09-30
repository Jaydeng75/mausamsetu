import fs from 'node:fs';
fs.mkdirSync('public/maplibre',{recursive:true});
for(const name of ['maplibre-gl-worker.mjs','maplibre-gl-shared.mjs'])fs.copyFileSync('node_modules/maplibre-gl/dist/'+name,'public/maplibre/'+name);
