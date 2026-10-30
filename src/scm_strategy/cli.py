# SPDX-License-Identifier: BSD-3-Clause
"""Local CLI; no network, upload or automatic publication."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from . import __version__
from .analysis import analyze
from .export import export_web
from .schema import read_table,write_table,canonical_csv
from .synthetic import generate
from .paper_bundle import read_paper_bundle
from .paper_study import run_paper_study,save_paper_study


def save_run(records,metadata,output,kind,bootstraps,seed):
    result=analyze(records,metadata,dataset_kind=kind,bootstrap_replicates=bootstraps,seed=seed)
    root=Path(output)
    root.mkdir(parents=True,exist_ok=True)
    write_table(records,metadata,root/"participants.csv",root/"metadata.json")
    (root/"analysis.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    manifest={"package_version":__version__,"dataset_kind":kind,"n_participants":len(records),
              "configuration":result["configuration"],
              "input_sha256":hashlib.sha256(canonical_csv(records).encode()).hexdigest(),
              "privacy":"Private runs and input hashes stay local; export-web only reconstructs verified synthetic data."}
    (root/"run_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    return result


def parser():
    root=argparse.ArgumentParser(prog="scm-strategy",description="Explicit-unit participant analysis and independent synthetic demonstrations")
    root.add_argument("--version",action="version",version=__version__)
    sub=root.add_subparsers(dest="command",required=True)
    validate=sub.add_parser("validate",help="validate a participant CSV and its mandatory metadata")
    validate.add_argument("csv")
    validate.add_argument("--metadata",required=True)
    analysis=sub.add_parser("analyze",help="analyze local standardized data; private_empirical by default")
    analysis.add_argument("csv");analysis.add_argument("--metadata",required=True);analysis.add_argument("--out",required=True)
    analysis.add_argument("--dataset-kind",choices=["private_empirical","synthetic"],default="private_empirical")
    analysis.add_argument("--bootstrap",type=int,default=2000);analysis.add_argument("--seed",type=int,default=20261030)
    demo=sub.add_parser("demo",help="generate from fixed independent equations and run the same analysis")
    demo.add_argument("--out",required=True);demo.add_argument("--participants",type=int,default=60)
    demo.add_argument("--seed",type=int,default=20261030);demo.add_argument("--bootstrap",type=int,default=2000)
    export=sub.add_parser("export-web",help="reconstruct a verified synthetic run through the public JSON whitelist")
    export.add_argument("run_directory");export.add_argument("--out",required=True)
    paper=sub.add_parser("paper-study",help="reproduce the full frozen paper analysis from a private standardized multi-table bundle")
    paper.add_argument("bundle_directory");paper.add_argument("--out",required=True)
    paper.add_argument("--bootstrap",type=int,default=None,help="smaller counts only for explicitly synthetic verification")
    paper.add_argument("--skip-design-audit",action="store_true",help="label fold audit as not run; do not imply a complete diagnostic artifact")
    paper.add_argument("--report",action="store_true",help="also render paper tables/figures; requires the paper extra")
    paper.add_argument("--calibration",help="optional independently computed calibration JSON for the paper report")
    paper.add_argument("--local-view",help="optional private local-view payload; never a public web export")
    paperdemo=sub.add_parser("paper-demo",help="generate a full independent synthetic bundle and run the paper workflow")
    paperdemo.add_argument("--out",required=True);paperdemo.add_argument("--participants",type=int,default=50)
    paperdemo.add_argument("--primary-participants",type=int,default=25);paperdemo.add_argument("--seed",type=int,default=20261030)
    paperdemo.add_argument("--bootstrap",type=int,default=None);paperdemo.add_argument("--skip-design-audit",action="store_true")
    paperdemo.add_argument("--report",action="store_true")
    paperdemo.add_argument("--calibration")
    paperdemo.add_argument("--local-view")
    pattern=sub.add_parser("pattern-study",help="run the exploratory pattern and bilateral-pressure workflow from standardized numeric arrays")
    pattern.add_argument("bundle_directory");pattern.add_argument("--out",required=True)
    pattern.add_argument("--bootstrap",type=int,default=None);pattern.add_argument("--permutations",type=int,default=None)
    pattern.add_argument("--local-view",help="local-only display JSON, with bounded display trajectories")
    patterndemo=sub.add_parser("pattern-demo",help="generate independent synthetic arrays and run the complete pattern workflow")
    patterndemo.add_argument("--out",required=True);patterndemo.add_argument("--participants",type=int,default=50)
    patterndemo.add_argument("--primary-participants",type=int,default=25);patterndemo.add_argument("--seed",type=int,default=20261030)
    patterndemo.add_argument("--bootstrap",type=int,default=None);patterndemo.add_argument("--permutations",type=int,default=None)
    patterndemo.add_argument("--local-view",help="local-only display JSON; synthetic output may be used as an explicit demo")
    return root


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.command=="validate":
            records,metadata=read_table(args.csv,args.metadata)
            response={"valid":True,"participants":len(records),"dataset_kind":metadata["dataset_kind"]}
        elif args.command=="demo":
            records,metadata=generate(args.participants,args.seed)
            result=save_run(records,metadata,args.out,"synthetic",args.bootstrap,args.seed)
            response={"dataset_kind":"synthetic","participants":len(records),"analysis_version":result["analysis_version"]}
        elif args.command=="analyze":
            records,metadata=read_table(args.csv,args.metadata)
            result=save_run(records,metadata,args.out,args.dataset_kind,args.bootstrap,args.seed)
            response={"dataset_kind":args.dataset_kind,"participants":len(records),"analysis_version":result["analysis_version"]}
        elif args.command in {"paper-study","paper-demo"}:
            if args.command=="paper-demo":
                from .paper_synthetic import generate_paper_bundle
                from .paper_bundle import write_paper_bundle
                bundle=generate_paper_bundle(total_participants=args.participants,primary_participants=args.primary_participants,seed=args.seed)
                write_paper_bundle(bundle,Path(args.out)/"input_bundle")
            else:bundle=read_paper_bundle(args.bundle_directory)
            result=run_paper_study(bundle,bootstrap_replicates=args.bootstrap,include_design_audit=not args.skip_design_audit)
            save_paper_study(result,args.out)
            if args.local_view:
                from .paper_report import write_local_view
                write_local_view(bundle,result,args.local_view)
            if args.report:
                try:
                    from .paper_report import write_paper_report
                    write_paper_report(result,args.out,calibration=args.calibration)
                except ModuleNotFoundError as error:
                    raise ValueError("paper_report_requires_installation_with_paper_extra: install scm-strategy[paper] (or use uv sync --extra paper)") from error
            response={"analysis_mode":"paper-study","dataset_kind":"private_empirical","input_dataset_kind":result["input_dataset_kind"],
                      "analyses":len(result["analyses"]),"protocol_id":result["protocol_id"],"exportable":False,
                      "full_frozen_draw_count":result["configuration"]["full_frozen_draw_count"]}
        elif args.command in {"pattern-study","pattern-demo"}:
            from .pattern_bundle import read_pattern_bundle,write_pattern_bundle
            from .pattern_study import run_pattern_study,save_pattern_study
            if args.command=="pattern-demo":
                from .pattern_synthetic import generate_pattern_bundle
                bundle=generate_pattern_bundle(args.participants,args.primary_participants,args.seed)
                write_pattern_bundle(bundle,Path(args.out)/"input_bundle")
            else:
                bundle=read_pattern_bundle(args.bundle_directory)
            result=run_pattern_study(bundle,bootstrap_replicates=args.bootstrap,permutations=args.permutations)
            save_pattern_study(result,args.out)
            if args.local_view:
                from .pattern_view import write_pattern_view
                write_pattern_view(bundle,result,args.local_view)
            response={"analysis_mode":"pattern-study","dataset_kind":result["dataset_kind"],"exportable":False,
                      "counts":result["counts"],"static_models":len(result["static_bilateral"]["models"]),"motion_models":len(result["motion_bilateral"]["models"])}
        else:
            payload=export_web(args.run_directory,args.out)
            response={"dataset_kind":payload["dataset_kind"],"schema_version":payload["schema_version"],"records":len(payload["records"])}
        print(json.dumps(response,allow_nan=False))
        return 0
    except (ValueError,OSError,KeyError,RuntimeError,json.JSONDecodeError) as error:
        # Error type and reason only; never dump raw rows or full tracebacks.
        print(json.dumps({"error":type(error).__name__,"reason":str(error)}),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
