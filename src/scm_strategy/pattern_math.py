# SPDX-License-Identifier: BSD-3-Clause
"""Self-authored exploratory arithmetic; no source readers or implicit I/O.

Migrated from the reviewed candidate, geometry, bilateral and conditional
permutation implementations. Floating-point operation order is retained.
"""
from __future__ import annotations
from collections import defaultdict
from functools import lru_cache
import math
import numpy as np
from scipy.stats import t


def value(row, key):
    try: return float(row[key])
    except (KeyError, ValueError, TypeError): return float("nan")


def finite(value):
    return value is not None and bool(np.isfinite(value))


def technical_eligible(row):
    return (str(row.get("available")).lower()=="true" and row.get("direction")=="backward"
            and value(row,"window_duration_s")==20 and value(row,"n_left_events")>=10
            and value(row,"n_right_events")>=10)


def body_scale(rows, fields):
    result={}
    for field in fields:
        values=np.array([value(r,field) for r in rows]);valid=values[np.isfinite(values)]
        if len(valid)<2 or valid.std(ddof=1)<=0:raise ValueError("body_scale_not_estimable:"+field)
        result[field]={"n":len(valid),"mean":float(valid.mean()),"sample_sd":float(valid.std(ddof=1))}
    return result


def graph_summary(ids, edges):
    adjacency={identifier:set() for identifier in sorted(ids)}
    for edge in edges:
        adjacency[edge["a"]].add(edge["b"]);adjacency[edge["b"]].add(edge["a"])
    components=[];remaining=set(ids)
    while remaining:
        root=min(remaining);todo=[root];members=[];remaining.remove(root)
        while todo:
            current=todo.pop();members.append(current)
            for other in sorted(adjacency[current]):
                if other in remaining:remaining.remove(other);todo.append(other)
        components.append(sorted(members))
    components.sort(key=lambda group:(-len(group),group))
    membership={p:i+1 for i,c in enumerate(components) for p in c}
    nodes=[{"anonymized_id":p,"degree":len(adjacency[p]),"component_id":membership[p],"component_n":len(components[membership[p]-1])} for p in sorted(ids)]
    return {"n_subjects":len(ids),"n_edges":len(edges),"n_subjects_with_edges":sum(bool(adjacency[p]) for p in ids),
            "n_isolates":sum(not adjacency[p] for p in ids),"components_including_isolates":components,
            "nonisolated_component_sizes":[len(c) for c in components if len(c)>1],"nodes":nodes}


def body_only_matching(summary, edges, maximum_component_size):
    weights={tuple(sorted((e["a"],e["b"]))):e["body_distance_full50_sd"] for e in edges if finite(e["body_distance_full50_sd"])}
    selected=[]
    for component in summary["components_including_isolates"]:
        if len(component)>maximum_component_size:return {"status":"not_computed","reason":"component_exceeds_exact_matching_limit","pairs":[],"unmatched_ids":sum(summary["components_including_isolates"],[])}
        @lru_cache(None)
        def solve(remaining):
            if not remaining:return (0,0.,())
            first,*rest=remaining;best=solve(tuple(rest))
            for other in rest:
                pair=tuple(sorted((first,other)))
                if pair not in weights:continue
                n,total,prior=solve(tuple(p for p in rest if p!=other))
                candidate=(n+1,total+weights[pair],tuple(sorted((*prior,pair))))
                if candidate[0]>best[0] or (candidate[0]==best[0] and (candidate[1]>best[1]+1e-12 or (abs(candidate[1]-best[1])<=1e-12 and candidate[2]<best[2]))):best=candidate
            return best
        selected.extend(solve(tuple(component))[2])
    selected=sorted(selected);matched={p for pair in selected for p in pair}
    return {"status":"computed_exact","n_pairs":len(selected),"n_subjects":len(matched),"pairs":[{"a":a,"b":b,"body_distance_full50_sd":weights[(a,b)]} for a,b in selected],
            "unmatched_ids":sorted(set(n["anonymized_id"] for n in summary["nodes"])-matched),
            "selection_inputs_only":["speed","height","weight","navicular_ratio","anonymous tie-break IDs"]}


def degree_weights(edges, graph):
    degrees={n["anonymized_id"]:n["degree"] for n in graph["nodes"]}
    weights=np.array([.5*(1/degrees[e["a"]]+1/degrees[e["b"]]) for e in edges])
    return weights/weights.sum() if len(weights) else weights


def empirical_frontier(edges, weights, metric):
    values=np.array([e[metric+"_abs_difference"] for e in edges]);valid=np.isfinite(values)
    if not valid.any():return []
    w=weights[valid];w=w/w.sum();values=values[valid]
    return [{"metric":metric,"absolute_tolerance":float(t),"n_edges_with_metric":len(values),"n_edges_all":len(edges),
             "n_edges_within":int(np.count_nonzero(values<=t)),"edge_fraction":float(np.mean(values<=t)),
             "degree_balanced_fraction":float(w[values<=t].sum()),"interpretation":"descriptive tolerance curve, not an equivalence test"}
            for t in np.unique(np.r_[0.,values])]


