# Bus Factor Zero

Could the next engineer recover a critical service at 3 a.m. with the founder offline? Bus Factor Zero is a prototype for rehearsing that handoff and giving the engineer a reproducible way to verify the recovery.

This first drill covers a stock reservation worker. Two orders compete for the last unit. The baseline returns two reservations because both workers act on the same stale stock reading. The candidate commits the stock decrement and reservation together, then handles another delivery of the winning order without changing the database.

## Run the drill

Use Python 3.10 or newer.

```sh
python -m pip install -r requirements.txt
python run_drill.py orchestrator.yaml
```

| Check | Observed result |
| --- | --- |
| Baseline, stock of one | Two reservations, no remaining stock, inventory invariant broken |
| Candidate, same inputs | One reservation, no remaining stock, inventory invariant holds |
| Replay the winning order | The candidate's committed stock and reservations stay the same |

The YAML starts the baseline and candidate in parallel with separate SQLite databases. A separate verifier reads committed rows after each worker exits. It requires the baseline to reproduce the failure and the candidate to pass the inventory and replay checks. The winning order can vary. The command returns a nonzero exit code when any required check fails.

[proof.json](proof.json) is the output of a local run. The GitHub Actions workflow runs the same drill ten times and includes a fresh report in the job summary.

## Scope

The prototype uses Python, PyYAML and SQLite. It runs on synthetic fixture data. The planned pilot adds the Devin sessions and an AWS staging drill in which an on-call engineer handles a real permission denial and a backup admin owns the escalation. Those integrations are pending.
