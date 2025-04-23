# /Users/davidmichels/Desktop/trading-bot/backend/db.py
import sqlite3
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import decimal
from decimal import Decimal # Import Decimal for stats calculation

# Use a more descriptive name, maybe? Or keep bot_orders.db
DB_PATH = "bot_orders.db"
logger = logging.getLogger(__name__) # Added logger

@contextmanager
def get_conn():
    """Provides a database connection context."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10) # Add timeout
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
            # --- Ensure all columns needed by frontend/logic are present ---
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS order_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,   -- Event time (Unix ms) - Make NOT NULL
                    orderId TEXT UNIQUE NOT NULL, -- Exchange Order ID (Unique identifier)
                    clientOrderId TEXT,           -- Client Order ID
                    symbol TEXT NOT NULL,         -- Trading pair (e.g., BTCUSDT)
                    strategy TEXT NOT NULL,       -- Strategy name
                    side TEXT NOT NULL,           -- BUY or SELL
                    type TEXT,                    -- Order type (MARKET, LIMIT, etc.)
                    timeInForce TEXT,             -- Time in force (GTC, IOC, FOK)
                    origQty REAL,                 -- Original order quantity (as REAL/float)
                    executedQty REAL,             -- Quantity filled (as REAL/float)
                    cummulativeQuoteQty REAL,     -- Total quote asset value filled (as REAL/float)
                    status TEXT NOT NULL,         -- Order status (NEW, FILLED, CANCELED, etc.) - Make NOT NULL
                    price REAL,                   -- Price for LIMIT orders (or avg price?) (as REAL/float)
                    stopPrice REAL,               -- Stop price for STOP_LOSS etc. (as REAL/float)
                    pnl REAL,                     -- Profit/Loss value (if calculated, as REAL/float)
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

def save_order(order_data: Dict[str, Any]) -> bool:
    """
    Saves or updates an order in the order_history table using orderId as the key.
    Returns True on success, False on failure.
    """
    # Ensure required fields are present and not None
    required = ['orderId', 'symbol', 'strategy', 'side', 'status', 'timestamp']
    if not all(k in order_data and order_data[k] is not None for k in required):
        logger.error(f"Cannot save order, missing required fields or None values in data: {order_data}")
        return False

    logger.debug(f"Attempting to save order {order_data.get('orderId')} to DB...")
    try:
        with get_conn() as conn:
            # Use INSERT OR REPLACE to handle new orders and updates based on UNIQUE orderId
            cursor = conn.cursor() # Get cursor to check rowcount
            cursor.execute(
                """
                INSERT OR REPLACE INTO order_history (
                    timestamp, orderId, clientOrderId, symbol, strategy, side, type,
                    timeInForce, origQty, executedQty, cummulativeQuoteQty, status,
                    price, stopPrice, pnl, performance_pct, session_id, created_at, closed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(order_data['timestamp']), # Use direct access after check
                    str(order_data['orderId']),   # Use direct access after check
                    order_data.get('clientOrderId'), # Optional
                    order_data['symbol'],         # Use direct access after check
                    order_data['strategy'],       # Use direct access after check
                    order_data['side'],           # Use direct access after check
                    order_data.get('type'),       # Optional
                    order_data.get('timeInForce'),# Optional
                    # Convert numeric fields safely to float, defaulting to 0.0 if None
                    float(order_data.get('origQty') or 0.0),
                    float(order_data.get('executedQty') or 0.0),
                    float(order_data.get('cummulativeQuoteQty') or 0.0),
                    order_data['status'],         # Use direct access after check
                    float(order_data.get('price') or 0.0),
                    float(order_data.get('stopPrice') or 0.0),
                    float(order_data.get('pnl') or 0.0), # Keep pnl for stats
                    order_data.get('performance_pct'), # String like 'x.xx%' or None
                    order_data.get('session_id'), # Optional
                    order_data.get('created_at', datetime.utcnow().isoformat()), # Fallback
                    order_data.get('closed_at') # Optional
                ),
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.debug(f"Order {order_data.get('orderId')} saved/updated successfully in DB.")
                return True
            else:
                # This might happen with INSERT OR REPLACE if the row was identical, still counts as success
                logger.debug(f"Order {order_data.get('orderId')} already exists with identical data or save failed (rowcount=0).")
                # Consider it success if no error occurred
                return True
    except (sqlite3.Error, ValueError, TypeError) as e:
        logger.error(f"Failed to save order {order_data.get('orderId')} to DB: {e}", exc_info=True)
        return False
    except Exception as e: # Catch any other unexpected error
        logger.error(f"Unexpected error saving order {order_data.get('orderId')} to DB: {e}", exc_info=True)
        return False


