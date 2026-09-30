# Institution-facing security deployment

MausamSetu's local research deployment is intentionally separate from the institution-facing production profile. The production profile is implemented as a fail-closed Docker Compose overlay and must not be started until the institution supplies real identity, DNS and secret values.

## Implemented controls

- HTTPS ingress through Caddy with HSTS, frame denial, no-sniff, restrictive referrer and permissions policies.
- Browser authentication through oauth2-proxy using an institutional OIDC provider.
- Backend JWT verification against a configured HTTPS JWKS endpoint.
- Issuer, audience, signature algorithm, expiry and issued-at/max-age checks.
- Nested configurable role claim with application roles: `viewer`, `reviewer`, `approver`, `admin`.
- Review actions require reviewer role; production activation/rollback requires approver or admin.
- Anonymous reads are disabled in production.
- Explicit HTTPS CORS origins only; wildcard origins are rejected.
- Non-development PostgreSQL credentials are mandatory.
- Read-only application filesystems, tmpfs for temporary writes, dropped Linux capabilities and `no-new-privileges`.
- External reverse proxy is the only public ingress; API and web development ports remain loopback-bound in the base compose file.
- Earthdata credentials remain in an owner-only file outside Git.
- Request body size bounds, request IDs and security headers.
- Production environment preflight rejects placeholder secrets, HTTP origins, localhost hostnames, wildcard email domains/origins and group/world-readable secret files.

## Required institutional values

Create an owner-only environment file outside the repository from `deploy/production.env.example` and supply:

- approved public DNS hostname;
- HTTPS external URL;
- institutional OIDC issuer and JWKS URL;
- dedicated OIDC client ID/client secret;
- random cookie secret;
- explicit allowed institutional email domains;
- explicit CORS origin(s);
- strong PostgreSQL password;
- owner-only NASA/Earthdata credential path.

Run:

```sh
chmod 600 /secure/mausamsetu-production.env
python deploy/production-preflight.py --env-file /secure/mausamsetu-production.env
```

Only after preflight succeeds should the institution render/start:

```sh
EARTHDATA_NETRC_PATH=/secure/earthdata.netrc \
docker compose --env-file /secure/mausamsetu-production.env \
  -f docker-compose.yml \
  -f docker-compose.runtime.yml \
  -f docker-compose.production.yml config
```

and then `up -d` under the institution's approved hosting process.

## What cannot be completed by the project repository

The repository cannot create or approve the institution's DNS name, TLS/DNS authority, OIDC tenant/client, reviewer/approver identities, email-domain policy, firewall policy or operational ownership. Those values are deliberately mandatory external configuration; replacing them with demo credentials would weaken the production boundary.
