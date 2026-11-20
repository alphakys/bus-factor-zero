"""Run the YAML against isolated databases and read results independently."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory

import yaml


ROOT = Path(__file__).resolve().parent


def initialize_database(database, initial_stock):
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("CREATE TABLE inventory (stock INTEGER NOT NULL CHECK (stock >= 0))")
        db.execute("CREATE TABLE reservations (order_id TEXT PRIMARY KEY NOT NULL)")
        db.execute("INSERT INTO inventory VALUES (?)", (initial_stock,))


def read_inventory(db, initial_stock):
    stock = db.execute("SELECT stock FROM inventory").fetchone()[0]
    order_ids = [
        row[0] for row in db.execute("SELECT order_id FROM reservations ORDER BY order_id")
    ]
    return {
        "reservations": len(order_ids),
        "stock": stock,
        "inventory_balanced": stock >= 0 and stock + len(order_ids) == initial_stock,
        "order_ids": order_ids,
    }


def read_database(database, initial_stock):
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        return read_inventory(db, initial_stock)


def run_worker(database, mode, orders):
    command = [sys.executable, str(ROOT / "worker.py"), str(database), mode, *orders]
    subprocess.run(command, check=True, timeout=15)


def run_case(name, case, config):
    initial_stock = config["initial_stock"]
    orders = config["concurrent_orders"]
    with TemporaryDirectory(prefix=f"bfz-{name}-") as directory:
        database = Path(directory) / "orders.sqlite"
        initialize_database(database, initial_stock)
        run_worker(database, case["worker"], orders)
        observed = read_database(database, initial_stock)
        matches = all(
            observed[key] == case["expect"][key]
            for key in ("reservations", "stock", "inventory_balanced")
        ) and set(observed["order_ids"]).issubset(orders)
        result = {"observed": observed, "matched_expected": matches}

        if case.get("replay_winning_order"):
            valid_winner = matches and len(observed["order_ids"]) == 1
            if valid_winner:
                winner = observed["order_ids"][0]
                run_worker(database, case["worker"], [winner])
                result["after_replay"] = read_database(database, initial_stock)
            result["replay_unchanged"] = valid_winner and result["after_replay"] == observed
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path, nargs="?", default=ROOT / "orchestrator.yaml")
    config = yaml.safe_load(parser.parse_args().config.read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = {
            name: pool.submit(run_case, name, case, config)
            for name, case in config["runs"].items()
        }
        results = {name: run.result() for name, run in runs.items()}

    baseline = results["baseline"]
    candidate = results["candidate"]
    passed = (
        baseline["matched_expected"]
        and not baseline["observed"]["inventory_balanced"]
        and candidate["matched_expected"]
        and candidate["observed"]["inventory_balanced"]
        and candidate["replay_unchanged"]
    )
    report = {
        "scenario": config["scenario"],
        "environment": "local SQLite fixture",
        "passed": passed,
        **results,
    }
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
