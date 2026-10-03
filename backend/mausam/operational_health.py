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
    context = status.get('mosdac')
    if context:
        if context.get('state') not in ('available',):
            alert('mosdac_context_unavailable', 'MOSDAC satellite context is unavailable or delayed. Core forecasts are independent.')
        checked = context.get('checked_at')
        try:
            if not checked or (now - datetime.fromisoformat(checked)).total_seconds() > 90 * 60:
                alert('mosdac_status_stale', 'MOSDAC worker status is over 90 minutes old or missing.')
        except (ValueError, TypeError):
            alert('mosdac_status_stale', 'MOSDAC worker status timestamp is invalid.')
        if context.get('session_cleanup') == 'failed':
            alert('mosdac_logout_failed', 'MOSDAC session cleanup failed after collection.')
    status["status"] = "degraded" if alerts else "healthy"
    return status


def attach_mosdac(status, public):
    """Project only safe health fields from the independently scheduled worker."""
    import json
    path = public / 'mosdac-status.json'
    if not path.exists():
        return status
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError('Invalid context status')
        report = json.loads(path.read_text())
        status['mosdac'] = {k: report.get(k) for k in ('state', 'checked_at', 'session_cleanup')}
    except (OSError, ValueError, TypeError, AttributeError):
        status['mosdac'] = {'state': 'invalid'}
    # Recompute context alerts from the current report, not the hourly snapshot.
    status['alerts'] = [a for a in status.get('alerts', []) if not a.get('code', '').startswith('mosdac_')]
    return status
