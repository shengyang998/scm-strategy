# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 SCM Research contributors. New project contribution.
"""Aggregate paper tables/figures and independent simulation calibration.

Only normalized paper_study results are consumed. No raw device formats,
private paths, individual plots, or stored empirical manuscript values occur.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np

from .statistics import bootstrap_analysis, fit_ols, loso, percentile_interval

REPORT_VERSION = "scm-strategy.paper-report/1"
CALIBRATION_VERSION = "scm-strategy.calibration/1"
MORPHOLOGY_MODELS = ("body_to_knee", "body_to_ankle", "extension_contact", "extension_peak", "extension_area")
PREDICTION_SPECS = ("primary", "PASS_only", "participant_mean", "p10_p90", "offset_m010", "offset_p010", "offset_m025", "offset_p025", "primary_height_replaced_by_age")
MEASUREMENT_KEYS = (
    "pooled_within_sd_cm2", "participant_balanced_within_sd_cm2", "first_last_bias_cm2",
    "first_last_loa_lower_cm2", "first_last_loa_upper_cm2", "repeatability_coefficient_cm2",
    "median_absolute_first_last_difference_cm2",
)


def _safe(value):
    if isinstance(value, dict):return {str(k):_safe(v) for k,v in value.items()}
    if isinstance(value, (list,tuple,np.ndarray)):return [_safe(v) for v in value]
    if isinstance(value, (np.integer,np.bool_)):return value.item()
    if isinstance(value, (float,np.floating)):return float(value) if math.isfinite(value) else None
    return value


def _write_json(path, value):
    path.write_text(json.dumps(_safe(value),indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")


def _write_csv(path, rows):
    if not rows:
        path.write_text("status\nnot_available\n",encoding="utf-8");return
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(_safe(v),separators=(",",":")) if isinstance(v,(list,tuple,dict,np.ndarray)) else _safe(v) for k,v in row.items()})


def _format(value):
    if value is None:return "not estimable"
    if isinstance(value,(list,tuple)):
        return "["+", ".join(_format(v) for v in value)+"]"
    if isinstance(value,float):return f"{value:.6g}" if math.isfinite(value) else "not estimable"
    return str(value).replace("|","/").replace("\n"," ")


def _markdown_table(rows):
    if not rows:return "Not available for the supplied bundle.\n"
    keys=list(dict.fromkeys(k for row in rows for k in row))
    return "\n".join(["|"+"|".join(keys)+"|","|"+"|".join("---" for _ in keys)+"|"]+
                     ["|"+"|".join(_format(row.get(k)) for k in keys)+"|" for row in rows])+"\n"


def _display_rows(name,rows):
    """Readable table views, preserving richer numbers in JSON and CSV."""
    if name=="T1_observed_descriptives":
        shown=[]
        for r in rows:
            item={"variable":r["variable"]}
            for scope in ["primary","not_selected","extension"]:
                d=r[scope]
                item[scope]="not available" if not d.get("n") else f"{_format(d['mean'])} ({_format(d['sd'])}); n={d['n']}"
            shown.append(item)
        return shown
    if name=="T1_cohort_profiles":
        return [{k:r.get(k) for k in ["variable","level","selected_n","not_selected_n","selected_mean","not_selected_mean","smd_selected_vs_not_selected"]} for r in rows]
    if name in {"T2_prediction","S1_prediction_sensitivity"}:
        return [{k:r.get(k) for k in ["analysis","n","baseline_mae","augmented_mae","delta_mae_baseline_minus_augmented","approx_delta_interval95"]} for r in rows]
    if name=="T3_morphology":
        return [{"analysis":r["analysis"],"n":r["n"],"outcome_logged":r["outcome_logged"],
                 "coefficient":(r["coefficient"] or {}).get("estimate"),"HC3_95%":(r["coefficient"] or {}).get("hc3_ci95"),
                 "bootstrap_95%":(r["coefficient"] or {}).get("participant_bootstrap_ci95")} for r in rows]
    if name=="T4_measurement":
        shown=[]
        for metric in MEASUREMENT_KEYS:
            item={"metric (cm²)":metric}
            for scope in ["full_pressure_cohort","primary_motion_cohort"]:
                r=next((r for r in rows if r["cohort"]==scope and r["metric"]==metric),{})
                item[scope]=_format(r.get("estimate"))+" "+_format(r.get("bootstrap_ci95"))
            shown.append(item)
        return shown
    if name=="S2_all_coefficients":
        return [{k:r.get(k) for k in ["analysis","model","term","estimate","hc3_ci95","participant_bootstrap_ci95"]} for r in rows]
    if name=="S4_calibration" and rows and "scenario" in rows[0]:
        return [{k:r.get(k) for k in ["scenario","target_delta_mae","target_mc_se","interval_center_bias","interval_center_bias_total_mc_se","coverage_count","datasets_with_interval","coverage_wilson_ci95","mean_interval_width","mean_bootstrap_unique_ids"]} for r in rows]
    return rows


def _matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("Paper figures require Matplotlib: run 'uv sync --extra paper' from the source checkout or install the local wheel with the [paper] extra") from exc
    return plt


def _prediction_rows(analyses):
    rows=[]
    for spec in PREDICTION_SPECS:
        for outcome in ["contact_ms","pressure_peak_N"]:
            if spec=="primary_height_replaced_by_age" and outcome!="contact_ms":continue
            name=spec+"__"+outcome
            a=analyses[name]
            rows.append({"analysis":name,"outcome":outcome,"n":a.get("n"),"status":a.get("status"),
                         "metrics":a.get("cv_metrics",{}),"intervals":a.get("cv_metric_bootstrap_ci95",{}),
                         "warnings":a.get("warnings",[]),"bootstrap":{k:v for k,v in a.get("bootstrap",{}).items() if k!="distinct_participant_counts"},
                         "interpretation_gate_passed":a.get("augmented_diagnostics",{}).get("interpretation_gate_passed")})
    return rows


def _coefficient_rows(analyses):
    rows=[]
    for name,a in analyses.items():
        sections=[("baseline",a.get("baseline_coefficients",[])),("augmented",a.get("augmented_coefficients",[]))]
        if "coefficients" in a:sections=[("secondary",a["coefficients"])]
        for model,coefs in sections:
            for c in coefs:rows.append({"analysis":name,"model":model,**c})
    return rows


def _profile_rows(cohort):
    return cohort.get("variables",[]) + cohort.get("categorical",[])


def _measurement_rows(measurement):
    rows=[]
    for key in ["full_pressure_cohort","primary_motion_cohort"]:
        group=measurement.get(key,{})
        stats=group.get("statistics",{})
        for metric in MEASUREMENT_KEYS:
            item=stats.get(metric,{})
            rows.append({"cohort":key,"repeatable_n":group.get("repeatable_n"),
                         "repeat_trial_n":group.get("repeat_trial_n"),"metric":metric,
                         "estimate":item.get("estimate"),"bootstrap_ci95":item.get("bootstrap_ci95"),
                         "status":group.get("status","estimated" if stats else "not_available")})
    return rows


def _quality_count_rows(cohort):
    counts=cohort.get("counts",{})
    quality=cohort.get("producer_supplied_quality_counts",{})
    rows=[]
    for key in ["primary_n","extension_n","paired_trial_rows","pressure_repeat_rows"]:
        value=counts.get(key)
        rows.append({"metric":key,"value":value,"source":"bundle_count" if value is not None else "not_provided"})
    qc=counts.get("primary_qc_counts")
    for label in ["PASS","WARNING"]:
        value=qc.get(label,0) if isinstance(qc,dict) else None
        rows.append({"metric":"primary_"+label+"_rows","value":value,"source":"bundle_count" if value is not None else "not_provided"})
    for key in ["min_complete_events_per_side","primary_PASS_count","primary_WARNING_count","source_exclusions",
                "mot_participants_screened","mot_channel_series_screened","heuristic_review_participants","automatic_exclusions"]:
        value=quality.get(key)
        rows.append({"metric":key,"value":value,"source":"producer_supplied" if value is not None else "not_provided"})
    for key,value in cohort.get("producer_supplied_cohort_counts",{}).items():
        rows.append({"metric":key,"value":value,"source":"producer_supplied_cohort_manifest"})
    return rows


def _aggregate_measurement(measurement):
    """Keep numeric cohort summaries; never transport eligibility/person rows."""
    allowed=("version","seed","bootstrap_replicates","unit","measurement_scope","difference_convention",
             "full_pressure_cohort","primary_motion_cohort","source_quality_counts","source_quality_counts_are_producer_supplied")
    result={key:measurement[key] for key in allowed if key in measurement}
    motion=measurement.get("motion_repeats",{})
    result["motion_repeats"]={key:value for key,value in motion.items() if key not in {"exclusions","details","rows","eligibility"}}
    result["motion_repeats"]["excluded_group_count"]=len(motion.get("exclusions",[]))
    result["repeat_eligibility_exclusion_count"]=sum(not r.get("repeatability_eligible",False) for r in measurement.get("eligibility",[]))
    return result


def _plot_interval(ax, y, estimate, interval, color="#007A87", marker="o"):
    if estimate is None or not np.isfinite(estimate):return False
    if interval is not None and len(interval)==2 and all(v is not None and np.isfinite(v) for v in interval):
        ax.plot(interval,[y,y],color=color,lw=1.8)
    ax.scatter([estimate],[y],color=color,marker=marker,s=30,zorder=3)
    return True


def _profile_value(row, key):
    aliases={"smd":["smd_selected_vs_not_selected","smd_selected_vs_excluded","smd"],
             "name":["variable","field","name"]}
    for field in aliases.get(key,[key]):
        if field in row:return row[field]
    return None


def _save_figure(plt,fig,path):
    fig.savefig(path.with_suffix(".png"),dpi=200,bbox_inches="tight",pad_inches=.20)
    fig.savefig(path.with_suffix(".svg"),bbox_inches="tight",pad_inches=.20)
    plt.close(fig)


def _figures(payload, out, calibration):
    plt=_matplotlib()
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.spines.top":False,
                         "axes.spines.right":False,"svg.fonttype":"none"})
    label="SYNTHETIC INPUT - NOT EMPIRICAL PAPER VALUES" if payload["input_dataset_kind"]=="synthetic" else "PRIVATE EMPIRICAL INPUT - NOT CLEARED FOR PUBLIC RELEASE"
    figure_data={}
    cohort=payload["tables"]["T1"]
    fig,axes=plt.subplots(1,2,figsize=(12,5),layout="constrained")
    counts={**cohort.get("producer_supplied_cohort_counts",{}),**cohort.get("counts",{})}
    count_rows=[{"name":k,"count":v} for k,v in counts.items() if isinstance(v,(int,float))]
    axes[0].axis("off");axes[0].set_title("A  Cohort and trial counts",loc="left")
    count_text="\n".join(k.replace("_"," ")+": "+str(v) for k,v in counts.items()) or "Cohort counts not supplied"
    axes[0].text(.02,.92,count_text,va="top",linespacing=1.7,transform=axes[0].transAxes)
    chosen=[]
    ordered=[]
    for variable in ["age_years","height_cm","weight_kg","bmi","recorded_sex","body_fat_pct","navicular_height_L_mm","navicular_height_R_mm","subject_median_speed_kmh"]:
        ordered.extend(r for r in _profile_rows(cohort) if _profile_value(r,"name")==variable and (variable!="recorded_sex" or r.get("level")=="F"))
    for row in ordered:
        value=_profile_value(row,"smd")
        if value is not None and np.isfinite(value):chosen.append({"variable":_profile_value(row,"name"),"smd":value})
    axes[1].set_title("B  Selection differences",loc="left")
    if chosen:
        values=[r["smd"] for r in chosen];y=np.arange(len(chosen))
        axes[1].hlines(y,0,values,color="#b3c8d0",lw=3);axes[1].scatter(values,y,color="#007A87")
        labels={"recorded_sex":"Female proportion","subject_median_speed_kmh":"Median eligible-trial speed"}
        axes[1].set_yticks(y,[labels.get(r["variable"],r["variable"].replace("_"," ")) for r in chosen]);axes[1].invert_yaxis();axes[1].axvline(0,color="gray",lw=.7)
    else:axes[1].text(.5,.5,"Cohort profiles unavailable\nNo substitution of index-trial speed",ha="center",transform=axes[1].transAxes)
    axes[1].set_xlabel("Descriptive standardized mean difference")
    fig.suptitle(label+"\nStudy coverage and selection",fontsize=12)
    _save_figure(plt,fig,out/"F1_cohort_flow_selection")
    figure_data["F1"]={"panels":["A","B"],"counts":count_rows,"selection":chosen,"profile_status":cohort.get("status")}

    predictions=payload["tables"]["T2"]
    fig,axes=plt.subplots(2,2,figsize=(12,10),layout="constrained")
    for col,outcome in enumerate(["contact_ms","pressure_peak_N"]):
        unit="ms" if col==0 else "N";color="#007A87" if col==0 else "#BB6225"
        main=next(r for r in predictions if r["analysis"]=="primary__"+outcome)
        metrics=main["metrics"];ax=axes[0,col]
        vals=[metrics.get(k) for k in ["mean_mae","baseline_mae","augmented_mae"]]
        if all(v is not None and np.isfinite(v) for v in vals):
            ax.barh([0,1,2],vals,color=["#bbc7cd","#17374a",color]);ax.set_yticks([0,1,2],["Training mean","Baseline","Added motion"]);ax.invert_yaxis()
        else:ax.text(.5,.5,"Model not estimable",ha="center",transform=ax.transAxes)
        ax.set_title(("A  Contact duration (primary)" if col==0 else "B  Peak load (secondary)"),loc="left");ax.set_xlabel("LOSO MAE ("+unit+")")
        rows=[r for r in predictions if r["outcome"]==outcome];ax=axes[1,col]
        for y,r in enumerate(rows):
            _plot_interval(ax,y,r["metrics"].get("delta_mae_baseline_minus_augmented"),r["intervals"].get("delta_mae_baseline_minus_augmented"),color)
        def spec_label(row):
            spec=row["analysis"].split("__")[0]
            name="Age replaces height" if spec=="primary_height_replaced_by_age" else spec.replace("_"," ")
            return name+(" †" if row["warnings"] else "")+f" (n={row['n']})"
        ax.axvline(0,color="gray",ls="--",lw=.8);ax.set_yticks(range(len(rows)),[spec_label(r) for r in rows]);ax.invert_yaxis()
        ax.set_title(("C" if col==0 else "D")+"  All fixed predictive configurations",loc="left");ax.set_xlabel("Baseline minus augmented MAE ("+unit+")")
    reps=payload["configuration"].get("executed_bootstrap_replicates","unspecified")
    fig.suptitle(label+f"\nIncremental prediction; approximate bootstrap intervals ({reps} draws); † influence warning",fontsize=12)
    _save_figure(plt,fig,out/"F2_prediction_sensitivity")
    figure_data["F2"]={"panels":["A","B","C","D"],"rows":predictions,"interval_label":"approximate bootstrap sensitivity interval; nominal 95%; real coverage not established"}

    morphology=payload["tables"]["T3"]
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
    plotted=[]
    for col,names in enumerate([MORPHOLOGY_MODELS[:2],MORPHOLOGY_MODELS[2:]]):
        rows=[r for r in morphology if r["analysis"] in names];ax=axes[col]
        for y,r in enumerate(rows):
            c=r.get("coefficient") or {};conv=(lambda x:100*np.expm1(x)) if r.get("outcome_logged") else (lambda x:x)
            est=None if c.get("estimate") is None else float(conv(c["estimate"]))
            hc=None if not c.get("hc3_ci95") else [float(conv(v)) for v in c["hc3_ci95"]]
            bc=None if not c.get("participant_bootstrap_ci95") else [float(conv(v)) for v in c["participant_bootstrap_ci95"]]
            _plot_interval(ax,y+.07,est,bc,"#9bafb8");_plot_interval(ax,y-.07,est,hc)
            plotted.append({"analysis":r["analysis"],"estimate":est,"hc3_ci95":hc,"bootstrap_ci95":bc,"unit":"geometric mean percent" if r.get("outcome_logged") else "degree"})
        ax.axvline(0,color="gray",ls="--",lw=.8);ax.set_yticks(range(len(rows)),[r["analysis"].replace("_"," ") for r in rows]);ax.invert_yaxis()
        ax.set_title(("A  Motion summaries" if col==0 else "B  Pressure outcomes"),loc="left");ax.set_xlabel("Change per +0.01 relative navicular height\n"+("degrees" if col==0 else "conditional geometric mean (%)"))
    fig.suptitle(label+"\nAll five morphology associations; teal: HC3 95%, grey: participant bootstrap 95%",fontsize=12)
    _save_figure(plt,fig,out/"F3_morphology_associations")
    figure_data["F3"]={"panels":["A","B"],"rows":plotted,"intervals":"HC3 and participant bootstrap; all associations retained"}

    fig,axes=plt.subplots(2 if calibration else 1,2,figsize=(12,8.6 if calibration else 4.6),layout="constrained",squeeze=False)
    measurement=payload["tables"]["T4"]
    for y,key in enumerate(["full_pressure_cohort","primary_motion_cohort"]):
        group=measurement.get(key,{});stats=group.get("statistics",{})
        a=stats.get("pooled_within_sd_cm2",{});b=stats.get("first_last_bias_cm2",{})
        low=stats.get("first_last_loa_lower_cm2",{}).get("estimate")
        high=stats.get("first_last_loa_upper_cm2",{}).get("estimate")
        if low is not None and high is not None:axes[0,1].plot([low,high],[y,y],color="#007A87",lw=8,alpha=.18)
        _plot_interval(axes[0,0],y,a.get("estimate"),a.get("bootstrap_ci95"))
        _plot_interval(axes[0,1],y,b.get("estimate"),b.get("bootstrap_ci95"))
    for j,title in enumerate(["A  Within-person effective-area SD","B  Last-minus-first effective area"]):
        ax=axes[0,j];ax.set_title(title,loc="left");ax.set_yticks([0,1],["Full repeaters (n="+str(measurement.get("full_pressure_cohort",{}).get("repeatable_n","unavailable"))+")","Paired-subset repeaters (n="+str(measurement.get("primary_motion_cohort",{}).get("repeatable_n","unavailable"))+")"]);ax.set_ylim(1.5,-.5);ax.set_xlabel("cm²; participant-bootstrap intervals"+("; faint bands: LoA" if j else ""))
        if j==1:ax.axvline(0,color="gray",ls="--",lw=.8)
    if calibration:_calibration_axes(axes[1],calibration)
    cal_config=payload.get("calibration_configuration",{})
    cal_note=(f"; independent calibration: {cal_config.get('datasets','?')} datasets/scenario, {cal_config.get('bootstrap_replicates','?')} draws" if calibration else " (calibration panels not run)")
    fig.suptitle(label+"\nSame-session measurement"+cal_note,fontsize=11)
    _save_figure(plt,fig,out/"F4_measurement_calibration")
    figure_data["F4"]={"panels":["A","B"]+(["C","D"] if calibration else []),"measurement":measurement,"calibration":calibration,"calibration_dataset_kind":"synthetic" if calibration else None,
                        "calibration_status":"computed_supplied_calibration" if calibration else "not_run_no_values_imputed"}
    return figure_data


def write_paper_report(result, directory, *, calibration=None, figures=True):
    """Generate aggregate machine-readable tables, Markdown and optional figures."""
    kind=result.get("input_dataset_kind",result.get("dataset_kind"))
    if kind not in {"synthetic","private_empirical"}:raise ValueError("explicit_input_dataset_kind_required")
    analyses=result.get("analyses",{})
    expected={s+"__"+y for s in PREDICTION_SPECS for y in ["contact_ms","pressure_peak_N"] if not (s=="primary_height_replaced_by_age" and y!="contact_ms")} | set(MORPHOLOGY_MODELS)
    if set(analyses)!=expected:raise ValueError("paper_report_requires_all_22_named_analyses")
    if isinstance(calibration,(str,Path)):calibration=json.loads(Path(calibration).read_text())
    calibration_config=None
    if calibration is not None:
        if calibration.get("schema_version")!=CALIBRATION_VERSION or calibration.get("dataset_kind")!="synthetic":raise ValueError("independent_calibration_result_required")
        calibration_config=calibration.get("configuration",{})
        calibration=calibration["summary"]
    if figures:_matplotlib()
    out=Path(directory)
    if (out/"paper-report.json").exists():
        prior=json.loads((out/"paper-report.json").read_text())
        if prior.get("input_dataset_kind")!=kind:raise ValueError("refuse_overwrite_different_dataset_kind")
    out.mkdir(parents=True,exist_ok=True);table_dir=out/"tables";table_dir.mkdir(exist_ok=True)
    predictions=_prediction_rows(analyses);coefs=_coefficient_rows(analyses)
    morphology=[]
    for name in MORPHOLOGY_MODELS:
        a=analyses[name]
        c=next((c for c in a.get("coefficients",[]) if c.get("term")=="navicular_ratio_per001"),None)
        morphology.append({"analysis":name,"n":a.get("n"),"outcome":a.get("outcome"),"outcome_logged":a.get("outcome_logged"),"status":a.get("status"),"coefficient":c})
    payload={"schema_version":REPORT_VERSION,"input_dataset_kind":kind,"dataset_kind":kind,"exportable":False,
             "notice":"Synthetic values are not empirical paper results." if kind=="synthetic" else "Private empirical aggregates: release is not authorized by generation of this report.",
             "protocol_id":result.get("protocol_id"),"configuration":result.get("configuration",{}),
             "tables":{"T1":result.get("cohort_selection_summary",{}),"T2":predictions,"T3":morphology,"T4":_aggregate_measurement(result.get("measurement_summary",{}))},
             "coefficients":coefs,"calibration_status":"not_run" if calibration is None else "computed_supplied_result",
             "calibration_configuration":calibration_config,"calibration_summary":calibration}
    simple_pred=[]
    for row in predictions:
        simple_pred.append({"dataset_kind":kind,"analysis":row["analysis"],"n":row["n"],"status":row["status"],**row["metrics"],"approx_delta_interval95":row["intervals"].get("delta_mae_baseline_minus_augmented"),"warnings":row["warnings"]})
    cohort=payload["tables"]["T1"]
    sexes=[]
    for row in cohort.get("categorical",[]):
        sex={"recorded_sex":row.get("level")}
        for scope in ["full","selected","not_selected"]:
            n,mean=row.get(scope+"_n"),row.get(scope+"_mean")
            sex[scope+"_count"]=round(n*mean) if n is not None and mean is not None else None
        sexes.append(sex)
    diagnostic_rows=[]
    for model in result.get("numerical_design",{}).get("models",[]):
        d=model.get("bootstrap_loso_training",{})
        diagnostic_rows.append({"analysis":model.get("analysis"),"model":model.get("model"),"matrix_count":d.get("matrix_count"),"rank_deficient_count":d.get("rank_deficient_count"),"condition_above_threshold_count":d.get("condition_above_frozen_threshold_count"),"minimum_distinct_training_participants":model.get("minimum_bootstrap_training_distinct_participants")})
    payload["numerical_diagnostics"]={"status":result.get("numerical_design",{}).get("status","not_run"),"models":diagnostic_rows,"producer_supplied_quality_counts":cohort.get("producer_supplied_quality_counts",{})}
    quality_rows=_quality_count_rows(cohort)
    payload["numerical_diagnostics"]["quality_summary"]=quality_rows
    table_rows={"T1_cohort_profiles":_profile_rows(cohort),"T1_observed_descriptives":cohort.get("observed_descriptives",[]),"T1_recorded_sex_counts":sexes,
                "T2_prediction":[r for r in simple_pred if r["analysis"].startswith("primary__")],"S1_prediction_sensitivity":simple_pred,
                "T3_morphology":morphology,"T4_measurement":_measurement_rows(payload["tables"]["T4"]),"S2_all_coefficients":coefs}
    table_rows["S3_numerical_diagnostics"]=diagnostic_rows
    table_rows["S3_quality_counts"]=quality_rows
    table_rows["S4_calibration"]=[{"dataset_kind":"synthetic",**r} for r in calibration] if calibration is not None else [{"dataset_kind":"synthetic","status":"not_run","reason":"No independently computed calibration was supplied; no values imputed."}]
    for name,rows in table_rows.items():
        labeled=[{"dataset_kind":kind,**r} for r in rows]
        _write_csv(table_dir/(name+".csv"),labeled)
        notice="Independent synthetic calibration; not empirical cohort estimates." if name=="S4_calibration" else payload["notice"]
        context=("\nProducer-supplied fields reproduce upstream bookkeeping; the public package does not independently recheck raw signals. Missing fields remain not_provided. Bundle counts and the separate S3 numerical-design audit describe different levels of evidence.\n" if name=="S3_quality_counts" else "")
        (table_dir/(name+".md")).write_text("# "+name+"\n\n"+notice+"\n\n"+_markdown_table(_display_rows(name,rows))+context)
    if figures:
        fig_dir=out/"figures";fig_dir.mkdir(exist_ok=True)
        payload["figures"]=_figures(payload,fig_dir,calibration)
    else:payload["figures"]={"status":"not_requested"}
    _write_json(out/"paper-report.json",payload)
    _write_json(out/"figure-data.json",payload["figures"])
    (out/"REPORT.md").write_text("# Paper-study report\n\n"+payload["notice"]+"\n\n"
        "All 22 fixed analyses are retained, including unestimable outcomes. Tables and figures share paper-report.json; no raw files or individual profiles are read by the reporting layer.\n\n"
        "- T1/F1 require cohort_profiles; the speed comparison uses subject_median_speed_kmh and never substitutes extension index speed.\n"
        "- [T2 primary comparisons](tables/T2_prediction.md) and [S1 all sensitivities](tables/S1_prediction_sensitivity.md) supply F2. Intervals are approximate bootstrap sensitivity intervals, not calibrated individual prediction intervals.\n"
        "- T3/F3 retain all five morphology associations. Logged coefficients are geometric-mean effects.\n"
        "- T4/F4 A-B use same-session repeat statistics, not biological validation.\n"
        "- F4 C-D are produced only when independently computed calibration is supplied; absent calibration is not filled with empirical or invented values.\n\n"
        "Raw-format adapters remain private or separately licensed. Producing this report does not authorize publication of private empirical data.\n",encoding="utf-8")
    return payload


def build_local_view_payload(bundle, result):
    """Return an explicit local-only whitelist, separate from export-web.

    A browser may show this JSON only after an intentional file selection and
    keep it in memory. Generation never grants permission for public hosting.
    """
    from .paper_bundle import validate_paper_bundle
    from .schema import UNITS
    normalized=validate_paper_bundle({k:v for k,v in bundle.items() if k!="validation"})
    kind=normalized["metadata"]["dataset_kind"]
    if result.get("input_dataset_kind")!=kind:raise ValueError("local_view_dataset_kind_mismatch")
    expected={s+"__"+y for s in PREDICTION_SPECS for y in ["contact_ms","pressure_peak_N"] if not (s=="primary_height_replaced_by_age" and y!="contact_ms")} | set(MORPHOLOGY_MODELS)
    if set(result.get("analyses",{}))!=expected:raise ValueError("local_view_requires_22_analyses")
    analyses={}
    coef_keys=("term","estimate","hc3_se","hc3_ci95","hc3_ci90","participant_bootstrap_ci95","conditional_geometric_mean_ratio","geometric_ratio_hc3_ci95")
    for name,a in result["analyses"].items():
        item={k:a[k] for k in ["analysis","outcome","n","input_n","status","controls","strategy_terms","terms","outcome_logged","cv_metrics","cv_metric_bootstrap_ci95"] if k in a}
        for key in ["baseline_coefficients","augmented_coefficients","coefficients"]:
            if key in a:item[key]=[{k:c[k] for k in coef_keys if k in c} for c in a[key]]
        for key in ["baseline_diagnostics","augmented_diagnostics","diagnostics"]:
            if key in a:item[key]={k:a[key][k] for k in ["rank","n_parameters","residual_df","standardized_design_condition_number","max_leverage","interpretation_gate_passed"] if k in a[key]}
        if "cv_predictions" in a:
            item["predictions"]=[{"participant_id":r.get("participant_id",r.get("anonymized_id")),**{k:r[k] for k in ["observed","mean_prediction","baseline_prediction","augmented_prediction"] if k in r}} for r in a["cv_predictions"]]
        analyses[name]=item
    payload={"schema_version":"scm-strategy.local-study/1","dataset_kind":kind,"local_only":True,"exportable":False,"upload_allowed":False,
             "notice":"LOCAL FILE VIEW ONLY. Contains individual standardized data. Do not upload or publish. Not medical advice or evidence of causal adaptation.",
             "protocol_id":result.get("protocol_id"),"units":dict(UNITS),
             "primary_participants":[{k:r[k] for k in ["participant_id",*UNITS,"qc_status"]} for r in normalized["primary"]],
             "analyses":analyses,"measurement_summary":_aggregate_measurement(result.get("measurement_summary",{})),
             "cohort_selection_summary":result.get("cohort_selection_summary",{})}
    config_keys=("seed","bootstrap_replicates","executed_bootstrap_replicates","full_frozen_draw_count",
                 "minimum_main_participants","maximum_standardized_design_condition_number","case_speed_caliper_kmh","window_seconds")
    payload["configuration"]={k:result["configuration"][k] for k in config_keys if k in result.get("configuration",{})}
    serialized=json.dumps(_safe(payload),allow_nan=False)
    if re_search_external(serialized):raise ValueError("external_link_or_path_in_local_payload")
    return _safe(payload)


def re_search_external(text):
    import re
    return re.search(r"(?:https?|file|ftp)://|/Users/|/Volumes/|[A-Za-z]:\\\\",text) is not None


def write_local_view(bundle, result, path):
    payload=build_local_view_payload(bundle,result)
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    _write_json(target,payload)
    return payload


def calibration_configuration(*,datasets=100,bootstrap_replicates=200,mc_training_sets=20000,mc_test_people=1000,seed=73104261):
    for key,value,minval in [("datasets",datasets,2),("bootstrap_replicates",bootstrap_replicates,10),("mc_training_sets",mc_training_sets,2),("mc_test_people",mc_test_people,1)]:
        if isinstance(value,bool) or not isinstance(value,int) or value<minval:raise ValueError(key+"_below_valid_minimum")
    if isinstance(seed,bool) or not isinstance(seed,int) or seed<0:raise ValueError("invalid_seed")
    return {"datasets":datasets,"bootstrap_replicates":bootstrap_replicates,"mc_training_sets":mc_training_sets,"mc_test_people":mc_test_people,"seed":seed,
            "n_observed":25,"n_target_train":24,"rho":.30,"intercept":math.log(200),"control_coefficients":[-.18,.10],"log_error_sd":.20,
            "scenarios":[{"name":"null_increment","strategy_coefficients":[0.,0.]},{"name":"moderate_increment","strategy_coefficients":[.12,-.12]}],
            "matches_full_paper_calibration_sizes":datasets==100 and bootstrap_replicates==200 and mc_training_sets==20000 and mc_test_people==1000,
            "dgp_notice":"Fixed Gaussian/lognormal calibration; distinct from the paper-demo cohort equations. No empirical fits or stored results."}


def _calibration_draw(rng, shape, config, scenario):
    cov=(1-config["rho"])*np.eye(4)+config["rho"]*np.ones((4,4))
    z=rng.standard_normal(shape+(4,)) @ np.linalg.cholesky(cov).T
    beta=np.array(config["control_coefficients"]+scenario["strategy_coefficients"])
    y=np.exp(config["intercept"]+z@beta+rng.normal(0,config["log_error_sd"],shape))
    x=np.concatenate([np.ones(shape+(1,)),z],axis=-1)
    return y,x[...,:3],x


def _reference_fit(x,y):
    xy=np.einsum("...ni,...n->...i",x,y)
    beta=np.linalg.solve(np.einsum("...ni,...nj->...ij",x,x),xy[...,None])[...,0]
    residual=y-np.einsum("...ni,...i->...n",x,beta)
    return beta,np.exp(residual).mean(axis=-1)


def _mc_target(config,scenario,index):
    rng=np.random.default_rng(config["seed"]+1000000+index);errors=[]
    for start in range(0,config["mc_training_sets"],100):
        n=min(100,config["mc_training_sets"]-start)
        y,x0,x1=_calibration_draw(rng,(n,24),config,scenario)
        b0,s0=_reference_fit(x0,np.log(y));b1,s1=_reference_fit(x1,np.log(y))
        test,t0,t1=_calibration_draw(rng,(n,config["mc_test_people"]),config,scenario)
        e0=abs(test-np.exp(np.einsum("rki,ri->rk",t0,b0))*s0[:,None])
        e1=abs(test-np.exp(np.einsum("rki,ri->rk",t1,b1))*s1[:,None])
        errors.extend(np.column_stack([e0.mean(1),e1.mean(1),(e0-e1).mean(1)]))
    errors=np.asarray(errors);mean=errors.mean(0);se=errors[:,2].std(ddof=1)/math.sqrt(len(errors))
    return {"scenario":scenario["name"],"n_train":config["n_target_train"],"mc_training_sets":config["mc_training_sets"],"test_people_per_training_set":config["mc_test_people"],"target_delta_mae":float(mean[2]),"target_mc_se":float(se),"target_mc_ci95":[float(mean[2]-1.96*se),float(mean[2]+1.96*se)],"baseline_mae":float(mean[0]),"augmented_mae":float(mean[1])}


def _calibration_job(args):
    config,si,di=args;scenario=config["scenarios"][si]
    y,x0,x1=_calibration_draw(np.random.default_rng(config["seed"]+si*10000+di),(25,),config,scenario)
    ids=[f"CAL-{i:02d}" for i in range(25)]
    point=loso(y,x0,x1,ids)["metrics"]["delta_mae_baseline_minus_augmented"]
    boot=bootstrap_analysis(y,x0,x1,ids,config["bootstrap_replicates"],config["seed"]+2000000+si*10000+di)
    values=np.array([r["delta_mae_baseline_minus_augmented"] for r in boot["metrics"]])
    interval=percentile_interval(values,.95)
    return {"scenario":scenario["name"],"dataset_index":di,"point_delta_mae":point,"interval_lower":None if interval is None else interval[0],"interval_upper":None if interval is None else interval[1],"interval_center":None if interval is None else .5*sum(interval),"bootstrap_valid":boot["valid"],"bootstrap_failures":sum(boot["failures"].values()),"mean_distinct_ids":float(np.mean(boot["bootstrap_distinct_participants"]))}


def _wilson(k,n):
    z=NormalDist().inv_cdf(.975);p=k/n;den=1+z*z/n
    mid=(p+z*z/(2*n))/den;radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [mid-radius,mid+radius]


def _calibration_axes(axes,summary):
    from matplotlib.lines import Line2D
    for y,s in enumerate(summary):
        _plot_interval(axes[0],y,100*s["coverage"],[100*v for v in s["coverage_wilson_ci95"]],"#17374a")
        for off,key,color in [(-.08,"interval_center","#17374a"),(.08,"point_estimate","#BB6225")]:
            _plot_interval(axes[1],y+off,s[key+"_bias"],s[key+"_bias_mc_ci95"],color)
    for ax in axes:ax.set_yticks(range(len(summary)),[s["scenario"] for s in summary]);ax.invert_yaxis()
    axes[0].axvline(95,color="gray",ls="--",lw=.8);axes[0].set_title("C  Synthetic coverage; Wilson intervals",loc="left");axes[0].set_xlabel("Percent of simulated datasets")
    axes[1].axvline(0,color="gray",ls="--",lw=.8);axes[1].set_title("D  Interval-center / point-estimate bias",loc="left");axes[1].set_xlabel("Synthetic response units; Monte Carlo intervals")
    axes[1].legend(handles=[Line2D([0],[0],color="#17374a",marker="o",label="Interval center"),Line2D([0],[0],color="#BB6225",marker="o",label="LOSO point")],fontsize=8,frameon=False)


def run_calibration(directory, *, datasets=100, bootstrap_replicates=200, mc_training_sets=20000, mc_test_people=1000, seed=73104261, workers=2, figures=True, progress=None):
    """Actually run the fixed independent calibration; never load manuscript values."""
    config=calibration_configuration(datasets=datasets,bootstrap_replicates=bootstrap_replicates,mc_training_sets=mc_training_sets,mc_test_people=mc_test_people,seed=seed)
    if isinstance(workers,bool) or not isinstance(workers,int) or workers<1:raise ValueError("invalid_workers")
    if figures:_matplotlib()
    targets=[_mc_target(config,s,i) for i,s in enumerate(config["scenarios"])]
    jobs=[(config,si,di) for si in range(2) for di in range(datasets)]
    if workers==1:rows=[_calibration_job(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:rows=list(pool.map(_calibration_job,jobs))
    summary=[]
    for target in targets:
        used=[r for r in rows if r["scenario"]==target["scenario"] and r["interval_center"] is not None]
        if len(used)<2:raise RuntimeError("insufficient_valid_calibration_intervals")
        truth=target["target_delta_mae"];covered=sum(r["interval_lower"]<=truth<=r["interval_upper"] for r in used);n=len(used)
        item={**target,"datasets_requested":datasets,"datasets_with_interval":n,"coverage_count":covered,"coverage":covered/n,"coverage_mc_se":math.sqrt((covered/n)*(1-covered/n)/n),"coverage_wilson_ci95":_wilson(covered,n),"mean_interval_width":float(np.mean([r["interval_upper"]-r["interval_lower"] for r in used])),"mean_bootstrap_unique_ids":float(np.mean([r["mean_distinct_ids"] for r in used])),"all_bootstrap_failures":sum(r["bootstrap_failures"] for r in used)}
        target_low,target_high=target["target_mc_ci95"]
        item["coverage_contains_entire_target_mc_ci_count"]=sum(r["interval_lower"]<=target_low and target_high<=r["interval_upper"] for r in used)
        item["coverage_intersects_target_mc_ci_count"]=sum(r["interval_lower"]<=target_high and target_low<=r["interval_upper"] for r in used)
        for name,col in [("interval_center","interval_center"),("point_estimate","point_delta_mae")]:
            bias=np.array([r[col]-truth for r in used]);dataset_se=float(bias.std(ddof=1)/math.sqrt(n));se=math.hypot(dataset_se,target["target_mc_se"])
            item[name+"_bias_dataset_mc_se"]=dataset_se
            item[name+"_bias"]=float(bias.mean());item[name+"_bias_total_mc_se"]=se;item[name+"_bias_mc_ci95"]=[float(bias.mean()-1.96*se),float(bias.mean()+1.96*se)]
        summary.append(item)
    out=Path(directory);out.mkdir(parents=True,exist_ok=True)
    result={"schema_version":CALIBRATION_VERSION,"dataset_kind":"synthetic","configuration":config,"summary":summary,"exportable":False,
            "notice":"Independent calibration only. Synthetic target units are not empirical paper estimates; favorable coverage does not validate empirical coverage."}
    _write_json(out/"calibration.json",result);_write_csv(out/"calibration_datasets.csv",rows);_write_csv(out/"calibration_summary.csv",summary)
    if figures:
        plt=_matplotlib();fig,axes=plt.subplots(1,2,figsize=(12,4.6),layout="constrained");_calibration_axes(axes,summary)
        fig.suptitle("INDEPENDENT SYNTHETIC CALIBRATION - ACTUALLY COMPUTED\n"+str(datasets)+" datasets per scenario; "+str(bootstrap_replicates)+" resamples each",fontsize=11)
        _save_figure(plt,fig,out/"F4_calibration_panels")
    (out/"README.md").write_text("# Independent calibration\n\n"+result["notice"]+"\n\n"+_markdown_table(summary)+"\nThe fixed full-size procedure uses 100 datasets per scenario, 200 bootstrap resamples, 20,000 independent training sets of 24, and 1,000 independent test people per training set. Reduced runs are smoke tests, not full calibration. Null strategy coefficients do not imply zero expected error difference for two finite-sample fitting algorithms.\n",encoding="utf-8")
    if progress:progress(len(jobs),len(jobs))
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest="command",required=True)
    c=sub.add_parser("calibrate",help="Run the fixed independent Gaussian/lognormal calibration")
    c.add_argument("--out",type=Path,required=True);c.add_argument("--datasets",type=int,default=100);c.add_argument("--bootstrap",type=int,default=200)
    c.add_argument("--mc-training",type=int,default=20000);c.add_argument("--mc-test",type=int,default=1000);c.add_argument("--seed",type=int,default=73104261);c.add_argument("--workers",type=int,default=2);c.add_argument("--no-figures",action="store_true")
    a=parser.parse_args(argv)
    result=run_calibration(a.out,datasets=a.datasets,bootstrap_replicates=a.bootstrap,mc_training_sets=a.mc_training,mc_test_people=a.mc_test,seed=a.seed,workers=a.workers,figures=not a.no_figures)
    print(json.dumps({"output":str(a.out),"full_configuration":result["configuration"]["matches_full_paper_calibration_sizes"],"scenarios":len(result["summary"])}))


if __name__=="__main__":main()