def reset_orders(strategy: str) -> bool:
    """
    Deletes all orders for a specific strategy from the order_history table.
    Returns True on success, False on failure.
    """
    logger.warning(f"Resetting order history in DB for strategy: {strategy}")
    try:
        with get_conn() as conn:
            cur = conn.execute("DELETE FROM order_history WHERE strategy = ?", (strategy,))
            conn.commit()
            logger.info(f"Deleted {cur.rowcount} orders from DB for strategy '{strategy}'.")
            return True
    except sqlite3.Error as e:
        logger.error(f"Failed to reset orders in DB for strategy {strategy}: {e}", exc_info=True)
        return False

def get_order_history(strategy: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Retrieves the most recent orders from the order_history table, optionally filtered by strategy.
    """
    action = f"Fetching order history from DB (Strategy: {strategy or 'ALL'}, Limit: {limit})"
    logger.debug(action)
    try:
        with get_conn() as conn:
            # Select all defined columns explicitly
            query = """SELECT
                    id, timestamp, orderId, clientOrderId, symbol, strategy, side, type,
                    timeInForce, origQty, executedQty, cummulativeQuoteQty, status,
                    price, stopPrice, pnl, performance_pct, session_id, created_at, closed_at
                   FROM order_history """
            params = []
            if strategy:
                query += " WHERE strategy = ? "
                params.append(strategy)

            query += " ORDER BY timestamp DESC LIMIT ? "
            params.append(limit)

            cur = conn.execute(query, params)
            rows = cur.fetchall()
            logger.debug(f"Fetched {len(rows)} orders from DB for strategy '{strategy or 'ALL'}'.")
            # Rows are already dictionaries due to row_factory
            return rows
    except sqlite3.Error as e:
        logger.error(f"Failed to {action}: {e}", exc_info=True)
        return [] # Return empty list on error
    except Exception as e: # Catch any other unexpected error
        logger.error(f"Unexpected error during {action}: {e}", exc_info=True)
        return []

def get_stats(strategy: str) -> Dict[str, Any]:
    """Calculates basic performance statistics based on the 'pnl' or 'performance_pct' column for a strategy."""
    logger.debug(f"Calculating stats from DB for strategy: {strategy}")
    stats = {
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "winrate": 0.0,
        "roi": 0.0, # Sum of PNL percentages
        "avg_pnl": 0.0, # Average PNL percentage
    }
    try:
        with get_conn() as conn:
            # Fetch performance_pct for completed SELL orders
            cur = conn.execute(
                """SELECT performance_pct
                   FROM order_history
                   WHERE strategy = ? AND status = 'FILLED' AND side = 'SELL' AND performance_pct IS NOT NULL""",
                (strategy,)
            )
            # Fetchall returns list of dicts
            perf_percentages_str = [row["performance_pct"] for row in cur.fetchall()]

            pnls_decimal = []
            for perf_str in perf_percentages_str:
                try:
                    # Convert 'x.xx%' string to Decimal fraction
                    if isinstance(perf_str, str) and '%' in perf_str:
                         # Use Decimal for precision
                         pnl_val = Decimal(perf_str.replace('%','')) / Decimal(100)
                         pnls_decimal.append(pnl_val)
                    # Handle case where it might already be a number (though saved as TEXT)
                    elif isinstance(perf_str, (int, float)):
                         pnls_decimal.append(Decimal(str(perf_str)))
                except (decimal.InvalidOperation, ValueError, TypeError):
                    logger.warning(f"Could not parse performance_pct '{perf_str}' for stats calculation.")
                    pass # Ignore invalid values

            total_trades = len(pnls_decimal)
            if total_trades > 0:
                wins = len([p for p in pnls_decimal if p > 0])
                losses = len([p for p in pnls_decimal if p < 0]) # Count only negative PNLs
                winrate = (wins / total_trades) * 100
                # ROI is the sum of percentage gains/losses
                roi = sum(pnls_decimal)
                avg_pnl = roi / total_trades
                stats.update({
                    "total_trades": total_trades,
                    "wins": wins,
                    "losses": losses,
                    "winrate": round(float(winrate), 2), # Convert Decimal to float for JSON
                    # Multiply by 100 to display as percentage in frontend
                    "roi": round(float(roi * 100), 2),
                    "avg_pnl": round(float(avg_pnl * 100), 2),
                })
            logger.debug(f"Stats calculated from DB for strategy '{strategy}': {stats}")
            return stats
    except (sqlite3.Error, ZeroDivisionError, decimal.InvalidOperation) as e:
        logger.error(f"Failed to calculate stats from DB for strategy {strategy}: {e}", exc_info=True)
        return stats # Return default stats on error
    except Exception as e: # Catch any other unexpected error
        logger.error(f"Unexpected error calculating stats from DB for strategy {strategy}: {e}", exc_info=True)
        return stats

# --- Initialization ---
# Call init_db() when the module is imported to ensure the table exists.
# It's safe because of "IF NOT EXISTS".
# REMINDER: Delete the old bot_orders.db file if the schema changed significantly.
try:
    init_db()
except Exception as e:
    # Log critical failure during import-time initialization
    logger.critical(f"CRITICAL: Database initialization failed during module import: {e}", exc_info=True)
    # Depending on the application structure, you might want to exit here
    # import sys
    # sys.exit("Database initialization failed, cannot continue.")

# Example usage block (optional, for testing)
if __name__ == "__main__":
    import time
    logger.info("Running db.py as main script (for testing)...")
    # Example: Add a dummy order
    dummy_order = {
        'timestamp': int(datetime.utcnow().timestamp() * 1000),
        'orderId': f'test_{int(time.time())}',
        'clientOrderId': 'test_client_id',
        'symbol': 'BTCUSDT',
        'strategy': 'TESTING_DB',
        'side': 'BUY',
        'type': 'MARKET',
        'timeInForce': None,
        'origQty': '1.0',
        'executedQty': '1.0',
        'cummulativeQuoteQty': '70000.0',
        'status': 'FILLED',
        'price': '0.0', # Market order price is 0
        'stopPrice': '0.0',
        'pnl': None,
        'performance_pct': None,
        'session_id': 'test_session_db',
        'created_at': datetime.utcnow().isoformat()
    }
    try:
        if save_order(dummy_order):
            print("Dummy order saved.")
        else:
            print("Dummy order save FAILED.")

        # Example: Get history
        history = get_order_history('TESTING_DB', limit=5)
        print("\nFetched History (TESTING_DB):")
        for order in history:
            print(order)

        # Example: Get stats
        stats = get_stats('TESTING_DB')
        print("\nCalculated Stats (TESTING_DB):")
        print(stats)

        # Example: Reset
        # if reset_orders('TESTING_DB'):
        #     print("\nOrders reset for TESTING_DB.")
        # history_after_reset = get_order_history('TESTING_DB', limit=5)
        # print(f"\nHistory after reset: {history_after_reset}")

    except Exception as main_e:
        print(f"\nError during __main__ test: {main_e}")

