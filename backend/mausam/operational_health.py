"""Shared health checks for the worker and public status projection."""
from datetime import datetime, timezone


def apply_health(status, now=None):
    now = now or datetime.now(timezone.utc)
    alerts = status.setdefault("alerts", [])
    def alert(code, message):
        if not any(a.get("code") == code for a in alerts):
            alerts.append({"severity": "warning", "code": code, "message": message})
    for domain, row in (("india", status), ("global", status.get("global_forecast", {}))):
        sources = row.get("sources", {})
        if sources:
            missing = sorted({"GFS", "GEFS", "IFS", "AIFS"} - {s for s, state in sources.items() if state == "loaded"})
            if missing:
                alert(domain + "_sources_degraded", domain.title() + " forecast sources unavailable: " + ", ".join(missing))
                if domain == "global": row["state"] = "degraded"
        if row.get("initialization"):
            age = (now - datetime.fromisoformat(row["initialization"])).total_seconds() / 3600
            row["forecast_age_hours"] = round(age, 2)
            if age > 30:
                alert("stale_" + domain + "_forecast", domain.title() + " forecast is older than 30 hours.")
    for key in ("refresh", "global_refresh"):
        if status.get(key, {}).get("state") in ("failed", "withheld"):
            alert(key + "_failed", "Scheduled " + key.replace("_", " ") + " did not complete.")
    evidence = status.get("validation", {})
    start = evidence.get("prospective_start")
    if start and (now - datetime.fromisoformat(start)).total_seconds() > 72 * 3600 and evidence.get("rain_prospective_event_blocks") == 0:
        alert("prospective_evidence_stalled", "No matched prospective rainfall blocks after 72 hours; inspect archive and reference ingestion.")
    if evidence.get("imd_latest_window") and (now - datetime.fromisoformat(evidence["imd_latest_window"])).total_seconds() > 72 * 3600:
        alert("imd_evidence_stale", "Newest IMD verification window is older than 72 hours.")
    status["status"] = "degraded" if alerts else "healthy"
    return status
