"""Generate public schemas and an independent synthetic input example."""
from pathlib import Path
import json
from scm_strategy.schema import FIELDS,UNITS,SCHEMA_VERSION,write_table
from scm_strategy.synthetic import generate,GENERATOR_VERSION


def main():
    root=Path(__file__).resolve().parents[1]
    number={"type":"number","exclusiveMinimum":0}
    record={"type":"object","additionalProperties":False,"required":FIELDS,
            "properties":{"participant_id":{"type":"string","pattern":"^[A-Za-z0-9_-]{1,64}$"},**{k:number for k in UNITS}}}
    generator={"type":"object","additionalProperties":False,"required":["version","seed","parameters"],
               "properties":{"version":{"const":GENERATOR_VERSION},"seed":{"type":"integer","minimum":0},
                             "parameters":{"type":"object","additionalProperties":False,"required":["participants"],
                                           "properties":{"participants":{"type":"integer","minimum":20,"maximum":10000}}}}}
    metadata={"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object",
              "required":["schema_version","dataset_kind","units"],
              "properties":{"schema_version":{"const":SCHEMA_VERSION},"dataset_kind":{"enum":["synthetic","private_empirical"]},
                            "units":{"const":UNITS},"generator":generator}}
    interval={"anyOf":[{"type":"null"},{"type":"array","minItems":2,"maxItems":2,"items":{"type":"number"}}]}
    coefficient={"type":"object","additionalProperties":False,"required":["term","estimate","hc3_ci95","bootstrap_ci95"],
                 "properties":{"term":{"type":"string"},"estimate":{"type":"number"},"hc3_ci95":interval,"bootstrap_ci95":interval}}
    prediction={"type":"object","additionalProperties":False,"required":["participant_id","observed","baseline_prediction","augmented_prediction"],
                "properties":{"participant_id":{"type":"string","pattern":"^SYN-[0-9]{5}$"},
                              **{k:{"type":"number"} for k in ["observed","baseline_prediction","augmented_prediction"]}}}
    metrics=[f"{name}_{measure}" for name in ["mean","baseline","augmented"] for measure in ["mae","rmse"]]+["delta_mae_baseline_minus_augmented"]
    outcome={"type":"object","additionalProperties":False,"required":["unit","cross_validation","delta_mae_bootstrap_ci95","coefficients","predictions"],
             "properties":{"unit":{"enum":["ms","N"]},"cross_validation":{"type":"object","additionalProperties":False,"required":metrics,
                              "properties":{k:{"type":"number"} for k in metrics}},"delta_mae_bootstrap_ci95":interval,
                           "coefficients":{"type":"array","items":coefficient},"predictions":{"type":"array","items":prediction}}}
    web={"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","additionalProperties":False,
         "required":["schema_version","dataset_kind","generator","units","records","analysis","disclaimer"],
         "properties":{"schema_version":{"const":"scm-strategy.web/1"},"dataset_kind":{"const":"synthetic"},
                       "generator":generator,"units":{"const":UNITS},"records":{"type":"array","items":record},
                       "analysis":{"type":"object","additionalProperties":False,"required":["contact_ms","pressure_peak_N"],
                                   "properties":{"contact_ms":outcome,"pressure_peak_N":outcome}},"disclaimer":{"type":"string"}}}
    for name,value in [("participant-record-v1.schema.json",record),("metadata-v1.schema.json",metadata),("web-v1.schema.json",web)]:
        (root/"schemas"/name).write_text(json.dumps(value,indent=2)+"\n")
    rows,meta=generate(30,42)
    write_table(rows,meta,root/"examples/synthetic/participants.csv",root/"examples/synthetic/metadata.json")


if __name__=="__main__":main()
