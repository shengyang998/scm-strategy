from fractions import Fraction
import numpy as np
import pytest
from scm_strategy.features import effective_area_frame,force_weighted_area,bilateral_excursion,percentile_excursion
from scm_strategy.statistics import fit_ols,coefficient_intervals,loso,bootstrap_analysis,NumericalFailure


def test_area_hand_calculation_and_invariances():
    f,a,_=effective_area_frame(np.full((2,3),4.),.25)
    assert f==pytest.approx(6) and a==pytest.approx(1.5)
    p=np.array([[1.,4.,2.],[0.,3.,0.]])
    f,a,_=effective_area_frame(p,.4)
    for equivalent in [p.T,p[::-1],np.pad(p,((3,2),(1,4))),p.ravel()[::-1]]:
        ff,aa,_=effective_area_frame(equivalent,.4)
        assert ff==pytest.approx(f) and aa==pytest.approx(a)
    ff,aa,_=effective_area_frame(p*7,.4)
    assert ff==pytest.approx(f*7) and aa==pytest.approx(a)
    assert np.isnan(effective_area_frame(np.zeros((0,0)),.4)[1])
    ae,num,imp=force_weighted_area([2,0,4],[1,np.nan,3],[.1,100,.1])
    assert ae==pytest.approx(7/3) and num==pytest.approx(1.4) and imp==pytest.approx(.6)
    with pytest.raises(ValueError):effective_area_frame([-1,2],.4)


def test_continuous_motion_window_and_explicit_degree_unit():
    time=np.arange(0,30+1/120,1/120)
    output=bilateral_excursion(time,2*time,4*time,(15,35),unit="degree",time_offset_s=10)
    assert output["mean_deg"]==pytest.approx(54)
    shifted=bilateral_excursion(time,2*time+900,4*time-900,(15,35),unit="degree",time_offset_s=10)
    assert shifted["mean_deg"]==pytest.approx(54)
    with pytest.raises(ValueError,match="degree"):percentile_excursion([1,2,3],unit="radian")


def test_ols_hc3_exact_rational_fixture():
    x=np.column_stack([np.ones(4),np.arange(4)])
    fit=fit_ols(x,np.array([1.,2.,2.,4.]))
    np.testing.assert_allclose(fit.beta,[.9,.9])
    vectors=[[Fraction(7,10),Fraction(-3,10)],[Fraction(4,10),Fraction(-1,10)],
             [Fraction(1,10),Fraction(1,10)],[Fraction(-2,10),Fraction(3,10)]]
    weights=[Fraction(1,9),Fraction(4,49),Fraction(1),Fraction(16,9)]
    golden=np.array([[float(sum(w*v[i]*v[j] for w,v in zip(weights,vectors))) for j in range(2)] for i in range(2)])
    np.testing.assert_allclose(fit.covariance_hc3,golden,atol=1e-12)
    assert coefficient_intervals(fit).shape==(2,2)


def fixture():
    a=np.arange(12.)
    x0=np.column_stack([np.ones(12),a])
    x1=np.column_stack([x0,np.sin(a)])
    return np.exp(2+.03*a+.1*np.cos(a)),x0,x1,[f"SYN-{i:05d}" for i in range(12)]


def test_bootstrap_identity_isolation_and_training_only_smear():
    y,x0,x1,ids=fixture()
    counts=np.array([3,1,2,1,1,2,1,1,1,1,1,1])
    result=loso(y,x0,x1,ids,counts,trace=True)
    for trace,row in zip(result["trace"],result["predictions"]):
        assert trace["heldout_id"] not in trace["training_ids"]
        assert len(trace["training_ids"])==counts.sum()-counts[ids.index(trace["heldout_id"])]
    altered=y.copy();altered[0]*=10000
    a=loso(y,x0,x1,ids)["predictions"][0]
    b=loso(altered,x0,x1,ids)["predictions"][0]
    for key in ["baseline_prediction","augmented_prediction","baseline_smear","augmented_smear"]:
        assert a[key]==pytest.approx(b[key])
    first=bootstrap_analysis(y,x0,x1,ids,20,20)
    second=bootstrap_analysis(y,x0,x1,ids,20,20)
    assert first["metrics"]==second["metrics"]


def test_rank_failure_is_explicit():
    x=np.column_stack([np.ones(10),np.arange(10),2*np.arange(10)])
    with pytest.raises(NumericalFailure,match="rank"):fit_ols(x,np.arange(10))
