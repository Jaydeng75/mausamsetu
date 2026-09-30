import numpy as np

from mausam.adaptive import predict_weights
from mausam.multi_shadow import (
    SOURCES, _scalar_features, _wind_features, missing_patterns,
    train_scalar_model, train_wind_model
)


def scalar_blocks(events=6, lead=24, shift=0.0):
    latitude=np.array([12.,11.,10.,9.]);longitude=np.array([78.,79.,80.,81.])
    blocks=[]
    for event in range(events):
        yy,xx=np.meshgrid(latitude,longitude,indexing='ij')
        truth=20+event+2*(yy-9)+(xx-78)+shift
        north=yy>=11
        sources=np.stack([
            truth+np.where(north,.2,5),
            truth+1.5,
            truth+np.where(north,4,.2),
            truth+.8,
        ])
        features,names=_scalar_features(sources,latitude,longitude,lead,f"2026-01-{event+1:02}T00:00:00+00:00")
        mask=np.ones_like(truth,dtype=bool)
        blocks.append({
            "event_id":f"event-{event}","initialization":f"2026-01-{event+1:02}T00:00:00+00:00",
            "lead":lead,"features":features[mask],"feature_names":names,
            "samples":sources[:,mask].T[:,:,None],"observations":truth[mask],
            "case_weight":np.ones(mask.sum()),
        })
    return blocks


def wind_blocks(events=6, lead=24):
    latitude=np.array([12.,11.,10.,9.]);longitude=np.array([78.,79.,80.,81.])
    blocks=[]
    for event in range(events):
        yy,xx=np.meshgrid(latitude,longitude,indexing='ij')
        obs_u=2+.2*event+.1*(xx-78);obs_v=1+.1*(yy-9)
        north=yy>=11
        u=np.stack([obs_u+np.where(north,.1,2),obs_u+.8,obs_u+np.where(north,1.7,.1),obs_u+.4])
        v=np.stack([obs_v+np.where(north,.1,1.5),obs_v+.6,obs_v+np.where(north,1.2,.1),obs_v+.3])
        features,names=_wind_features(u,v,latitude,longitude,lead,f"2026-01-{event+1:02}T00:00:00+00:00")
        mask=np.ones_like(obs_u,dtype=bool)
        vectors=np.stack([u[:,mask].T,v[:,mask].T],axis=-1)
        observations=np.stack([obs_u[mask],obs_v[mask]],axis=-1)
        blocks.append({
            "event_id":f"event-{event}","initialization":f"2026-01-{event+1:02}T00:00:00+00:00",
            "lead":lead,"features":features[mask],"feature_names":names,
            "vectors":vectors,"observations":observations,"case_weight":np.ones(mask.sum()),
        })
    return blocks


def test_missing_source_matrix_covers_all_single_and_pair_outages():
    patterns=missing_patterns()
    assert len(patterns)==10
    assert {sum(~available) for _,available in patterns}=={1,2}


def test_scalar_shadow_scores_all_outage_patterns_without_promotion():
    blocks=scalar_blocks()
    cross=scalar_blocks(shift=.25)
    model,report=train_scalar_model(blocks,"rain",24,"2026-02-01T00:00:00Z",
                                    cross_blocks=cross,require_independent=True)
    assert model is not None
    assert len(report["missing_source_matrix"])==10
    assert all("acceptance_pass" in row for row in report["missing_source_matrix"])
    assert report["missing_source_gate_passed"] in {True,False}
    assert report["extreme_event_gate_passed"] is False
    assert report["extreme_event_evidence"]["64.5"]["support_pass"] is False
    assert report["acceptance_passed"] is False
    assert report["prospective_event_blocks"]==0
    test_features=blocks[-1]["features"][:4]
    available=np.array([False,True,True,True])
    weights=predict_weights(model,test_features,available)
    assert np.allclose(weights[:,0],0)
    assert np.allclose(weights.sum(axis=1),1)


def test_temperature_shadow_remains_research_only_with_era5t_reference():
    model,report=train_scalar_model(scalar_blocks(),"temperature",24,"2026-02-01T00:00:00Z")
    assert model["variable"]=="temperature"
    assert report["acceptance_passed"] is False
    assert "reanalysis" in report["reference_limitation"].lower()


def test_wind_shadow_uses_one_shared_vector_weight_gate():
    model,report=train_wind_model(wind_blocks(),24,"2026-02-01T00:00:00Z")
    assert model["method"]=="linear-softmax-energy"
    assert len(report["missing_source_matrix"])==10
    assert report["acceptance_passed"] is False
    weights=predict_weights(model,wind_blocks()[-1]["features"][:5],np.ones(4,dtype=bool))
    assert weights.shape==(5,4)
    assert np.allclose(weights.sum(axis=1),1)


