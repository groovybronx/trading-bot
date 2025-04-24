# /Users/davidmichels/Desktop/trading-bot/backend/db.py
import sqlite3
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone # Import timezone
import logging
import decimal
from decimal import Decimal  # Import Decimal for stats calculation

# Use a more descriptive name, maybe? Or keep bot_orders.db
DB_PATH = "bot_orders.db"
logger = logging.getLogger(__name__)  # Added logger


@contextmanager
def get_conn():
    """Provides a database connection context."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)  # Add timeout
        # Use dict_factory for easier access by column name
        conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
        yield conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error to {DB_PATH}: {e}", exc_info=True)
        # Optionally re-raise or handle differently
        raise
    finally:
        if conn:
            conn.close()


def init_db():
    """Initializes the database and creates/updates tables."""
    logger.info(f"Initializing database schema at {DB_PATH}...")
    try:
        with get_conn() as conn:
            cursor = conn.cursor()

            # --- Table: sessions ---
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,                      -- Optional user-friendly name
                    start_time INTEGER NOT NULL,    -- Unix timestamp (ms) of session start
                    end_time INTEGER,               -- Unix timestamp (ms) of session end (NULL if active)
                    status TEXT NOT NULL CHECK(status IN ('active', 'completed', 'aborted')), -- Session status
                    strategy TEXT NOT NULL,         -- Strategy used for this session
                    config_snapshot TEXT            -- JSON string of the config used for this session
                )
                """
            )
            logger.info("Table 'sessions' checked/created.")

            # --- Table: order_history ---
            # Check if table exists first
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='order_history';"
            )
            table_exists = cursor.fetchone()

            if not table_exists:
                logger.info("Creating table 'order_history'...")
                cursor.execute(
                    """
                    CREATE TABLE order_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER NOT NULL,  -- Foreign key to sessions table
                        timestamp INTEGER NOT NULL,
                        orderId TEXT UNIQUE NOT NULL,
                        clientOrderId TEXT,
                        symbol TEXT NOT NULL,
                        strategy TEXT NOT NULL,       -- Keep for potential filtering, though session implies it
                        side TEXT NOT NULL,
                        type TEXT,
                        timeInForce TEXT,
                        origQty REAL,
                        executedQty REAL,
                        cummulativeQuoteQty REAL,
                        status TEXT NOT NULL,
                        price REAL,
                        stopPrice REAL,
                        pnl REAL,
                        performance_pct TEXT,
                        created_at TEXT,
                        closed_at TEXT,
                        FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE -- Delete orders if session is deleted
                    )
                    """
                )
                logger.info("Table 'order_history' created.")
            else:
                logger.info(
                    "Table 'order_history' exists. Checking for 'session_id' column..."
                )
                # Check if session_id column exists
                cursor.execute("PRAGMA table_info(order_history);")
                columns = [col["name"] for col in cursor.fetchall()]
                if "session_id" not in columns:
                    logger.warning(
                        "Column 'session_id' not found in 'order_history'. Adding column..."
                    )
                    cursor.execute(
                        "ALTER TABLE order_history ADD COLUMN session_id INTEGER"
                    )  # NULLABLE for now
                    logger.info("Column 'session_id' added to 'order_history'.")
                else:
                    logger.info(
                        "Column 'session_id' already exists in 'order_history'."
                    )

            # Check/Add config_snapshot column to sessions table if it doesn't exist
            cursor.execute("PRAGMA table_info(sessions);")
            session_columns = [col["name"] for col in cursor.fetchall()]
            if "config_snapshot" not in session_columns:
                logger.warning(
                    "Column 'config_snapshot' not found in 'sessions'. Adding column..."
                )
                cursor.execute("ALTER TABLE sessions ADD COLUMN config_snapshot TEXT")
                logger.info("Column 'config_snapshot' added to 'sessions'.")
            else:
                logger.info("Column 'config_snapshot' already exists in 'sessions'.")

            # --- Indexes ---
            # Index for session_id in order_history
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_order_history_session_id_timestamp ON order_history (session_id, timestamp DESC);"
            )
            # Existing indexes (check if they still make sense or need session_id)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_order_history_strategy_timestamp ON order_history (strategy, timestamp DESC);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_order_history_orderId ON order_history (orderId);"
            )
            # Index for session status/start_time
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_status_start_time ON sessions (status, start_time DESC);"
            )

            conn.commit()
            logger.info("Database schema initialization complete.")
    except sqlite3.Error as e:
        logger.critical(
            f"Failed to initialize/update database schema: {e}", exc_info=True
        )
        raise


