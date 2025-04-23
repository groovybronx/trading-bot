# /Users/davidmichels/Desktop/trading-bot/backend/db.py
import sqlite3
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging # Added logging

# Use a more descriptive name, maybe? Or keep bot_orders.db
DB_PATH = "bot_orders.db"
logger = logging.getLogger(__name__) # Added logger

@contextmanager
def get_conn():
    """Provides a database connection context."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        # Use dict_factory for easier access by column name
        conn.row_factory = lambda c, r: dict(
            zip([col[0] for col in c.description], r)
        )
        yield conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error to {DB_PATH}: {e}", exc_info=True)
        # Optionally re-raise or handle differently
        raise
    finally:
        if conn:
            conn.close()

def init_db():
    """Initializes the database and creates the order_history table if it doesn't exist."""
    logger.info(f"Initializing database at {DB_PATH}...")
    try:
        with get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS order_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER,            -- Event time (Unix ms)
                    orderId TEXT UNIQUE NOT NULL, -- Exchange Order ID (Unique identifier)
                    clientOrderId TEXT,           -- Client Order ID
                    symbol TEXT NOT NULL,         -- Trading pair (e.g., BTCUSDT)
                    strategy TEXT NOT NULL,       -- Strategy name
                    side TEXT NOT NULL,           -- BUY or SELL
                    type TEXT,                    -- Order type (MARKET, LIMIT, etc.)
                    timeInForce TEXT,             -- Time in force (GTC, IOC, FOK)
                    origQty REAL,                 -- Original order quantity
                    executedQty REAL,             -- Quantity filled
                    cummulativeQuoteQty REAL,     -- Total quote asset value filled
                    status TEXT,                  -- Order status (NEW, FILLED, CANCELED, etc.)
                    price REAL,                   -- Price for LIMIT orders (or avg price?)
                    stopPrice REAL,               -- Stop price for STOP_LOSS etc.
                    pnl REAL,                     -- Profit/Loss value (if calculated)
                    performance_pct TEXT,         -- Performance as string 'x.xx%' (if calculated)
                    session_id TEXT,              -- Bot session identifier
                    created_at TEXT,              -- Original creation timestamp string (optional)
                    closed_at TEXT                -- Original closing timestamp string (optional)
                )
            """
            )
            # Add indexes for faster querying
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_order_history_strategy_timestamp ON order_history (strategy, timestamp DESC);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_order_history_orderId ON order_history (orderId);"
            )
            conn.commit()
            logger.info("Database initialized successfully. 'order_history' table checked/created.")
    except sqlite3.Error as e:
        logger.critical(f"Failed to initialize database schema: {e}", exc_info=True)
        # This is critical, maybe exit or raise
        raise

def save_order(order_data: Dict[str, Any]):
    """Saves or updates an order in the order_history table using orderId as the key."""
    # Ensure required fields are present
    required = ['orderId', 'symbol', 'strategy', 'side', 'status', 'timestamp']
    if not all(k in order_data and order_data[k] is not None for k in required):
        logger.error(f"Cannot save order, missing required fields in data: {order_data}")
        return

    logger.debug(f"Saving order {order_data.get('orderId')} to DB...")
    try:
        with get_conn() as conn:
            # Use INSERT OR REPLACE to handle new orders and updates based on UNIQUE orderId
            conn.execute(
                """
                INSERT OR REPLACE INTO order_history (
                    timestamp, orderId, clientOrderId, symbol, strategy, side, type,
                    timeInForce, origQty, executedQty, cummulativeQuoteQty, status,
                    price, stopPrice, pnl, performance_pct, session_id, created_at, closed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(order_data.get('timestamp', 0)), # Ensure integer
                    str(order_data.get('orderId')),      # Ensure string
                    order_data.get('clientOrderId'),
                    order_data.get('symbol'),
                    order_data.get('strategy'),
                    order_data.get('side'),
                    order_data.get('type'),
                    order_data.get('timeInForce'),
                    # Convert numeric fields safely to float, defaulting to 0.0 if None or invalid
                    float(order_data.get('origQty') or 0.0),
                    float(order_data.get('executedQty') or 0.0),
                    float(order_data.get('cummulativeQuoteQty') or 0.0),
                    order_data.get('status'),
                    float(order_data.get('price') or 0.0),
                    float(order_data.get('stopPrice') or 0.0),
                    float(order_data.get('pnl') or 0.0), # Keep pnl for stats
                    order_data.get('performance_pct'), # String like 'x.xx%' or None
                    order_data.get('session_id'),
                    order_data.get('created_at', datetime.utcnow().isoformat()), # Fallback
                    order_data.get('closed_at')
                ),
            )
            conn.commit()
            logger.debug(f"Order {order_data.get('orderId')} saved/updated successfully.")
    except (sqlite3.Error, ValueError, TypeError) as e:
        logger.error(f"Failed to save order {order_data.get('orderId')}: {e}", exc_info=True)