def joint_frontier(edges, weights):
    x=np.array([e["pressure_peak_N_abs_difference"] for e in edges]);y=np.array([e["effective_area_cm2_abs_difference"] for e in edges]);valid=np.isfinite(x)&np.isfinite(y)
    if not valid.any():return []
    x=x[valid];y=y[valid];w=weights[valid];w=w/w.sum();result=[]
    for tx in np.unique(np.r_[0.,x]):
        for ty in np.unique(np.r_[0.,y]):
            included=(x<=tx)&(y<=ty)
            result.append({"peak_tolerance_N":float(tx),"area_tolerance_cm2":float(ty),"n_edges_all":len(edges),"n_edges_with_both":len(x),
                           "n_edges_within_both":int(included.sum()),"edge_fraction":float(included.mean()),"degree_balanced_fraction":float(w[included].sum())})
    return result


def pressure_noise_reference(rows, config):
    grouped=defaultdict(list)
    for row in rows:grouped[row["anonymized_id"]].append(row)
    summaries={};details=[]
    for metric,role in [("contact_ms","strategy_timing"),("pressure_peak_N","observable_pressure"),("effective_area_cm2","observable_pressure")]:
        eligible=[]
        for pid,group in sorted(grouped.items()):
            group=sorted(group,key=lambda r:(value(r,"replicate_index"),r["zebris_trial_id"]))
            x=np.array([value(r,metric) for r in group]);v=np.array([value(r,"speed_kmh") for r in group])
            reasons=[]
            if len(x)<2:reasons.append("single_trial")
            if not all(technical_eligible(r) for r in group):reasons.append("technical_ineligible_trial")
            if not np.isfinite(x).all() or not np.isfinite(v).all():reasons.append("missing_value")
            if len(v) and np.isfinite(v).all() and np.ptp(v)>.15:reasons.append("repeat_speed_range_exceeded")
            if not reasons:
                ss=float(np.sum((x-x.mean())**2));df=len(x)-1;delta=float(x[-1]-x[0]);eligible.append([ss,df,delta])
            details.append({"anonymized_id":pid,"metric":metric,"role":role,"n_trials":len(x),"eligible":not reasons,"reasons":";".join(reasons)})
        data=np.asarray(eligible)
        if len(data)<2:summaries[metric]={"status":"not_estimable","n_subjects":len(data)};continue
        sw=float(np.sqrt(data[:,0].sum()/data[:,1].sum()));bias=float(data[:,2].mean());sd=float(data[:,2].std(ddof=1))
        rng=np.random.default_rng(config["seed"]);draws=rng.integers(len(data),size=(config["bootstrap_replicates"],len(data)))
        samples=data[draws];sw_samples=np.sqrt(samples[:,:,0].sum(1)/samples[:,:,1].sum(1));bias_samples=samples[:,:,2].mean(1)
        summaries[metric]={"status":"estimated","role":role,"n_subjects":len(data),"n_trials":int(data[:,1].sum()+len(data)),
                           "within_sd":sw,"within_sd_bootstrap_ci95":np.quantile(sw_samples,[.025,.975]).tolist(),
                           "first_last_bias":bias,"first_last_bias_bootstrap_ci95":np.quantile(bias_samples,[.025,.975]).tolist(),
                           "first_last_difference_sd":sd,"approximate_loa":[bias-1.96*sd,bias+1.96*sd],
                           "max_observed_absolute_repeat_difference":float(np.abs(data[:,2]).max()),
                           "interpretation":"same-session measurement/noise reference; not a meaningful-equivalence threshold"}
    return summaries,details


def chamfer_components(a,b):
    from scipy.spatial import cKDTree
    a=np.asarray(a,float);b=np.asarray(b,float)
    if a.ndim!=2 or b.ndim!=2 or a.shape[1]!=2 or b.shape[1]!=2 or not len(a) or not len(b) or not np.isfinite(a).all() or not np.isfinite(b).all():raise ValueError("finite_nonempty_two_angle_clouds_required")
    _,bi=cKDTree(b).query(a,k=1,eps=0,workers=1)
    _,ai=cKDTree(a).query(b,k=1,eps=0,workers=1)
    # Each component retains degrees squared. Mean over two components is
    # the requested normalization by channel count.
    return .5*(np.mean(np.square(a-b[bi]),axis=0)+np.mean(np.square(b-a[ai]),axis=0))


