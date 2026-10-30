"""The scanner distinguishes policy constants from named private paths."""
from pathlib import Path
import importlib.util
import re


def test_private_path_scan_preserves_policy_constants_but_rejects_named_paths():
    source=Path(__file__).resolve().parents[1]/'tools/audit_release.py'
    spec=importlib.util.spec_from_file_location('release_audit_under_test',source)
    audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
    pattern=audit.PRIVATE_PATH_PATTERN
    roots=['/'+'Users'+'/', '/'+'home'+'/', '/'+'Volumes'+'/']
    for root in roots:
        assert re.search(pattern,root) is None
        assert re.search(pattern,'"'+root+'"') is None
        assert re.search(pattern,root+'example/data.csv') is not None
        assert re.search(pattern,root+'研究员/data.csv') is not None
    policy='(?:https?|file|ftp)://|'+roots[0]+'|'+roots[2]+'|'
    assert re.search(pattern,policy) is None
