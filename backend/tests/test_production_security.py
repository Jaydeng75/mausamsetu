import importlib.util
from pathlib import Path
import pytest

SCRIPT=Path(__file__).parents[2]/"deploy"/"production-preflight.py"
spec=importlib.util.spec_from_file_location("production_preflight",SCRIPT)
preflight=importlib.util.module_from_spec(spec);spec.loader.exec_module(preflight)


def secure_env(tmp_path):
    netrc=tmp_path/"earthdata.netrc";netrc.write_text("machine example.invalid\nlogin x\npassword y\n");netrc.chmod(0o600)
    env={
      "POSTGRES_PASSWORD":"x"*40,
      "MAUSAM_HOSTNAME":"forecast.weather.gov.in",
      "MAUSAM_EXTERNAL_URL":"https://forecast.weather.gov.in",
      "CORS_ORIGINS":"https://forecast.weather.gov.in",
      "OIDC_ISSUER":"https://id.weather.gov.in/realms/forecast",
      "OIDC_AUDIENCE":"mausamsetu",
      "OIDC_JWKS_URL":"https://id.weather.gov.in/realms/forecast/certs",
      "OIDC_ALGORITHM":"RS256",
      "OIDC_ROLES_CLAIM":"realm_access.roles",
      "OIDC_MAX_TOKEN_AGE_SECONDS":"3600",
      "OIDC_CLIENT_ID":"mausamsetu-web",
      "OIDC_CLIENT_SECRET":"s"*32,
      "OIDC_COOKIE_SECRET":"c"*32,
      "OIDC_ALLOWED_EMAIL_DOMAINS":"weather.gov.in",
      "EARTHDATA_NETRC_PATH":str(netrc),
    }
    return env


def test_production_preflight_accepts_structurally_secure_values(tmp_path):
    assert preflight.validate(secure_env(tmp_path),require_files=False)


@pytest.mark.parametrize("key,value",[
 ("CORS_ORIGINS","*"),
 ("MAUSAM_EXTERNAL_URL","http://forecast.weather.gov.in"),
 ("MAUSAM_HOSTNAME","localhost"),
 ("OIDC_ALLOWED_EMAIL_DOMAINS","*"),
 ("OIDC_ISSUER","http://id.weather.gov.in"),
 ("POSTGRES_PASSWORD","short"),
])
def test_production_preflight_rejects_insecure_values(tmp_path,key,value):
    env=secure_env(tmp_path);env[key]=value
    with pytest.raises(ValueError):preflight.validate(env,require_files=False)


def test_production_preflight_rejects_group_readable_secret_file(tmp_path):
    env=secure_env(tmp_path)
    env_file=tmp_path/"prod.env";env_file.write_text("x=y\n");env_file.chmod(0o640)
    env["__ENV_FILE__"]=str(env_file)
    with pytest.raises(ValueError,match="owner-only"):preflight.validate(env,require_files=True)


def test_production_compose_pins_current_security_edge_versions():
    text=(Path(__file__).parents[2]/"docker-compose.production.yml").read_text()
    assert "oauth2-proxy/oauth2-proxy:v7.15.4" in text
    assert "caddy:2.11.4-alpine" in text
    assert "MAUSAM_ALLOW_ANONYMOUS_READ: 'false'" in text
    assert "OIDC_CLIENT_SECRET" in text and "OIDC_COOKIE_SECRET" in text


def secure_runtime_env(monkeypatch):
    values={
      "MAUSAM_ENV":"production",
      "MAUSAM_ALLOW_ANONYMOUS_READ":"false",
      "MAUSAM_EXTERNAL_URL":"https://forecast.weather.gov.in",
      "OIDC_ISSUER":"https://id.weather.gov.in/realms/forecast",
      "OIDC_JWKS_URL":"https://id.weather.gov.in/realms/forecast/certs",
      "OIDC_AUDIENCE":"mausamsetu",
      "OIDC_ALGORITHM":"RS256",
      "OIDC_ROLES_CLAIM":"realm_access.roles",
      "OIDC_MAX_TOKEN_AGE_SECONDS":"3600",
      "CORS_ORIGINS":"https://forecast.weather.gov.in",
      "DATABASE_URL":"postgresql+psycopg://mausam:strong-secret@postgres/mausam",
    }
    for key,value in values.items():monkeypatch.setenv(key,value)


def test_backend_production_startup_accepts_structurally_secure_runtime(monkeypatch):
    import mausam.api as api
    secure_runtime_env(monkeypatch)
    api.check_environment()


@pytest.mark.parametrize("key,value",[
    ("MAUSAM_ALLOW_ANONYMOUS_READ","true"),
    ("MAUSAM_EXTERNAL_URL","http://forecast.weather.gov.in"),
    ("CORS_ORIGINS","*"),
    ("OIDC_ALGORITHM","HS256"),
    ("OIDC_ROLES_CLAIM","realm_access.roles[0]"),
    ("DATABASE_URL","sqlite:///metadata.db"),
])
def test_backend_production_startup_rejects_insecure_runtime(monkeypatch,key,value):
    import mausam.api as api
    secure_runtime_env(monkeypatch);monkeypatch.setenv(key,value)
    with pytest.raises(RuntimeError):api.check_environment()


def test_production_edge_routes_only_through_authenticated_tls_proxy():
    root=Path(__file__).parents[2]
    compose=(root/"docker-compose.production.yml").read_text()
    caddy=(root/"deploy/caddy/Caddyfile").read_text()
    assert "reverse_proxy oauth2-proxy:4180" in caddy
    assert "Strict-Transport-Security" in caddy
    assert "X-Frame-Options \"DENY\"" in caddy
    assert "OAUTH2_PROXY_COOKIE_SECURE: 'true'" in compose
    assert "OAUTH2_PROXY_PASS_ACCESS_TOKEN: 'true'" in compose
    assert "ports: ['80:80','443:443']" in compose
    assert "oauth2-proxy:4180:4180" not in compose


@pytest.mark.parametrize("key",["OIDC_ALGORITHM","OIDC_ROLES_CLAIM","OIDC_MAX_TOKEN_AGE_SECONDS"])
def test_preflight_requires_explicit_token_policy(tmp_path,key):
    env=secure_env(tmp_path);env.pop(key)
    with pytest.raises(ValueError,match="Missing required production settings"):
        preflight.validate(env,require_files=False)
