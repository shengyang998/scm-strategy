import json
from pathlib import Path
import subprocess
import sys
import pytest
from scm_strategy.analysis import analyze
from scm_strategy.cli import main,save_run
from scm_strategy.export import export_payload
from scm_strategy.schema import validate_records,SchemaError,read_table
from scm_strategy.synthetic import generate,verify_recipe


def test_reject_missing_id_unit_duplicate_and_extra_fields():
    rows,meta=generate(30,42)
    bad=[dict(r) for r in rows];del bad[0]["participant_id"]
    with pytest.raises(SchemaError):validate_records(bad,meta)
    bad_meta={**meta,"units":{**meta["units"],"height_cm":"m"}}
    with pytest.raises(SchemaError,match="unit"):validate_records(rows,bad_meta)
    bad=[dict(r) for r in rows];bad[1]["participant_id"]=bad[0]["participant_id"]
    with pytest.raises(SchemaError,match="duplicate"):validate_records(bad,meta)
    bad=[dict(r) for r in rows];bad[0]["unapproved_field"]="private"
    with pytest.raises(SchemaError):validate_records(bad,meta)


def test_synthetic_end_to_end_and_public_whitelist(tmp_path):
    run=tmp_path/"run";web=tmp_path/"web.json"
    assert main(["demo","--out",str(run),"--participants","30","--seed","42","--bootstrap","12"])==0
    assert main(["validate",str(run/"participants.csv"),"--metadata",str(run/"metadata.json")])==0
    # Unapproved fields in stored results or metadata never flow into public JSON.
    result=json.loads((run/"analysis.json").read_text());result["private_marker"]="DO_NOT_EXPORT"
    (run/"analysis.json").write_text(json.dumps(result))
    meta=json.loads((run/"metadata.json").read_text());meta["private_marker"]="DO_NOT_EXPORT"
    (run/"metadata.json").write_text(json.dumps(meta))
    assert main(["export-web",str(run),"--out",str(web)])==0
    payload=json.loads(web.read_text())
    assert "DO_NOT_EXPORT" not in web.read_text()
    assert payload["dataset_kind"]=="synthetic" and len(payload["records"])==30
    assert set(payload)=={"schema_version","dataset_kind","generator","units","records","analysis","disclaimer"}
    assert "input_sha256" not in web.read_text()


def test_private_export_and_forged_synthetic_relabel_rejected(tmp_path):
    rows,meta=generate(30,21)
    rows[0]["height_cm"]+=1
    run=tmp_path/"private"
    save_run(rows,meta,run,"private_empirical",12,21)
    with pytest.raises(SchemaError,match="synthetic"):export_payload(run)
    manifest=json.loads((run/"run_manifest.json").read_text());manifest["dataset_kind"]="synthetic"
    (run/"run_manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(SchemaError,match="recipe"):export_payload(run)


def test_analyze_defaults_private_even_for_synthetic_inputs(tmp_path):
    run=tmp_path/"demo"
    main(["demo","--out",str(run),"--participants","30","--bootstrap","10"])
    target=tmp_path/"default"
    assert main(["analyze",str(run/"participants.csv"),"--metadata",str(run/"metadata.json"),"--out",str(target),"--bootstrap","10"])==0
    assert json.loads((target/"run_manifest.json").read_text())["dataset_kind"]=="private_empirical"


def test_import_does_not_read_configuration():
    code='''
import numpy, scipy.stats
from pathlib import Path
def reject(*args, **kwargs):
    raise AssertionError("import-time configuration read")
Path.read_text = reject
import scm_strategy.features, scm_strategy.schema, scm_strategy.synthetic
import scm_strategy.statistics, scm_strategy.analysis
'''
    subprocess.run([sys.executable,"-c",code],check=True,capture_output=True,text=True)


def test_reproducible_generator_and_analysis():
    first,meta=generate(30,7);second,other=generate(30,7)
    assert first==second and meta==other
    assert verify_recipe(first,meta)==first
    a=analyze(first,meta,dataset_kind="synthetic",bootstrap_replicates=12,seed=7)
    b=analyze(second,other,dataset_kind="synthetic",bootstrap_replicates=12,seed=7)
    assert a==b
