# Geographic and software attribution

- Country outlines: Natural Earth, `ne_110m_admin_0_countries.geojson`, public domain. Retrieved from https://github.com/nvkelso/natural-earth-vector/tree/master/geojson on 26 September 2026.
- State boundaries: geoBoundaries gbOpen IND ADM1, source DataMeet India community / Election Commission of India. Licence: Creative Commons Attribution 2.5 India (CC BY 2.5 IN). https://www.geoboundaries.org/api/current/gbOpen/IND/ADM1/ ; snapshot https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/IND/ADM1/geoBoundaries-IND-ADM1_simplified.geojson . Licence text: https://creativecommons.org/licenses/by/2.5/in/ . Rendered as illustrative boundaries, without representing an authoritative territorial determination.
- MapLibre GL JS: BSD 3-Clause. https://github.com/maplibre/maplibre-gl-js . Its distributed worker and shared module are served locally with their licence headers retained.
- Apache ECharts: Apache 2.0. https://echarts.apache.org/
- Lucide icons: ISC. https://lucide.dev/license
- Generated forecast fields and verification records: deterministic synthetic examples authored for this application. They are not NEPS, NCUM, AIFS, GFS, IMD, NCMRWF, ECMWF, or NOAA forecasts and do not imply institutional endorsement.

## Preparedness companion and Weather Project reference

- The user-supplied `Weather_project_zip.zip` informed the preparedness navigation, emergency-contact card, earthquake list/map interaction and forecast-card selection. Its README credits Ankit Pal, Abhishek Kumar and Abhishek Prajapati, with additional acknowledgments. No standalone licence was identified in the reviewed application files; the integration is newly authored rather than a wholesale copy or relicensing of that application. The original archive and author notices remain untouched.
- Recent earthquake event data and coordinates: US Geological Survey, M2.5+ seven-day GeoJSON summary, https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson . Format and attribution: https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php . Provider generation and retrieval times are displayed. Data may be revised and do not constitute an earthquake prediction or tsunami warning.
- Preparedness summaries are newly worded from the official USGS and NOAA/National Weather Service pages linked beside each guide in `lib/preparedness/guidance.ts`. These summaries are not individualized emergency instructions or an official institutional bulletin.
- India emergency assistance: Ministry of Home Affairs ERSS 112, https://www.mha.gov.in/en/commoncontent/emergency-response-support-system-erss . Official warning resources remain external links to IMD and NDMA SACHET.
- No bundled environment variables, Gemini keys, simulated alerts, invented nearby facilities, additional map SDKs, or dependencies were imported from the ZIP. See `WEATHER-ZIP-INTEGRATION.md` for the exact scope.
