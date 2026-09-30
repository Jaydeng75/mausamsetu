import json
from datetime import datetime, timezone
import numpy as np
import pytest
import xarray as xr
from mausam.adaptive import fit_gate, predict_weights, crps_terms, mixture_crps, context_features, save_candidate
from mausam.golden import generate
from mausam.pipeline import publish_aligned
from mausam.registry import activate, approved_model


def test_gate_learns_context_not_fixed_weights():
    rng = np.random.default_rng(26081)
    x = rng.uniform(-1, 1, (600, 1))
    y = rng.normal(20, 2, 600)
    prediction = np.column_stack([y + np.where(x[:, 0] > 0, .1, 5), y + np.where(x[:, 0] < 0, .1, 5)])
    samples = prediction[:, :, None] + np.linspace(-1, 1, 11)
    model = fit_gate(x[:400], samples[:400], y[:400])
    weights = predict_weights(model, x[400:], [True, True])
    first, pair = crps_terms(samples[400:], y[400:])
    assert mixture_crps(weights, first, pair).mean() < mixture_crps(np.full_like(weights, .5), first, pair).mean()
    assert predict_weights(model, [[1], [-1]], [True, True])[0, 0] > .8
    assert predict_weights(model, [[1], [-1]], [True, True])[1, 1] > .8
    assert np.allclose(predict_weights(model, [[1]], [False, True]), [[0, 1]])
    with pytest.raises(ValueError):
        predict_weights(model, [[1]], [False, False])


def test_learned_publication_is_pinned_and_gridwise(tmp_path):
    generate(tmp_path)
    path = tmp_path / "golden" / "manifest.json"
    config = json.loads(path.read_text())
    samples = [np.load(path.parent / source["file"]) for source in config["sources"]]
    features, names = context_features(samples, config["lat"], config["lon"], 72, config["sources"][0]["metadata"]["initialization_time_utc"])
    x = features.reshape(-1, features.shape[-1])
    s = np.stack(samples, axis=-1).transpose(1, 2, 3, 0).reshape(-1, 4, 21)
    model = fit_gate(x, s, s[:, 0].mean(-1))
    model.update(source_ids=[m["metadata"]["source_id"] for m in config["sources"]], feature_names=names, variable="rain", units="mm")
    save_candidate(tmp_path / "models" / "gate-v1", model, {"data_kind": "synthetic", "acceptance_passed": False})
    with pytest.raises(ValueError):
        activate(tmp_path, "gate-v1", "tester", "Reviewed synthetic mechanics", "production")
    activate(tmp_path, "gate-v1", "tester", "Reviewed synthetic mechanics", "demonstration")
    config["run_id"] = "learned-test"
    config["model"] = {"version": "active", "method": "learned", "approved": True}
    path.write_text(json.dumps(config))
    result = publish_aligned(path, tmp_path)
    assert result["approval"]["scope"] == "demonstration"
    assert result["model"]["version"] == "gate-v1"
    with xr.open_dataset(tmp_path / "published" / "learned-test" / "forecast.nc") as ds:
        assert ds.source_weights.dims == ("lat", "lon", "source")
        assert np.allclose(ds.source_weights.sum("source"), 1)
    artifact = tmp_path / "models" / "gate-v1" / "model.json"
    artifact.write_text(artifact.read_text() + " ")
    with pytest.raises(ValueError, match="checksum"):
        approved_model(tmp_path, "gate-v1", "synthetic")


def test_context_features_are_explicit_and_grid_checked():
    samples=[np.ones((3,2,2)),np.ones((3,2,2))*2]
    context={'tpw':np.full((2,2),42.0),'sst':np.full((2,2),29.0)}
    features,names=context_features(samples,[10,11],[80,81],24,'2026-09-26T00:00:00+00:00',context)
    assert features.shape[-1]==11
    assert names[-2:]==['context_sst','context_tpw']
    assert np.all(features[...,names.index('context_tpw')]==42.0)
    with pytest.raises(ValueError,match='feature name'):
        context_features(samples,[10,11],[80,81],24,'2026-09-26T00:00:00+00:00',{'Bad Name':np.ones((2,2))})
    with pytest.raises(ValueError,match='grid'):
        context_features(samples,[10,11],[80,81],24,'2026-09-26T00:00:00+00:00',{'tpw':np.ones((1,2))})