def save_order(
    order_data: Dict[str, Any], session_id: int
) -> bool:  # Added session_id parameter
    """
    Saves or updates an order in the order_history table using orderId as the key.
    Requires a valid session_id.
    Returns True on success, False on failure.
    """
    # Ensure required fields are present and not None
    required = ["orderId", "symbol", "strategy", "side", "status", "timestamp"]
    if not all(k in order_data and order_data[k] is not None for k in required):
        logger.error(
            f"Cannot save order, missing required fields or None values in data: {order_data}"
        )
        return False
    if session_id is None:  # Check session_id
        logger.error(
            f"Cannot save order {order_data.get('orderId')}, session_id is missing."
        )
        return False

    logger.debug(
        f"Attempting to save order {order_data.get('orderId')} to DB for session {session_id}..."
    )
    try:
        with get_conn() as conn:
            # Use INSERT OR REPLACE to handle new orders and updates based on UNIQUE orderId
            cursor = conn.cursor()  # Get cursor to check rowcount
            cursor.execute(
                """
                INSERT OR REPLACE INTO order_history (
                    session_id, timestamp, orderId, clientOrderId, symbol, strategy, side, type,
                    timeInForce, origQty, executedQty, cummulativeQuoteQty, status,
                    price, stopPrice, pnl, performance_pct, created_at, closed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,  # New parameter
                    int(order_data["timestamp"]),
                    str(order_data["orderId"]),
                    order_data.get("clientOrderId"),
                    order_data["symbol"],
                    order_data["strategy"],
                    order_data["side"],
                    order_data.get("type"),
                    order_data.get("timeInForce"),
                    float(order_data.get("origQty") or 0.0),
                    float(order_data.get("executedQty") or 0.0),
                    float(order_data.get("cummulativeQuoteQty") or 0.0),
                    order_data["status"],
                    float(order_data.get("price") or 0.0),
                    float(order_data.get("stopPrice") or 0.0),
                    float(order_data.get("pnl") or 0.0),
                    order_data.get("performance_pct"),
                    # session_id was here before, removed as it's now a dedicated column
                    order_data.get("created_at", datetime.now(timezone.utc).isoformat()), # Use timezone-aware UTC now
                    order_data.get("closed_at"),
                ),
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.debug(
                    f"Order {order_data.get('orderId')} saved/updated successfully in DB for session {session_id}."
                )
                return True
            else:
                logger.debug(
                    f"Order {order_data.get('orderId')} already exists with identical data or save failed (rowcount=0) for session {session_id}."
                )
                return True
    except (sqlite3.Error, ValueError, TypeError) as e:
        logger.error(
            f"Failed to save order {order_data.get('orderId')} to DB for session {session_id}: {e}",
            exc_info=True,
        )
        return False
    except Exception as e:  # Catch any other unexpected error
        logger.error(
            f"Unexpected error saving order {order_data.get('orderId')} to DB for session {session_id}: {e}",
            exc_info=True,
        )
        return False


def reset_orders(strategy: str) -> bool:
    """
    DEPRECATED - Use delete_session instead.
    Deletes all orders for a specific strategy from the order_history table.
    Returns True on success, False on failure.
    """
    logger.warning(
        f"Function 'reset_orders' is deprecated. Use session management functions."
    )
    # Keep old behavior for now, but it might delete across sessions if strategy is reused.
    logger.warning(
        f"Executing deprecated reset for strategy: {strategy}. This may affect multiple sessions."
    )
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM order_history WHERE strategy = ?", (strategy,)
            )
            conn.commit()
            logger.info(
                f"Deleted {cur.rowcount} orders from DB for strategy '{strategy}' (DEPRECATED ACTION)."
            )
            return True
    except sqlite3.Error as e:
        logger.error(
            f"Failed to execute deprecated reset orders in DB for strategy {strategy}: {e}",
            exc_info=True,
        )
        return False


def get_order_history(
    session_id: int, limit: int = 100
) -> List[Dict[str, Any]]:  # Changed filter to session_id
    """
    Retrieves the most recent orders from the order_history table for a specific session_id.
    """
    action = (
        f"Fetching order history from DB (Session ID: {session_id}, Limit: {limit})"
    )
    logger.debug(action)
    if session_id is None:
        logger.error("Cannot get order history: session_id is required.")
        return []
    try:
        with get_conn() as conn:
            # Select all defined columns explicitly
            query = """SELECT
                    id, session_id, timestamp, orderId, clientOrderId, symbol, strategy, side, type,
                    timeInForce, origQty, executedQty, cummulativeQuoteQty, status,
                    price, stopPrice, pnl, performance_pct, created_at, closed_at
                   FROM order_history
                   WHERE session_id = ? """  # Filter by session_id
            params = [session_id]

            query += " ORDER BY timestamp DESC LIMIT ? "
            params.append(limit)

            cur = conn.execute(query, params)
            rows = cur.fetchall()
            logger.debug(
                f"Fetched {len(rows)} orders from DB for session {session_id}."
            )
            return rows
    except sqlite3.Error as e:
        logger.error(f"Failed to {action}: {e}", exc_info=True)
        return []
    except Exception as e:  # Catch any other unexpected error
        logger.error(f"Unexpected error during {action}: {e}", exc_info=True)
        return []


def get_stats(session_id: int) -> Dict[str, Any]:  # Changed filter to session_id
    """Calculates basic performance statistics based on the 'performance_pct' column for a specific session."""
    logger.debug(f"Calculating stats from DB for session ID: {session_id}")
    stats = {
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "winrate": 0.0,
        "roi": 0.0,  # Sum of PNL percentages
        "avg_pnl": 0.0,  # Average PNL percentage
    }
    if session_id is None:
        logger.error("Cannot get stats: session_id is required.")
        return stats
    try:
        with get_conn() as conn:
            # Fetch performance_pct for completed SELL orders for the specific session
            cur = conn.execute(
                """SELECT performance_pct
                   FROM order_history
                   WHERE session_id = ? AND status = 'FILLED' AND side = 'SELL' AND performance_pct IS NOT NULL""",
                (session_id,),
            )
            perf_percentages_str = [row["performance_pct"] for row in cur.fetchall()]

            pnls_decimal = []
            for perf_str in perf_percentages_str:
                try:
                    if isinstance(perf_str, str) and "%" in perf_str:
                        pnl_val = Decimal(perf_str.replace("%", "")) / Decimal(100)
                        pnls_decimal.append(pnl_val)
                    elif isinstance(perf_str, (int, float)):
                        pnls_decimal.append(Decimal(str(perf_str)))
                except (decimal.InvalidOperation, ValueError, TypeError):
                    logger.warning(
                        f"Could not parse performance_pct '{perf_str}' for stats calculation in session {session_id}."
                    )
                    pass

            total_trades = len(pnls_decimal)
            if total_trades > 0:
                wins = len([p for p in pnls_decimal if p > 0])
                losses = len([p for p in pnls_decimal if p < 0])
                winrate = (wins / total_trades) * 100
                roi = sum(pnls_decimal)
                avg_pnl = roi / total_trades
                stats.update(
                    {
                        "total_trades": total_trades,
                        "wins": wins,
                        "losses": losses,
                        "winrate": round(float(winrate), 2),
                        "roi": round(float(roi * 100), 2),
                        "avg_pnl": round(float(avg_pnl * 100), 2),
                    }
                )
            logger.debug(f"Stats calculated from DB for session {session_id}: {stats}")
            return stats
    except (sqlite3.Error, ZeroDivisionError, decimal.InvalidOperation) as e:
        logger.error(
            f"Failed to calculate stats from DB for session {session_id}: {e}",
            exc_info=True,
        )
        return stats
    except Exception as e:  # Catch any other unexpected error
        logger.error(
            f"Unexpected error calculating stats from DB for session {session_id}: {e}",
            exc_info=True,
        )
        return stats


# --- NEW Session Management Functions ---


def create_new_session(
    strategy: str, config_snapshot_json: str, name: Optional[str] = None
) -> Optional[int]:
    """
    Creates a new active session with a snapshot of the configuration.
    Optionally ends previous active sessions (logic commented out).
    Returns the new session ID on success, None on failure.
    """
    logger.info(f"Attempting to create a new session for strategy: {strategy}")
    now_utc = datetime.now(timezone.utc) # Use timezone-aware UTC now
    now_ms = int(now_utc.timestamp() * 1000)
    session_name = name or f"{strategy}_{now_utc.strftime('%Y%m%d_%H%M%S')}" # Use the same aware object
    if not isinstance(config_snapshot_json, str):
        logger.error(
            "Failed to create session: config_snapshot_json must be a JSON string."
        )
        return None
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            # Step 1: End any previous active session(s) for this strategy (optional, depends on desired logic)
            # If you want only one active session per strategy at a time:
            # cursor.execute(
            #     "UPDATE sessions SET status = 'completed', end_time = ? WHERE strategy = ? AND status = 'active'",
            #     (now_ms, strategy)
            # )
            # logger.info(f"Ended {cursor.rowcount} previous active session(s) for strategy {strategy}.")

            # Step 2: Create the new session
            cursor.execute(
                """
                INSERT INTO sessions (name, start_time, status, strategy, config_snapshot)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_name,
                    now_ms,
                    "active",
                    strategy,
                    config_snapshot_json,
                ),  # Added config_snapshot
            )
            new_session_id = cursor.lastrowid
            conn.commit()
            if new_session_id:
                logger.info(
                    f"Successfully created new session ID: {new_session_id} for strategy {strategy} with name '{session_name}'."
                )
                return new_session_id
            else:
                logger.error("Failed to get last row ID after inserting new session.")
                return None
    except sqlite3.Error as e:
        logger.error(
            f"Database error creating new session for strategy {strategy}: {e}",
            exc_info=True,
        )
        return None
    except Exception as e:
        logger.error(
            f"Unexpected error creating new session for strategy {strategy}: {e}",
            exc_info=True,
        )
        return None