def reset_orders(strategy: str):
    """Deletes all orders for a specific strategy from the order_history table."""
    logger.warning(f"Resetting order history for strategy: {strategy}")
    try:
        with get_conn() as conn:
            cur = conn.execute("DELETE FROM order_history WHERE strategy = ?", (strategy,))
            conn.commit()
            logger.info(f"Deleted {cur.rowcount} orders for strategy '{strategy}'.")
    except sqlite3.Error as e:
        logger.error(f"Failed to reset orders for strategy {strategy}: {e}", exc_info=True)


def get_order_history(strategy: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Retrieves the most recent orders for a specific strategy from the order_history table."""
    logger.debug(f"Fetching order history for strategy: {strategy} (limit: {limit})")
    try:
        with get_conn() as conn:
            # Select all defined columns explicitly
            cur = conn.execute(
                """SELECT
                    id, timestamp, orderId, clientOrderId, symbol, strategy, side, type,
                    timeInForce, origQty, executedQty, cummulativeQuoteQty, status,
                    price, stopPrice, pnl, performance_pct, session_id, created_at, closed_at
                   FROM order_history
                   WHERE strategy = ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (strategy, limit),
            )
            rows = cur.fetchall()
            logger.debug(f"Fetched {len(rows)} orders for strategy '{strategy}'.")
            # Rows are already dictionaries due to row_factory
            return rows
    except sqlite3.Error as e:
        logger.error(f"Failed to get order history for strategy {strategy}: {e}", exc_info=True)
        return [] # Return empty list on error


def get_stats(strategy: str) -> Dict[str, Any]:
    """Calculates basic performance statistics based on the 'pnl' column for a strategy."""
    logger.debug(f"Calculating stats for strategy: {strategy}")
    stats = {
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "winrate": 0.0,
        "roi": 0.0, # Sum of PNL values
        "avg_pnl": 0.0,
    }
    try:
        with get_conn() as conn:
            # Using pnl column for stats calculation
            cur = conn.execute(
                "SELECT pnl FROM order_history WHERE strategy = ? AND pnl IS NOT NULL AND status = 'FILLED' AND side = 'SELL'", # Consider only filled SELL orders for PNL stats
                (strategy,)
            )
            # Fetchall returns list of dicts
            pnls = [row["pnl"] for row in cur.fetchall() if isinstance(row.get("pnl"), (int, float))]

            total_trades = len(pnls)
            if total_trades > 0:
                wins = len([p for p in pnls if p > 0])
                losses = len([p for p in pnls if p < 0])
                winrate = (wins / total_trades) * 100
                roi = sum(pnls)
                avg_pnl = roi / total_trades
                stats.update({
                    "total_trades": total_trades,
                    "wins": wins,
                    "losses": losses,
                    "winrate": round(winrate, 2),
                    "roi": round(roi, 4), # Adjust precision as needed
                    "avg_pnl": round(avg_pnl, 4), # Adjust precision as needed
                })
            logger.debug(f"Stats calculated for strategy '{strategy}': {stats}")
            return stats
    except (sqlite3.Error, ZeroDivisionError) as e:
        logger.error(f"Failed to calculate stats for strategy {strategy}: {e}", exc_info=True)
        return stats # Return default stats on error


# --- Initialization ---
init_db()

   
# Example usage block (optional, for testing)
if __name__ == "__main__":
     init_db()
    
  