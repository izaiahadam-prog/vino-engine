# VINO

## External Validation Pipeline

This repository includes a first-pass external-validation scaffold for VINO as a continuation-under-uncertainty engine.

The pipeline:

1. Ingests public or local external-domain records.
2. Normalizes records across five domains.
3. Builds successor-selection tasks.
4. Runs ordinary baseline selectors.
5. Runs a heuristic VINO continuation-integrity evaluator.
6. Writes transparent comparison reports.

Supported domains:

- Git repositories: fork lineage, refactors, renamed modules, file survival.
- Wikipedia: concept continuity through revisions.
- Papers: idea lineage through citations and terminology shifts.
- Datasets: provenance through transformations.
- Software symbols: function/class survival across rewrites.

Commands:

```powershell
py -3 -m vino_cli.main ingest --config ingestion_config.example.json
py -3 -m vino_cli.main validate-ingestion
py -3 -m vino_cli.main build-candidates --input data/external --out data/candidates
py -3 -m vino_cli.main evaluate --candidates data/candidates --out results/external_validation
py -3 -m vino_cli.main report --results results/external_validation
py -3 -m vino_cli.main run-all --config ingestion_config.example.json
```

Smoke test:

```powershell
py -3 scripts/run_external_validation_smoke_test.py
```

Outputs:

- `data/external/*.jsonl`
- `data/external/continuation_candidates/*.jsonl`
- `data/candidates/continuation_tasks.jsonl`
- `results/external_validation/external_validation_results.json`
- `results/external_validation/external_validation_report.txt`
- `results/external_validation/external_validation_report.json`

Limitations:

- This pipeline is an external-validation scaffold.
- The current VINO scoring is heuristic.
- Results from sample data are not proof.
- Serious validation requires real external datasets and baseline comparison.
