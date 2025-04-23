import sqlite3
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
from datetime import datetime

DB_PATH = "bot_orders.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL,
                price REAL,
                pnl REAL,
                status TEXT,
                created_at TEXT,
                closed_at TEXT
            )
        """
        )
        conn.commit()


def add_order(order: Dict[str, Any]):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO orders (strategy, symbol, side, qty, price, pnl, status, created_at, closed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                order["strategy"],
                order["symbol"],
                order["side"],
                order.get("qty"),
                order.get("price"),
                order.get("pnl"),
                order.get("status"),
                order.get("created_at", datetime.utcnow().isoformat()),
                order.get("closed_at"),
            ),
        )
        conn.commit()


def reset_orders(strategy: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM orders WHERE strategy = ?", (strategy,))
        conn.commit()


def get_orders(strategy: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM orders WHERE strategy = ? ORDER BY created_at DESC",
            (strategy,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_stats(strategy: str) -> Dict[str, Any]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT pnl FROM orders WHERE strategy = ? AND pnl IS NOT NULL", (strategy,)
        )
        pnls = [row["pnl"] for row in cur.fetchall()]
        total_trades = len(pnls)
        wins = len([p for p in pnls if p > 0])
        losses = len([p for p in pnls if p < 0])
        winrate = (wins / total_trades) * 100 if total_trades > 0 else 0
        roi = sum(pnls)
        avg_pnl = roi / total_trades if total_trades > 0 else 0
        return {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "winrate": winrate,
            "roi": roi,
            "avg_pnl": avg_pnl,
        }


# Appeler init_db() à l'import du module pour garantir la création de la table
init_db()

# Appeler init_db() au démarrage du backend
if __name__ == "__main__":
    init_db()