def test_rain_extreme_support_is_counted_by_event_block_not_grid_cells():
    blocks=scalar_blocks(events=8,shift=120)
    cross=scalar_blocks(events=8,shift=120.25)
    _,report=train_scalar_model(blocks,"rain",24,"2026-02-01T00:00:00Z",
                                cross_blocks=cross,require_independent=True)
    evidence=report["extreme_event_evidence"]
    assert evidence["64.5"]["observed_event_cells"]>evidence["64.5"]["event_blocks_with_observed_event"]
    assert evidence["64.5"]["event_blocks_with_observed_event"]==report["test_event_blocks"]
    assert evidence["115.6"]["event_blocks_with_observed_event"]==report["test_event_blocks"]
    assert report["extreme_event_gate_passed"] is False  # too few held-out daily blocks for the declared gate


def test_rain_extreme_gate_requires_independent_event_blocks():
    from mausam.multi_shadow import _extreme_block_counts, _extreme_gate
    blocks=[]
    for i,maximum in enumerate([80.,130.,220.,90.,140.,70.]):
        obs=np.array([0.,maximum])
        blocks.append({"event_id":f"e{i}","observations":obs})
    counts=_extreme_block_counts(blocks)
    assert counts["64.5"]==6
    assert counts["115.6"]==3
    assert counts["204.5"]==1
    assert not _extreme_gate(counts)
    assert _extreme_gate({"64.5":6,"115.6":3,"204.5":2})
    assert not _extreme_gate({"64.5":6,"115.6":3,"204.5":1})


def test_missing_source_gate_limits_degradation_not_only_equal_comparison():
    from mausam.multi_shadow import MISSING_SINGLE_MAX_DEGRADATION,MISSING_PAIR_MAX_DEGRADATION
    assert MISSING_SINGLE_MAX_DEGRADATION < MISSING_PAIR_MAX_DEGRADATION < 1


def test_rain_candidate_cannot_pass_without_extreme_event_support():
    model,report=train_scalar_model(
        scalar_blocks(), "rain", 24, "2026-02-01T00:00:00Z",
        cross_blocks=scalar_blocks(shift=.25), require_independent=True
    )
    assert model is not None
    assert report["extreme_event_gate_passed"] is False
    assert set(report["extreme_event_evidence"])=={"64.5","115.6","204.5"}
    assert all(row["support_pass"] is False for row in report["extreme_event_evidence"].values())
    assert report["numerical_gate_passed"] is False
    assert report["acceptance_passed"] is False


def test_missing_source_gate_requires_all_ten_accepted_patterns():
    _,report=train_scalar_model(
        scalar_blocks(), "temperature", 24, "2026-02-01T00:00:00Z"
    )
    assert len(report["missing_source_matrix"])==10
    expected=all(row["acceptance_pass"] for row in report["missing_source_matrix"])
    assert report["missing_source_gate_passed"] is expected


def test_wind_missing_source_gate_requires_all_ten_patterns():
    _,report=train_wind_model(wind_blocks(),24,"2026-02-01T00:00:00Z")
    assert len(report["missing_source_matrix"])==10
    expected=all(row["acceptance_pass"] for row in report["missing_source_matrix"])
    assert report["missing_source_gate_passed"] is expected


def test_runtime_inference_masks_partial_source_cells(tmp_path):
    import json
    from pathlib import Path
    from mausam.multi_shadow import infer_current

    blocks=scalar_blocks(events=6,lead=24)
    model,_=train_scalar_model(blocks,"rain",24,"2026-02-01T00:00:00Z")
    model_dir=tmp_path/"models"/"rain";model_dir.mkdir(parents=True)
    (model_dir/"024.model.json").write_text(json.dumps(model))
    latitude=[12.,11.,10.,9.];longitude=[78.,79.,80.,81.]
    values=np.stack([
        blocks[-1]["samples"][:,i,0].reshape(4,4) for i in range(4)
    ])
    values[0,0,0]=np.nan
    values[0:3,0,1]=np.nan
    product={
        "schema_version":1,"data_kind":"forecast","coverage":"india",
        "run_id":"public-runtime-fixture","initialization":"2026-01-06T00:00:00+00:00",
        "calibrated":False,"latitude":latitude,"longitude":longitude,
        "sources":{},
    }
    for index,source in enumerate(SOURCES):
        product["sources"][source]={"24":{"rain":[None if not np.isfinite(v) else float(v) for v in values[index].ravel()]}}
    public=tmp_path/"public";public.mkdir()
    asset=public/"fixture.json";asset.write_text(json.dumps(product))
    (public/"latest.json").write_text(json.dumps({"path":"fixture.json"}))
    out=tmp_path/"shadow.json"
    result=infer_current(public,tmp_path/"models",out)
    rain=result["leads"]["24"]["rain"]
    assert rain["weights"]["GFS"][0]==0
    assert rain["mean"][0] is not None
    assert rain["mean"][1] is None
    assert all(rain["weights"][source][1] is None for source in SOURCES)
