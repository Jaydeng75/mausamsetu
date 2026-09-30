from pathlib import Path
import yaml


def test_runtime_compose_serializes_global_refresh_and_keeps_rain_worker():
    root=Path(__file__).parents[2]
    config=yaml.safe_load((root/"docker-compose.runtime.yml").read_text())
    services=config["services"]
    assert {"ingest-worker","rain-worker"} <= set(services)
    assert "global-ingest-worker" not in services
    ingest=services["ingest-worker"]
    assert ingest["restart"]=="unless-stopped"
    assert "provider-cache:/cache" in ingest["volumes"]
    rain=services["rain-worker"]
    assert "mausam.rain_service" in " ".join(rain["command"])
    assert rain["secrets"][0]["source"]=="earthdata_netrc"
    assert "/var/run/docker.sock" not in str(config)
    assert services["api"]["volumes"]==["public-products:/public:ro"]


def test_container_service_enables_sequential_global_refresh():
    root=Path(__file__).parents[2]
    text=(root/"backend/mausam/container_service.py").read_text()
    assert "'enable_global_refresh':True" in text
