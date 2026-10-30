# Participant input contract, version 1

CSV must have exactly `participant_id` plus the eleven numeric fields and units in `scm_strategy.schema.UNITS`. One row is one independent participant. Repeated trials must be summarized using a prospectively specified participant-level rule before this interface. Duplicate keys, missing/extra columns, nonfinite numbers, nonpositive numeric values and missing or different units are errors.

The mandatory JSON sidecar is:

```json
{
  "schema_version": "scm-strategy.participants/1",
  "dataset_kind": "private_empirical",
  "units": {
    "speed_kmh": "km/h", "height_cm": "cm", "weight_kg": "kg",
    "age_years": "year", "navicular_ratio": "1", "foot_size_proxy_cm2": "cm^2",
    "knee_excursion_deg": "degree", "ankle_excursion_deg": "degree",
    "contact_ms": "ms", "pressure_peak_N": "N", "effective_area_cm2": "cm^2"
  }
}
```

Definitions: navicular ratio is the arithmetic mean of each foot's navicular-height/foot-length ratio; the foot-size proxy is mean foot length times mean forefoot width in cm², not measured plantar area. Knee and ankle excursion are bilateral equal-weight robust model-coordinate amplitudes. Contact and pressure quantities are first summarized per side and then equally across sides. These definitions do not validate a sensor, coordinate frame or collection protocol.

The array API `bilateral_excursion` explicitly accepts source seconds, a reference-time window, degrees and one optional source-to-reference time offset. It never infers synchronization or anatomical axes. `effective_area_frame` accepts nonnegative N/cm² and a positive cell area in cm²; an empty/zero-load frame has undefined area and zero force.

