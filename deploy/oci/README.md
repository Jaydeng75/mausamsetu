# OCI Ampere migration

This profile targets an Oracle Cloud `VM.Standard.A1.Flex` ARM64 host.
The initial research deployment stays private on VM loopback; only SSH needs
to be reachable from the Internet. Use the production Caddy/OIDC overlay later,
after a real domain and identity provider are available.

## 1. Export from the Mac

Keep the existing Mac stack running. From the repository:

```sh
deploy/oci/export-state.sh
```

This creates source, PostgreSQL dump, forecast/scientific state, public products,
backups, checksums and a manifest. It deliberately excludes credentials.
Set `INCLUDE_PROVIDER_CACHE=1` only if you want the additional ~1.6 GB cache.

## 2. Transfer

Copy the generated bundle to `/srv/mausamsetu/migration/` on OCI.
Copy the Earthdata netrc separately to
`/srv/mausamsetu/secrets/earthdata.netrc` and set mode `0600`.
Never put the credential in Git or in the migration archive.

Extract `mausamsetu-source.tgz` into `/opt/mausamsetu`, then run:

```sh
cd /opt/mausamsetu
sudo deploy/oci/prepare-host.sh
cp deploy/oci/research.env.example /srv/mausamsetu/secrets/research.env
chmod 600 /srv/mausamsetu/secrets/research.env
```

Replace the PostgreSQL placeholder in that private environment file.

## 3. Restore

```sh
cd /opt/mausamsetu
deploy/oci/import-state.sh \
  /srv/mausamsetu/migration/BUNDLE_DIRECTORY \
  /srv/mausamsetu/secrets/research.env
```

## 4. Inspect privately

From the Mac:

```sh
ssh -L 14173:127.0.0.1:4173 -L 18000:127.0.0.1:8000 ubuntu@OCI_PUBLIC_IP
```

Then inspect the cloud UI at `http://127.0.0.1:14173` while the Mac UI
remains at `http://127.0.0.1:4173`. The tunneled cloud API is
`http://127.0.0.1:18000`; compare its `/public/status`,
`/public/shadow-rain`, `/public/multi-shadow` and `/public/imd-gauge`
against the local API on port 8000.

## 5. Cut over collectors

Run Mac and OCI in parallel until OCI completes at least one successful
forecast-maintenance cycle and all scientific counters/prospective-start values
match expectations. Then stop only the Mac collectors:

```sh
docker compose -p mausamsetu-audit stop ingest-worker rain-worker imd-gauge-worker
```

Do not reset `/data/shadow-rain/config.json`; the original prospective start
must survive migration. Keep the Mac state intact as rollback until OCI has
completed a full forecast → observation → verification cycle.