def bilateral_chamfer(a,b,centered=False):
    a=np.asarray(a,float);b=np.asarray(b,float)
    if centered:a=a-a.mean(axis=0);b=b-b.mean(axis=0)
    components=np.array([chamfer_components(a[:,[0,1]],b[:,[0,1]]),chamfer_components(a[:,[2,3]],b[:,[2,3]])])
    return {"chamfer_rms_deg":float(np.sqrt(components.mean())),
            "left_chamfer_rms_deg":float(np.sqrt(components[0].mean())),"right_chamfer_rms_deg":float(np.sqrt(components[1].mean())),
            "knee_component_rms_deg":float(np.sqrt(components[:,0].mean())),"ankle_component_rms_deg":float(np.sqrt(components[:,1].mean()))}


def log_ratio(left,right):
    if not all(np.isfinite([left,right])) or min(left,right)<=0:return float("nan")
    return math.log(left/right)


def fit_model(x,y,extra=None,inference=True):
    x,y=np.asarray(x,float),np.asarray(y,float)
    X=np.column_stack([np.ones(len(x)),x] if extra is None else [np.ones(len(x)),x,np.asarray(extra,float)])
    if not np.isfinite(X).all() or not np.isfinite(y).all():raise ValueError("nonfinite_design")
    n,p=X.shape
    if n<=p:raise ValueError("no_residual_degrees_of_freedom")
    beta,_,rank,singular=np.linalg.lstsq(X,y,rcond=None)
    if rank<p:raise ValueError("rank_deficient")
    residual=y-X@beta;df=n-p
    result={"beta":beta,"residual":residual,"n":n,"df":df,"rank":int(rank)}
    z=np.column_stack([np.ones(n),(X[:,1:]-X[:,1:].mean(0))/X[:,1:].std(0)])
    result["standardized_condition_number"]=float(np.linalg.cond(z))
    if inference:
        inv=np.linalg.inv(X.T@X);h=np.sum((X@inv)*X,axis=1)
        if np.any(1-h<=1e-10):raise ValueError("unit_leverage")
        scaled=X*(residual/(1-h))[:,None]
        covariance=inv@(scaled.T@scaled)@inv
        se=np.sqrt(np.maximum(np.diag(covariance),0));q=t.ppf(.975,df)
        result.update(covariance=covariance,hc3_se=se,hc3_ci95=np.column_stack([beta-q*se,beta+q*se]),leverage=h)
    return result


def repeat_stats(groups):
    arrays=[np.asarray(g,float) for g in groups]
    if len(arrays)<2 or any(len(g)<2 for g in arrays):raise ValueError("insufficient_repeat_groups")
    ss=sum(float(((g-g.mean())**2).sum()) for g in arrays)
    sw=math.sqrt(ss/sum(len(g)-1 for g in arrays))
    delta=np.array([g[-1]-g[0] for g in arrays]);bias=float(delta.mean());sd=float(delta.std(ddof=1))
    return {"pooled_within_sd":sw,"participant_balanced_within_sd":math.sqrt(float(np.mean([g.var(ddof=1) for g in arrays]))),
            "first_last_bias":bias,"first_last_difference_sd":sd,"loa_lower":bias-1.96*sd,"loa_upper":bias+1.96*sd,
            "repeatability_coefficient":1.96*math.sqrt(2)*sw,
            "median_absolute_asymmetry":float(np.median([np.median(abs(g)) for g in arrays])),
            "median_absolute_first_last_change":float(np.median(abs(delta)))}


def bootstrap_repeat(groups,reps,seed):
    point=repeat_stats(groups);rng=np.random.default_rng(seed);samples={k:[] for k in point}
    for ids in rng.integers(len(groups),size=(reps,len(groups))):
        r=repeat_stats([groups[i] for i in ids])
        for key,value in r.items():samples[key].append(value)
    return {k:{"estimate":v,"bootstrap_ci95":np.quantile(samples[k],[.025,.975]).tolist()} for k,v in point.items()}


def sign_summary(groups,thresholds):
    rows=[]
    for threshold in thresholds:
        used=[g for g in groups if min(abs(g[0]),abs(g[-1]))>=threshold]
        agreeing=sum(g[0]*g[-1]>0 for g in used)
        zeros=sum(g[0]==0 or g[-1]==0 for g in used)
        rows.append({"minimum_both_absolute_log_ratio":threshold,"n_groups":len(used),"same_nonzero_sign_n":agreeing,"zero_endpoint_n":zeros,
                     "same_nonzero_sign_fraction":agreeing/len(used) if used else None,
                     "interpretation":"descriptive magnitude conditioning only; no participants removed from primary analysis"})
    return rows


