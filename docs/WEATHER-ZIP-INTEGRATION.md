# Weather Project ZIP integration — 26 September 2026

Reference archive: `/Users/jayden75/Downloads/Weather_project_zip.zip`.
The archive was inspected without running its application or installation scripts. Only 32 relevant source/document files were extracted into the private review directory. Bundled dependencies, environment files and build output were excluded. The original ZIP is unchanged.

## Useful portions integrated

| ZIP feature | MausamSetu adaptation |
| --- | --- |
| SafetyGuide and SafetyHub | `/preparedness`: six source-linked hazard topics, clear separation from forecasts and official warnings. |
| EmergencyNumbersCard | India ERSS 112, linked to Ministry of Home Affairs documentation; no unverified global number table. |
| Print/download guide | Printable selected guidance plus a self-contained, script-free offline HTML handbook containing all six guides and checklist state. |
| Local-storage UX | A versioned, validated preparedness checklist; graceful session-only operation when browser storage is unavailable. |
| EarthquakeFeedCard | A genuine USGS M2.5+ seven-day feed with region/magnitude/time filters, provider/retrieval timestamps and explicit stale/error states. |
| EarthquakeMapCard | Existing MapLibre stack, USGS longitude/latitude/depth, list/map selection and source links. No mock geocoding or unsafe HTML popups. |
| ForecastCard | Seven-day cards in the real-data point panel, derived only from published source/baseline values. Instantaneous temperature is not relabeled daily Tmax/Tmin; rainfall keeps its 24-hour window. |

## Deliberately not imported

- `useMockApi`, generated earthquake records, city-name-based weather, arbitrary probabilities and dated fabricated cyclone/flood/tsunami alerts.
- Nearby hospital/shelter markers constructed from invented offsets.
- The browser-side Gemini survival assistant, API keys or `.env.local`.
- Humidity-to-rain-probability formulas, fixed confidence scores, and controls claiming a neural/transformer model without model inference.
- A second Leaflet map stack, external map-script CDNs, dependency directories, old React/Vite versions or background stock photography.

The implementation is newly authored against the existing Next.js/MapLibre application. The ZIP informed feature selection and interaction patterns; it is not treated as authoritative safety or meteorological evidence. No new runtime dependencies were added.

## Provenance and operation

Archive SHA-256: `cf7c93b8aaec9b7ead4d46e4bbde9665edf63930af0f1f01a2cd5973fd59b4d9`.
Review manifests, before-change backups and test logs are stored outside the checkout under `work/weather-zip-integration-20260926/`.

`/api/earthquakes` retrieves only the fixed USGS endpoint. It validates the GeoJSON contract, coordinate order, timestamps, finite values, duplicate event revisions and allowlisted source URLs. Requests have a ten-second deadline, a three-megabyte response limit, a five-minute cache and a brief retry cooldown. Set `MAUSAM_ENABLE_SEISMIC_CONTEXT=false` in the frontend server environment to disable this supplementary feed. It is never an input to weather training, blending or verification.

A provider failure is explicit. A previously loaded catalogue may remain visible with its original timestamp and failure message; no substitute events or all-clear assessment are generated. The offline handbook contains static guidance and checklist state only, not a cached live warning feed.

## Validation performed

- Next.js route type generation, TypeScript checks and production build passed.
- Preparedness contract/export tests and existing public-data integrity checks passed.
- 14 Playwright browser tests passed, including all six existing tests plus eight preparedness/outlook tests; earthquake canvas rendering is checked, not only the loading placeholder.
- All 52 existing Python backend tests passed; existing scientific fixtures checked 280 forecast combinations and 2,880 verification records.
- A direct preview API request returned HTTP 200 with 333 validated USGS earthquake events; one nonconforming or non-earthquake record was excluded. This is a check-time count, not a permanently fixed data value.
- Desktop inspection of the real feed showed one rendered map canvas and no browser page errors. Mobile layouts, offline guidance, storage failure and hostile text rendering were exercised.

The first run also exposed pre-existing unknown-JSON TypeScript errors in the unfinished point-weather/explorer/cache work. Narrow response-type/validation fixes were applied with backups; these draft features were not replaced by the ZIP app. Two existing backend dependency compatibility/deprecation warnings remain unchanged.

## Deployment notes

The frontend is updated at `http://127.0.0.1:4173`, with the new workspace at `/preparedness`. Backend, database and ingestion/verification workers were not redeployed.

A clean Docker dependency reinstall stalled during `npm ci` and was cancelled. Because no runtime dependencies changed, the tested standalone JavaScript/static build was packaged over the existing Linux runtime after checking traced package versions. Linux native modules were preserved, not copied from macOS. All 14 browser tests were then rerun against the resulting Docker container, and its live USGS route and map were checked successfully before replacing the web service.

Deployment image: `mausamsetu-web:weather-zip-20260926`. The previous frontend image remains tagged `mausamsetu-web:before-weather-zip-20260926` for rollback. The regular source-build Dockerfile remains available for clean rebuilds when package downloads are available. Runtime-version checks, the asset packaging script and build/test logs are in the private integration work directory.

No scientific training, calibration, scorecards, model approvals or institutional data-access status was changed by this integration. The preparedness companion does not make the forecasting service institutionally production-approved.