def end_session(session_id: int, final_status: str = "completed") -> bool:
    """Ends a specific session by setting its status and end_time."""
    logger.info(
        f"Attempting to end session ID: {session_id} with status '{final_status}'"
    )
    if final_status not in ["completed", "aborted"]:
        logger.error(f"Invalid final status '{final_status}' for ending session.")
        return False
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000) # Use timezone-aware UTC now
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET status = ?, end_time = ? WHERE id = ? AND status = 'active'",
                (final_status, now_ms, session_id),
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(
                    f"Successfully ended session ID: {session_id} with status '{final_status}'."
                )
                return True
            else:
                logger.warning(
                    f"Session ID {session_id} not found or was not active. No changes made."
                )
                return False  # Or True if not finding it isn't an error? Depends on caller.
    except sqlite3.Error as e:
        logger.error(
            f"Database error ending session ID {session_id}: {e}", exc_info=True
        )
        return False
    except Exception as e:
        logger.error(
            f"Unexpected error ending session ID {session_id}: {e}", exc_info=True
        )
        return False


def get_active_session(strategy: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Gets the currently active session, optionally filtered by strategy."""
    logger.debug(f"Fetching active session (Strategy: {strategy or 'Any'})...")
    try:
        with get_conn() as conn:
            query = "SELECT * FROM sessions WHERE status = 'active'"
            params = []
            if strategy:
                query += " AND strategy = ?"
                params.append(strategy)
            query += (
                " ORDER BY start_time DESC LIMIT 1"  # Get the most recent active one
            )

            cursor = conn.execute(query, params)
            session = cursor.fetchone()  # Returns dict or None
            if session:
                logger.debug(
                    f"Found active session: {session['id']} for strategy {session['strategy']}"
                )
                return session
            else:
                logger.debug("No active session found.")
                return None
    except sqlite3.Error as e:
        logger.error(f"Database error fetching active session: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching active session: {e}", exc_info=True)
        return None


def list_sessions() -> List[Dict[str, Any]]:
    """Lists all sessions, most recent first."""
    logger.debug("Fetching list of all sessions...")
    try:
        with get_conn() as conn:
            cursor = conn.execute("SELECT * FROM sessions ORDER BY start_time DESC")
            sessions = cursor.fetchall()
            logger.debug(f"Fetched {len(sessions)} sessions.")
            return sessions
    except sqlite3.Error as e:
        logger.error(f"Database error listing sessions: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Unexpected error listing sessions: {e}", exc_info=True)
        return []


def delete_session(session_id: int) -> bool:
    """Deletes a session and all its associated orders (due to ON DELETE CASCADE)."""
    logger.warning(
        f"Attempting to delete session ID: {session_id} and all associated orders..."
    )
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            # ON DELETE CASCADE should handle orders, just delete the session
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(
                    f"Successfully deleted session ID: {session_id} and associated orders."
                )
                return True
            else:
                logger.warning(
                    f"Session ID {session_id} not found. No session deleted."
                )
                return False
    except sqlite3.Error as e:
        logger.error(
            f"Database error deleting session ID {session_id}: {e}", exc_info=True
        )
        return False
    except Exception as e:
        logger.error(
            f"Unexpected error deleting session ID {session_id}: {e}", exc_info=True
        )
        return False


# --- Initialization ---
# Call init_db() when the module is imported to ensure the table exists.
# It's safe because of "IF NOT EXISTS".
# REMINDER: Delete the old bot_orders.db file if the schema changed significantly.
try:
    init_db()
except Exception as e:
    # Log critical failure during import-time initialization
    logger.critical(
        f"CRITICAL: Database initialization failed during module import: {e}",
        exc_info=True,
    )
    # Depending on the application structure, you might want to exit here
    # import sys
    # sys.exit("Database initialization failed, cannot continue.")

# Example usage block (optional, for testing)
if __name__ == "__main__":
    import time

    logger.info("Running db.py as main script (for testing)...")

    try:  # Wrap the whole test block in try/except
        # --- Test Session Management ---
        print("\n--- Testing Session Management ---")
        test_strategy = "SESSION_TEST"
        active_session = get_active_session(test_strategy)
        print(f"Initial active session for {test_strategy}: {active_session}")

        # Provide a dummy JSON string for the config snapshot in the test
        new_session_id = create_new_session(test_strategy, config_snapshot_json='{}', name="My Test Run")
        if new_session_id is not None:  # Check specifically for None
            print(f"Created new session: {new_session_id}")
            active_session = get_active_session(test_strategy)
            print(
                f"Active session after creation: {active_session}"
            )  # Correctly indented

            # --- Test Order Saving within Session ---
            print("\n--- Testing Order Saving ---")
            dummy_order = {
                "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000), # Use timezone-aware UTC now
                "orderId": f"test_{int(time.time())}",
                "clientOrderId": "test_client_id_sess",
                "symbol": "ETHUSDT",
                "strategy": test_strategy,  # Match session strategy
                "side": "BUY",
                "type": "MARKET",
                "origQty": "0.1",
                "executedQty": "0.1",
                "cummulativeQuoteQty": "300.0",
                "status": "FILLED",
                "created_at": datetime.now(timezone.utc).isoformat(), # Use timezone-aware UTC now
                # performance_pct would be added on SELL typically
            }
            # Only save if session_id is valid (which it is inside this block)
            if save_order(dummy_order, new_session_id):
                print(f"Dummy order saved for session {new_session_id}.")
            else:
                print(f"Dummy order save FAILED for session {new_session_id}.")

            # --- Test History and Stats per Session ---
            print("\n--- Testing History & Stats ---")
            history = get_order_history(new_session_id, limit=5)
            print(f"\nFetched History (Session {new_session_id}):")
            for order in history:
                print(order)

            stats = get_stats(new_session_id)
            print(f"\nCalculated Stats (Session {new_session_id}):")
            print(stats)

            # --- Test Listing Sessions ---
            print("\n--- Testing List Sessions ---")
            all_sessions = list_sessions()
            print("All Sessions:")
            for sess in all_sessions:
                print(sess)

            # --- Test Ending Session ---
            print("\n--- Testing End Session ---")
            if end_session(new_session_id):
                print(f"Ended session {new_session_id}.")
                active_session = get_active_session(test_strategy)
                print(f"Active session after end: {active_session}")
            else:
                print(f"Failed to end session {new_session_id}.")

            # --- Test Deleting Session --- (Keep commented out unless needed)
            # print("\n--- Testing Delete Session ---")
            # if delete_session(new_session_id):
            #     print(f"Deleted session {new_session_id}.")
            #     history_after_delete = get_order_history(new_session_id, limit=5)
            #     print(f"History after delete (should be empty): {history_after_delete}")
            #     sessions_after_delete = list_sessions()
            #     print(f"Sessions after delete: {sessions_after_delete}")
            # else:
            #      print(f"Failed to delete session {new_session_id}.")

        else:  # This else belongs to 'if new_session_id is not None:'
            print("Failed to create new session for testing.")

        # Example: Deprecated Reset (Should ideally not be used)
        # print("\n--- Testing Deprecated Reset ---")
        # if reset_orders('SESSION_TEST'): # Use the same strategy name
        #     print("\nOrders reset for SESSION_TEST (DEPRECATED).")
        # history_after_reset = get_order_history(???, limit=5) # Cannot get history without session_id now
        # print(f"\nHistory after reset: {history_after_reset}")

    except Exception as main_e:  # Catch errors during the test run
        print(f"\nError during __main__ test: {main_e}")
        logger.exception("Error in __main__ test block")
