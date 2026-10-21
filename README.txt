PMo combined analysis dataset

original_baseline/: Copies of raw original agent outputs (8192-token Claude condition retained).
recovery_archive/: Copies of 16000-token Claude recovery outputs, including failed PMo 18.
selected_for_analysis/: One selected output per process and provider; incomplete outputs have no initial.bpmn.
ground_truth_RESTRICTED/: Reference models. NEVER expose to generating or feedback agents.
analysis_manifest.csv: Provenance, configurations, and statuses.
IMPORTANT: This is a combined analysis view, NOT a homogeneous-token-budget baseline.
Models selected from recovery have a different output limit. Do not conflate their quality with the original setting.
Selection is based on parseable BPMN XML availability, not semantic correctness.
