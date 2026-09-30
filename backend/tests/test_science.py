import numpy as np
import pytest
from mausam.science import masked_softmax,mixture,crps,verification,reliability,ResidualCalibration,NoEligibleSources,blocked_bootstrap_difference
from mausam.normalize import precipitation_intervals,convert_units,rotate_wind

def test_missing_sources_are_excluded_not_zero_forecasts():
    w=masked_softmax([2,10,1],[True,False,True]);assert w[1]==0;assert np.isclose(w.sum(),1)

def test_no_sources_withholds():
    with pytest.raises(NoEligibleSources):masked_softmax([1,2],[False,False])

def test_extreme_softmax_stability():
    assert np.isfinite(masked_softmax([1e6,1e6-1],[True,True])).all()

def test_mixture_quantile_is_not_average_of_quantiles():
    r=mixture([[0,0],[100,100]],[.5,.5],64.5)
    assert r['p10']==0 and r['p90']==100 and r['mean']==50 and r['probability']==.5

def test_ensemble_size_does_not_change_source_weight():
    a=mixture([[0],[100]*50],[.5,.5],64.5);b=mixture([[0]*50,[100]],[.5,.5],64.5)
    assert np.isclose(a['mean'],b['mean']) and np.isclose(a['probability'],b['probability'])

def test_crps_agrees_with_bruteforce():
    x=np.array([0,10,12,50]);w=np.array([.1,.4,.2,.3]);y=8
    brute=np.dot(w,np.abs(x-y))-.5*np.sum(w[:,None]*w[None,:]*np.abs(x[:,None]-x[None,:]))
    assert crps(x,w,y)==pytest.approx(brute)

def test_crps_perfect_forecast():assert crps([4],[1],4)==0

def test_units():
    assert convert_units([.01],'rain','m')[0]==10
    assert convert_units([273.15],'temperature','K')[0]==0
    assert convert_units([36],'wind_u','km h-1')[0]==10
    with pytest.raises(ValueError):convert_units([1],'rain','inches')

def test_accumulation_same_run_and_complete_window():
    assert precipitation_intervals([0,2,5],[0,6,12],['a']*3).tolist()==[2,3]
    for values,leads,runs in [([0,5,1],[0,6,12],['a']*3),([0,2],[0,12],['a']*2),([0,2],[0,6],['a','b'])]:
        with pytest.raises(ValueError):precipitation_intervals(values,leads,runs)

def test_wind_rotation_preserves_magnitude():
    u,v=rotate_wind(3,4,np.pi/2);assert np.hypot(u,v)==pytest.approx(5)

def test_undefined_csi_is_not_perfect_score():
    s=verification([0,0],[0,0],[0,0],64.5);assert s['csi'] is None and s['brier']==0

def test_reliability_counts_probability_one():
    result=reliability([0,1],[0,1]);assert result[0]['n']==1 and result[-1]['n']==1

def test_residual_calibration_requires_evidence():
    with pytest.raises(ValueError):ResidualCalibration().fit([1,2],[2,3])
    model=ResidualCalibration().fit(np.arange(40),np.arange(40)+2);assert np.all(model.predict(10)==12)

def test_block_bootstrap_uses_event_units():
    result=blocked_bootstrap_difference([1,1,2,2],[2,2,4,4],['a','a','b','b']);assert result[0]<0 and result[1]<0

def test_wind_extremes_do_not_cancel_with_opposing_vectors():
    from mausam.science import blend_wind_components
    r=blend_wind_components([[20],[-20]],[[0],[0]],[.5,.5],17)
    assert r['u']==0 and r['speed_distribution']['probability']==1
