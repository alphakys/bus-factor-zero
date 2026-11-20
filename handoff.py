"""Review and apply a scoped repair to a local inventory drill database."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from run_drill import initialize_database, read_database, read_inventory, run_worker


INITIAL_STOCK = 1
ORDERS = ("order-a", "order-b")


def prepare(directory):
    directory.mkdir()
    database = directory / "orders.sqlite"
    initialize_database(database, INITIAL_STOCK)
    drill_id = uuid4().hex
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("CREATE TABLE drill_context (id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO drill_context VALUES (?)", (drill_id,))

    run_worker(database, "stale-read", ORDERS)
    before = read_database(database, INITIAL_STOCK)
    if before["order_ids"] != list(ORDERS) or before["stock"] != 0:
        raise ValueError("the expected inventory incident did not reproduce")

    plan = {
        "drill_id": drill_id,
        "decision": "Keep the first order from the fixture's intake sequence.",
        "before": before,
        "keep_order": ORDERS[0],
        "release_order": ORDERS[1],
        "after": {
            "reservations": 1,
            "stock": 0,
            "inventory_balanced": True,
            "order_ids": [ORDERS[0]],
        },
    }
    payload = (json.dumps(plan, indent=2) + "\n").encode("utf-8")
    (directory / "plan.json").write_bytes(payload)
    return {"state": "awaiting_approval", "sha256": hashlib.sha256(payload).hexdigest(), "plan": plan}


def recover(directory, approval):
    payload = (directory / "plan.json").read_bytes()
    if hashlib.sha256(payload).hexdigest() != approval:
        raise ValueError("approval does not match this recovery plan")
    plan = json.loads(payload)
    database = directory / "orders.sqlite"
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=rw", uri=True)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        identity = db.execute("SELECT id FROM drill_context").fetchall()
        if identity != [(plan["drill_id"],)]:
            raise ValueError("the database belongs to a different drill")
        current = read_inventory(db, INITIAL_STOCK)
        if current == plan["before"]:
            db.execute("DELETE FROM reservations WHERE order_id = ?", (plan["release_order"],))
            if read_inventory(db, INITIAL_STOCK) != plan["after"]:
                raise ValueError("the repair did not produce the approved state")
        elif current != plan["after"]:
            raise ValueError("inventory changed since review. Prepare a new drill.")

    committed = read_database(database, INITIAL_STOCK)
    if committed != plan["after"]:
        raise ValueError("independent verification failed")
    with TemporaryDirectory(prefix="bfz-replay-") as scratch:
        replay = Path(scratch) / "orders.sqlite"
        with (
            closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(replay)) as target,
        ):
            source.backup(target)
        run_worker(replay, "atomic", ORDERS)
        if read_database(replay, INITIAL_STOCK) != committed:
            raise ValueError("redelivery check failed")
    return {
        "state": "recovered",
        "approval_sha256": approval,
        "committed": committed,
        "redelivery_unchanged": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "recover"):
        step = subcommands.add_parser(command)
        step.add_argument("directory", type=Path)
        if command == "recover":
            step.add_argument("--approve", required=True, metavar="SHA256")
    args = parser.parse_args()
    try:
        report = (
            prepare(args.directory)
            if args.command == "prepare"
            else recover(args.directory, args.approve)
        )
    except (OSError, ValueError, KeyError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"Blocked: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
