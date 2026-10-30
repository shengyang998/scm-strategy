"""Source/wheel disclosure checks; run from any directory, no private imports."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile
import tomllib
import zipfile

PRIVATE_PATH_PATTERN = r"/(?:Users|home|Volumes)/[\w.-]"


def audit(root,wheel=None,sdist=None):
    allowed=[x for x in (root/"release_allowlist.txt").read_text().splitlines() if x and not x.startswith("#")]
    problems=[];files=[]
    if len(allowed)!=len(set(allowed)) or any(x.endswith("/") for x in allowed):
        problems.append({"reason":"allowlist_must_be_unique_explicit_files"})
    for relative in allowed:
        if not (root/relative).is_file():problems.append({"file":relative,"reason":"missing_allowlisted_file"})
    project=tomllib.loads((root/"pyproject.toml").read_text())
    version=project["project"]["version"]
    source_include=project["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    if set(source_include)!=set(allowed):problems.append({"reason":"sdist_includes_differ_from_explicit_allowlist"})
    root_license=(root/"LICENSE").read_bytes()
    if b"BSD 3-Clause License" not in root_license or project["project"].get("license")!="BSD-3-Clause":
        problems.append({"reason":"missing_or_inconsistent_project_license"})
    for path in sorted(root.rglob("*")):
        if not path.is_file():continue
        rel=path.relative_to(root).as_posix()
        if rel=="publishing_audit.json":continue
        if rel not in allowed:
            problems.append({"file":rel,"reason":"outside_explicit_source_allowlist"})
        if path.is_symlink() or any(part in {"__pycache__",".venv",".git",".pytest_cache","node_modules"} for part in path.parts) or path.suffix in {".pyc",".log",".pkl",".pickle",".sqlite",".parquet",".mot",".trc",".stl"}:
            problems.append({"file":rel,"reason":"forbidden_generated_or_unknown_source"})
        raw=path.read_bytes()
        text=raw.decode("utf-8",errors="replace")
        for label,pattern in [("absolute_private_path",PRIVATE_PATH_PATTERN),("empirical_identifier",r"\bP\d{6}\b"),
                              ("private_reader_import",r"(?:from|import)\s+readers\b")]:
            if re.search(pattern,text):problems.append({"file":rel,"reason":label})
        files.append({"path":rel,"sha256":hashlib.sha256(raw).hexdigest()})
    wheel_result=None
    if wheel:
        with zipfile.ZipFile(wheel) as archive:
            names=archive.namelist()
            denied=[n for n in names if not (n.startswith("scm_strategy/") or ".dist-info/" in n) or ".." in Path(n).parts or n.endswith(".pyc")]
            wheel_result={"filename":Path(wheel).name,"files":names,"unexpected_members":denied}
            if denied:problems.append({"reason":"unexpected_wheel_members"})
            license_names=[n for n in names if n.endswith(".dist-info/licenses/LICENSE")]
            if len(license_names)!=1 or archive.read(license_names[0])!=root_license:
                problems.append({"reason":"wheel_license_missing_or_changed"})
            if "scm_strategy/THIRD_PARTY_NOTICES.md" not in names:
                problems.append({"reason":"wheel_third_party_notice_missing"})
            for required in ["scm_strategy/paper_study.py","scm_strategy/paper_report.py","scm_strategy/paper_bundle.py",
                             "scm_strategy/protocols/paper_v1.json","scm_strategy/protocols/paper-bundle-v1.schema.json",
                             "scm_strategy/pattern_study.py","scm_strategy/pattern_bundle.py","scm_strategy/pattern_math.py",
                             "scm_strategy/pattern_synthetic.py","scm_strategy/protocols/pattern_v1.json",
                             "scm_strategy/protocols/pattern-bundle-v1.schema.json"]:
                if required not in names:problems.append({"file":required,"reason":"wheel_paper_resource_missing"})
            metadata_names=[n for n in names if n.endswith(".dist-info/METADATA")]
            if len(metadata_names)!=1 or f"Version: {version}\n" not in archive.read(metadata_names[0]).decode():
                problems.append({"reason":"wheel_version_mismatch"})
            for name in names:
                text=archive.read(name).decode("utf-8",errors="replace")
                if re.search(PRIVATE_PATH_PATTERN+r"|\bP\d{6}\b|(?:from|import)\s+readers\b",text):
                    problems.append({"file":name,"reason":"wheel_private_content_pattern"})
    sdist_result=None
    if sdist:
        with tarfile.open(sdist,"r:gz") as archive:
            members=archive.getmembers();seen=[]
            for member in members:
                if member.isdir():continue
                parts=Path(member.name).parts
                relative=Path(*parts[1:]).as_posix()
                seen.append(relative)
                if not member.isfile() or ".." in parts or relative not in {*allowed,"PKG-INFO"}:
                    problems.append({"file":relative,"reason":"unexpected_sdist_member"});continue
                contents=archive.extractfile(member).read()
                if relative!="PKG-INFO" and contents!=(root/relative).read_bytes():
                    problems.append({"file":relative,"reason":"sdist_source_bytes_mismatch"})
                text=contents.decode("utf-8",errors="replace")
                if re.search(PRIVATE_PATH_PATTERN+r"|\bP\d{6}\b|(?:from|import)\s+readers\b",text):
                    problems.append({"file":relative,"reason":"sdist_private_content_pattern"})
            for relative in set(allowed)-set(seen):problems.append({"file":relative,"reason":"sdist_missing_allowlisted_file"})
            sdist_result={"filename":Path(sdist).name,"files":sorted(seen),"matches_explicit_source_allowlist":set(seen)=={*allowed,"PKG-INFO"}}
    return {"status":"passed" if not problems else "failed","version":version,"publication_performed":False,
            "scope":"Explicit source tree, wheel and source archive; known-private catalog and synthetic provenance checks may be appended externally.",
            "files":files,"wheel":wheel_result,"sdist":sdist_result,"issues":problems,
            "license_scope":"BSD-3-Clause for new contributions only; authorship and public citation metadata remain to be confirmed."}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--wheel");parser.add_argument("--sdist");parser.add_argument("--report",default="publishing_audit.json")
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    result=audit(root,args.wheel,args.sdist)
    (root/args.report).write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"status":result["status"],"files":len(result["files"]),"issues":result["issues"]}))
    raise SystemExit(0 if result["status"]=="passed" else 1)


if __name__=="__main__":main()
