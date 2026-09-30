#!/usr/bin/env python3
"""Fail-closed validation for institution-facing MausamSetu deployment."""
import argparse
import os
import stat
from pathlib import Path
from urllib.parse import urlparse

REQUIRED = [
    "POSTGRES_PASSWORD","MAUSAM_HOSTNAME","MAUSAM_EXTERNAL_URL","CORS_ORIGINS",
    "OIDC_ISSUER","OIDC_AUDIENCE","OIDC_JWKS_URL","OIDC_ALGORITHM",
    "OIDC_ROLES_CLAIM","OIDC_MAX_TOKEN_AGE_SECONDS","OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET","OIDC_COOKIE_SECRET","OIDC_ALLOWED_EMAIL_DOMAINS",
    "EARTHDATA_NETRC_PATH",
]
PLACEHOLDER_TOKENS = ("REPLACE", "example.gov.in", "changeme", "password")


def load_env(path):
    result={}
    for raw in Path(path).read_text().splitlines():
        line=raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("Invalid env-file line")
        key,value=line.split("=",1)
        key=key.strip();value=value.strip()
        if not key or key in result:
            raise ValueError("Invalid or duplicate environment key")
        result[key]=value
    return result


def _https(value, name):
    parsed=urlparse(value)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{name} must be an HTTPS URL without embedded credentials")
    return parsed


def validate(env, require_files=True):
    missing=[key for key in REQUIRED if not env.get(key)]
    if missing:
        raise ValueError("Missing required production settings: "+", ".join(missing))
    for key in REQUIRED:
        value=env[key]
        if any(token.lower() in value.lower() for token in PLACEHOLDER_TOKENS):
            raise ValueError(f"{key} still contains a placeholder")
    if len(env["POSTGRES_PASSWORD"])<32:
        raise ValueError("POSTGRES_PASSWORD must be at least 32 characters")
    if len(env["OIDC_CLIENT_SECRET"])<24:
        raise ValueError("OIDC_CLIENT_SECRET must be at least 24 characters")
    if len(env["OIDC_COOKIE_SECRET"])<32:
        raise ValueError("OIDC_COOKIE_SECRET must be at least 32 characters")

    hostname=env["MAUSAM_HOSTNAME"].strip().lower()
    if hostname in {"localhost","127.0.0.1"} or "/" in hostname or ":" in hostname or "." not in hostname:
        raise ValueError("MAUSAM_HOSTNAME must be a public institutional DNS name")
    external=_https(env["MAUSAM_EXTERNAL_URL"],"MAUSAM_EXTERNAL_URL")
    if external.hostname.lower()!=hostname or external.path not in ("","/"):
        raise ValueError("MAUSAM_EXTERNAL_URL must exactly match MAUSAM_HOSTNAME")
    _https(env["OIDC_ISSUER"],"OIDC_ISSUER")
    _https(env["OIDC_JWKS_URL"],"OIDC_JWKS_URL")

    origins=[item.strip() for item in env["CORS_ORIGINS"].split(",") if item.strip()]
    if not origins or "*" in origins:
        raise ValueError("CORS_ORIGINS must be explicit")
    if env["MAUSAM_EXTERNAL_URL"].rstrip("/") not in [origin.rstrip("/") for origin in origins]:
        raise ValueError("CORS_ORIGINS must include the external origin")
    for origin in origins:
        parsed=_https(origin,"CORS origin")
        if parsed.path not in ("","/"):
            raise ValueError("CORS origins must not include paths")

    domains=[item.strip().lower() for item in env["OIDC_ALLOWED_EMAIL_DOMAINS"].split(",") if item.strip()]
    if not domains or "*" in domains or any("." not in item or "/" in item or "@" in item for item in domains):
        raise ValueError("OIDC_ALLOWED_EMAIL_DOMAINS must list explicit institutional domains")

    algorithm=env.get("OIDC_ALGORITHM","RS256")
    if algorithm not in {"RS256","PS256"}:
        raise ValueError("OIDC_ALGORITHM must be RS256 or PS256")
    try:
        max_age=int(env.get("OIDC_MAX_TOKEN_AGE_SECONDS","3600"))
    except ValueError as exc:
        raise ValueError("OIDC_MAX_TOKEN_AGE_SECONDS must be an integer") from exc
    if not 300<=max_age<=86400:
        raise ValueError("OIDC_MAX_TOKEN_AGE_SECONDS outside permitted range")

    if require_files:
        env_path=Path(env["__ENV_FILE__"])
        if stat.S_IMODE(env_path.stat().st_mode)&0o077:
            raise ValueError("Production env file must be owner-only (0600)")
        netrc=Path(env["EARTHDATA_NETRC_PATH"])
        if not netrc.is_file():
            raise ValueError("EARTHDATA_NETRC_PATH does not exist")
        if stat.S_IMODE(netrc.stat().st_mode)&0o077:
            raise ValueError("Earthdata netrc must be owner-only (0600)")
    return True


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--env-file",required=True)
    args=parser.parse_args()
    env=load_env(args.env_file)
    env["__ENV_FILE__"]=str(Path(args.env_file).resolve())
    validate(env,True)
    print("Production preflight passed: secrets, OIDC, HTTPS origin, CORS and credential-file permissions are structurally valid.")


if __name__=="__main__":
    main()
