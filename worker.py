"""Local order worker fixture. Its two modes share the same database schema."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier


def reserve_atomic(database, order):
    with sqlite3.connect(database) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM reservations WHERE order_id = ?", (order,)).fetchone():
            return
        updated = db.execute("UPDATE inventory SET stock = stock - 1 WHERE stock > 0")
        if updated.rowcount == 1:
            db.execute("INSERT INTO reservations VALUES (?)", (order,))


def reserve_stale(database, order, after_read):
    with sqlite3.connect(database) as db:
        stock = db.execute("SELECT stock FROM inventory").fetchone()[0]
        after_read.wait(timeout=5)
        if stock > 0:
            db.execute("UPDATE inventory SET stock = ?", (stock - 1,))
            db.execute("INSERT INTO reservations VALUES (?)", (order,))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("mode", choices=["stale-read", "atomic"])
    parser.add_argument("orders", nargs="+")
    args = parser.parse_args()
    if len(args.orders) == 1:
        if args.mode != "atomic":
            parser.error("Replay is supported only for the candidate")
        reserve_atomic(args.database, args.orders[0])
        return

    ready = Barrier(len(args.orders))
    after_read = Barrier(len(args.orders))

    def handle(order):
        ready.wait(timeout=5)
        if args.mode == "atomic":
            reserve_atomic(args.database, order)
        else:
            reserve_stale(args.database, order, after_read)

    with ThreadPoolExecutor(max_workers=len(args.orders)) as pool:
        list(pool.map(handle, args.orders))


if __name__ == "__main__":
    main()
