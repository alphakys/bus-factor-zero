# Bus Factor Zero local proof

Run the orchestrator on Python 3.10 or newer.

```sh
python -m pip install -r requirements.txt
python run_drill.py orchestrator.yaml
```

The YAML runs the baseline and candidate in separate SQLite databases. The baseline deliberately places both orders at a barrier after each has read the last item. Both write based on that stale read. The candidate serializes the conditional decrement and reservation insert in one transaction and handles repeat deliveries by order ID.

The verifier reads each database after the worker process exits. It requires the baseline to violate inventory conservation, the candidate to satisfy it, and a redelivery of the winning order to leave the candidate database unchanged. The winning order ID can vary. The process returns a nonzero exit code if the drill fails.

This proof covers local inventory consistency and replay. The proposed AWS staging deployment, IAM denial drill, and Devin API integration have not been run here. `proof.json` is output captured from a local run.
