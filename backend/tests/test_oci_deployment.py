from pathlib import Path

ROOT=Path(__file__).parents[2]

def test_oci_overlay_is_arm64_and_keeps_research_ports_private():
    text=(ROOT/"docker-compose.oci.yml").read_text()
    assert "platform: linux/arm64" in text
    assert "127.0.0.1:4173:3000" in text
    assert "mausamsetu-postgis:16-arm64" in text
    assert "/srv/mausamsetu/state" in text

def test_oci_postgis_uses_official_arm64_postgres_base():
    text=(ROOT/"deploy/oci/Dockerfile.postgis").read_text()
    assert text.startswith("FROM postgres:16-bookworm")
    assert "postgresql-16-postgis-3" in text

def test_oci_export_excludes_secrets_and_preserves_prospective_state():
    export=(ROOT/"deploy/oci/export-state.sh").read_text()
    readme=(ROOT/"deploy/oci/README.md").read_text()
    assert "earthdata" not in export.lower()
    assert "forecast-data.tgz" in export
    assert "contains_secrets" in export
    assert "prospective start" in readme.lower()
    assert "14173" in readme and "18000" in readme

def test_oci_research_env_keeps_credentials_external():
    env=(ROOT/"deploy/oci/research.env.example").read_text()
    prepare=(ROOT/"deploy/oci/prepare-host.sh").read_text()
    assert "REPLACE_WITH_RANDOM" in env
    assert "EARTHDATA_NETRC_PATH=/srv/mausamsetu/secrets/earthdata.netrc" in env
    assert "host_uid=$(id -u)" in prepare
    assert '"$root/secrets" "$root/migration"' in prepare