def association(rows,outcome,spec,cfg):
    if spec=="repeat_mean":ykey=outcome+"_repeat_mean";extra_key=None
    elif spec=="speed_adjusted":ykey=outcome;extra_key="centered_log_speed"
    elif spec=="geometry_adjusted":ykey=outcome;extra_key="static_area_log_lr"
    else:ykey=outcome;extra_key=None
    used=[];excluded=[]
    for row in rows:
        keys=["dRNH_per001",ykey]+([extra_key] if extra_key else [])
        if all(row.get(k) is not None and np.isfinite(row[k]) for k in keys):used.append(row)
        else:excluded.append({"anonymized_id":row["anonymized_id"],"reason":"missing/nonfinite required feature"})
    x=np.array([r["dRNH_per001"] for r in used]);y=np.array([r[ykey] for r in used]);extra=np.array([r[extra_key] for r in used]) if extra_key else None
    base={"outcome":outcome,"spec":spec,"n":len(used),"excluded":excluded,"unit":"log left/right ratio per 0.01 static L-R navicular/length ratio"}
    try:point=fit_model(x,y,extra)
    except ValueError as e:return {**base,"status":"not_estimable","reason":str(e)},[],[]
    rng=np.random.default_rng(cfg["seed"]);samples=[];failures=0
    for idx in rng.integers(len(used),size=(cfg["bootstrap_replicates"],len(used))):
        try:samples.append(fit_model(x[idx],y[idx],None if extra is None else extra[idx],False)["beta"])
        except ValueError:failures+=1
    boot=np.asarray(samples)
    intervals=np.quantile(boot,[.025,.975],axis=0).T if len(boot) else np.full((len(point["beta"]),2),np.nan)
    coef=[]
    terms=["intercept","dRNH_per001"]+([extra_key] if extra_key else [])
    for j,term in enumerate(terms):
        coef.append({"outcome":outcome,"spec":spec,"n":len(used),"term":term,"estimate":point["beta"][j],
                     "hc3_ci95_low":point["hc3_ci95"][j,0],"hc3_ci95_high":point["hc3_ci95"][j,1],
                     "bootstrap_ci95_low":intervals[j,0],"bootstrap_ci95_high":intervals[j,1],
                     "ratio_multiplier":math.exp(point["beta"][j]) if j==1 else None})
    influence=[]
    if spec=="primary":
        for i,row in enumerate(used):
            keep=np.arange(len(used))!=i
            try:
                deleted=fit_model(x[keep],y[keep],inference=False)["beta"][1]
                influence.append({"outcome":outcome,"omitted_id":row["anonymized_id"],"full_beta":point["beta"][1],"deleted_beta":deleted,
                                  "slope_sign_reversal":bool(point["beta"][1]*deleted<0),"absolute_slope_change":abs(deleted-point["beta"][1])})
            except ValueError as e:influence.append({"outcome":outcome,"omitted_id":row["anonymized_id"],"failure":str(e)})
    result={**base,"status":"estimated","coefficients":coef,"bootstrap_valid":len(boot),"bootstrap_failed":failures,
            "standardized_condition_number":point["standardized_condition_number"],"r_squared":1-float(np.sum(point["residual"]**2))/float(np.sum((y-y.mean())**2)) if np.var(y)>0 else None,
            "exposure_extra_correlation":float(np.corrcoef(x,extra)[0,1]) if extra is not None else None,
            "side_transform_checks":{"both_sides_relabel_slope":fit_model(-x,-y,inference=False)["beta"][1],"dynamic_only_relabel_slope":fit_model(x,-y,inference=False)["beta"][1]} if spec=="primary" else None,
            "interpretation":"observational association; side transformations are algebra, not validation of anatomical labels"}
    return result,coef,influence


def center_within(values,groups,weights):
    """Final axis indexes edges; works on one vector or many permutation rows."""
    values=np.asarray(values,float);out=values.copy()
    for group in np.unique(groups):
        indices=np.flatnonzero(groups==group);w=weights[indices]
        mean=np.sum(values[...,indices]*w,axis=-1)/w.sum()
        out[...,indices]-=np.expand_dims(mean,-1)
    return out


def weighted_r(x,y,weights):
    x=np.asarray(x,float);y=np.asarray(y,float);w=np.asarray(weights,float);w=w/w.sum()
    x=x-np.sum(x*w,axis=-1,keepdims=True);y=y-np.sum(y*w,axis=-1,keepdims=True)
    denominator=np.sqrt(np.sum(x*x*w,axis=-1)*np.sum(y*y*w,axis=-1))
    if np.any(denominator<=0):raise ValueError("zero conditional variance; statistic not estimable")
    return np.sum(x*y*w,axis=-1)/denominator


def permute_vectors(vectors,node_groups,replicates,seed):
    rng=np.random.default_rng(seed);indices=np.tile(np.arange(len(vectors)),(replicates,1))
    for i in range(replicates):
        for group in node_groups:indices[i,group]=rng.permutation(group)
    return indices
