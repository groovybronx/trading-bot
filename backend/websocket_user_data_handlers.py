import logging
from decimal import Decimal, InvalidOperation
import time
from typing import Dict, Any
from datetime import datetime, timezone

# --- Gestionnaires ---
from manager.state_manager import state_manager
from manager.config_manager import config_manager

# --- Utilitaires ---
from utils.websocket_utils import broadcast_state_update, broadcast_order_history_update, broadcast_stats_update

# --- MODIFIED: Import DB ---
import db

logger = logging.getLogger(__name__)

# --- User Data Handler ---
def process_user_data_message(data: Dict[str, Any]):
    """Traite les messages User Data Stream (ordres, balance)."""
    event_type = data.get("e")
    try:
        if event_type == "executionReport":
            _handle_execution_report(data)
        elif event_type == "outboundAccountPosition":
            _handle_account_position(data)
        elif event_type == "balanceUpdate":
            _handle_balance_update(data)
    except Exception as e:
        logger.error(
            f"Error processing User Data message (Type: {event_type}): {e}",
            exc_info=True,
        )


def _format_execution_report_for_db(exec_report: Dict[str, Any]) -> Dict[str, Any]:
    """Formats the execution report data for saving into the database."""
    order_id = str(exec_report.get("i", "N/A"))
    side = exec_report.get("S")
    status = exec_report.get("X")
    timestamp = exec_report.get("T")

    strategy = config_manager.get_value("STRATEGY_TYPE", "UNKNOWN")
    # Get the active session ID from state_manager
    session_id = state_manager.get_active_session_id()
    if session_id is None:
        logger.error(
            f"Cannot format execution report for DB: No active session ID found for order {order_id}."
        )
        # Return an empty dict or raise an error? Returning empty for now.
        # This case should ideally not happen if the bot is running.
        return {}

    performance_pct = None
    pnl_value = None
    entry_details_hist = (
        state_manager.get_state("entry_details")
        if side == "SELL" and status == "FILLED"
        else None
    )

    if entry_details_hist:
        try:
            entry_price = Decimal(str(entry_details_hist.get("avg_price", "0")))
            exec_qty_sell = Decimal(str(exec_report.get("z", "0")))
            quote_qty_sell = Decimal(str(exec_report.get("Z", "0")))
            if entry_price > 0 and exec_qty_sell > 0:
                exit_price = quote_qty_sell / exec_qty_sell
                perf = (exit_price - entry_price) / entry_price
                performance_pct = f"{perf:.4%}"
                pnl_value = (exit_price - entry_price) * exec_qty_sell
                logger.info(
                    f"Calculated PNL for order {order_id}: {pnl_value:.4f} {state_manager.get_state('quote_asset')}, Perf: {performance_pct}"
                )
        except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
            logger.warning(
                f"Failed to calculate performance/PNL for order {order_id}: {e}",
                exc_info=False,
            )

    formatted_order = {
        "timestamp": int(timestamp) if timestamp else int(time.time() * 1000),
        "orderId": order_id,
        "clientOrderId": exec_report.get("c"),
        "symbol": exec_report.get("s"),
        "strategy": strategy,
        "side": side,
        "type": exec_report.get("o"),
        "timeInForce": exec_report.get("f"),
        "origQty": exec_report.get("q"),
        "executedQty": exec_report.get("z"),
        "cummulativeQuoteQty": exec_report.get("Z"),
        "status": status,
        "price": exec_report.get("p"),
        "stopPrice": exec_report.get("P"),
        "pnl": float(pnl_value) if pnl_value is not None else None,
        "performance_pct": performance_pct,
        # "session_id": session_id, # No longer needed here, passed to save_order
        "created_at": (
            datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat()
            if timestamp
            else datetime.now(timezone.utc).isoformat()
        ),
        "closed_at": (
            datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat()
            if timestamp and status in ["FILLED", "CANCELED", "EXPIRED", "REJECTED"]
            else None
        ),
    }
    return formatted_order


def _handle_execution_report(data: dict):
    """Gère les mises à jour d'exécution d'ordre, met à jour DB et état."""
    order_id = data.get("i")
    symbol = data.get("s")
    side = data.get("S")
    order_type = data.get("o")
    status = data.get("X")
    client_order_id = data.get("c")
    reject_reason = data.get("r", "NONE")
    filled_qty_str = data.get("z", "0")
    filled_quote_qty_str = data.get("Z", "0")
    order_time = data.get("T")

    logger.info(
        f"Execution Report: ID={order_id}, ClientID={client_order_id}, Symbol={symbol}, Side={side}, Type={order_type}, Status={status}"
        + (
            f", FilledQty={filled_qty_str}, FilledQuoteQty={filled_quote_qty_str}"
            if status in ["FILLED", "PARTIALLY_FILLED"]
            else ""
        )
        + (f", Reason={reject_reason}" if status == "REJECTED" else "")
    )

    formatted_data_for_db = _format_execution_report_for_db(data)
    active_session_id = state_manager.get_active_session_id()  # Get session ID

    # Attempt to save to DB only if formatting was successful and session ID exists
    if formatted_data_for_db and active_session_id is not None:
        save_success = db.save_order(formatted_data_for_db, active_session_id)
        if save_success:
            broadcast_order_history_update()  # Broadcast history update
            # Check if the order status implies the trade/stats might have changed
            if status in ["FILLED", "CANCELED", "REJECTED", "EXPIRED"]:
                broadcast_stats_update(active_session_id)  # Broadcast stats update
        else:
            # Error already logged in save_order if it failed
            logger.error(
                f"DB save failed for order {order_id}, session {active_session_id}. History broadcast skipped."
            )
    elif not formatted_data_for_db:
        logger.error(
            f"Failed to format execution report for order {order_id}. DB save skipped."
        )
    else:  # session_id was None
        logger.error(
            f"Cannot save execution report for order {order_id}: No active session ID found in state manager."
        )

    # --- Now handle state updates based on the execution report ---
    state_updates = {}  # Initialize state updates dictionary *once*
    current_state = state_manager.get_state()
    current_open_order_id = current_state.get("open_order_id")
    current_status = current_state.get("status")
    is_in_position = current_state.get("in_position")

    if status not in ["NEW", "PARTIALLY_FILLED"] and current_open_order_id == order_id:
        logger.info(
            f"ExecutionReport: Clearing open order ID {order_id} (status: {status})."
        )
        state_updates["open_order_id"] = None
        state_updates["open_order_timestamp"] = None
        if status in ["CANCELED", "REJECTED", "EXPIRED"] and current_status in [
            "ENTERING",
            "EXITING",
        ]:
            state_updates["status"] = "RUNNING"
            if current_status == "EXITING":
                state_updates["in_position"] = True
            if current_status == "ENTERING" and client_order_id:
                state_manager.clear_pending_order_details(client_order_id)

    if status == "FILLED":
        try:
            filled_qty = Decimal(filled_qty_str)
            filled_quote_qty = Decimal(filled_quote_qty_str)

            if filled_qty > 0:
                avg_price = filled_quote_qty / filled_qty

                if (
                    side == "BUY"
                    and current_status == "ENTERING"
                    and not is_in_position
                ):
                    logger.info(
                        f"ExecutionReport (FILLED BUY): Entering position. AvgPrice={avg_price:.4f}, Qty={filled_qty}"
                    )
                    # --- Use stored last_entry_client_id to retrieve details ---
                    last_entry_id = state_manager.get_and_clear_last_entry_client_id()
                    logger.debug(
                        f"Attempting to retrieve pending details using last stored entry ClientID: {last_entry_id}"
                    )
                    pending_details = None
                    if last_entry_id:
                        pending_details = (
                            state_manager.get_and_clear_pending_order_details(
                                last_entry_id
                            )
                        )
                        logger.debug(
                            f"Retrieved pending details using {last_entry_id}: {pending_details}"
                        )
                    else:
                        logger.warning(
                            f"No last_entry_client_id was stored. Cannot retrieve pending details reliably for order {order_id} (API ClientID: {client_order_id})."
                        )
                    # --- End modification ---

                    sl_price = (
                        pending_details.get("sl_price") if pending_details else None
                    )
                    tp1_price = (
                        pending_details.get("tp1_price") if pending_details else None
                    )
                    tp2_price = (
                        pending_details.get("tp2_price") if pending_details else None
                    )
                    # Log warning using the API's client_order_id for reference
                    if sl_price is None and client_order_id:
                        logger.warning(
                            f"ExecutionReport (FILLED BUY): Could not retrieve pending SL/TP for API ClientID {client_order_id} (used stored ID: {last_entry_id})."
                        )

                    state_updates["in_position"] = True
                    state_updates["entry_details"] = {
                        "order_id": order_id,
                        "avg_price": avg_price,
                        "quantity": filled_qty,
                        "timestamp": order_time,
                        "side": side,
                        "highest_price": avg_price,
                        "lowest_price": avg_price,
                        "sl_price": sl_price,
                        "tp1_price": tp1_price,
                        "tp2_price": tp2_price,
                    }
                    state_updates["status"] = "RUNNING"
                    state_updates["open_order_id"] = None
                    state_updates["open_order_timestamp"] = None
                    logger.info(
                        f"StateManager updated: In Position, Entry Details: {state_updates['entry_details']}"
                    )

                elif side == "SELL" and current_status == "EXITING" and is_in_position:
                    logger.info(
                        f"ExecutionReport (FILLED SELL): Exiting position. AvgPrice={avg_price:.4f}, Qty={filled_qty}"
                    )
                    state_updates["in_position"] = False
                    state_updates["entry_details"] = None
                    state_updates["status"] = "RUNNING"
                    state_updates["open_order_id"] = None
                    state_updates["open_order_timestamp"] = None

            else:
                logger.warning(
                    f"ExecutionReport (FILLED): Order {order_id} (ClientID: {client_order_id}) has zero filled quantity?"
                )
                # Clear pending details using API's client_order_id just in case (might be redundant)
                if current_status == "ENTERING" and client_order_id:
                    state_manager.clear_pending_order_details(client_order_id)
                if current_status in ["ENTERING", "EXITING"]:
                    state_updates["status"] = "RUNNING"
                    if current_status == "EXITING":
                        state_updates["in_position"] = True

        except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
            logger.error(
                f"ExecutionReport (FILLED): Error processing order {order_id} (ClientID: {client_order_id}): {e}",
                exc_info=True,
            )
            # Clear pending details using API's client_order_id just in case (might be redundant)
            if current_status == "ENTERING" and client_order_id:
                state_manager.clear_pending_order_details(client_order_id)
            state_updates["status"] = "ERROR"

    if state_updates:
        state_manager.update_state(state_updates)
        # --- Added Broadcast ---
        # Broadcast the state update AFTER it has been applied by state_manager
        # update_state handles saving, but not broadcasting anymore
        broadcast_state_update()
        logger.debug("Broadcasted state update after handling execution report.")
        # --- End Added Broadcast ---


def _handle_account_position(data: dict):
    """Gère les mises à jour de balance (événement outboundAccountPosition)."""
    balances = data.get("B", [])
    state_updates = {}
    quote_asset = state_manager.get_state("quote_asset")
    base_asset = state_manager.get_state("base_asset")

    current_quote_balance = state_manager.get_state("available_balance")
    current_base_quantity = state_manager.get_state("symbol_quantity")

    for balance_info in balances:
        asset = balance_info.get("a")
        free_balance_str = balance_info.get("f")

        if asset and free_balance_str is not None:
            try:
                free_balance = Decimal(free_balance_str)
                if asset == quote_asset:
                    if abs(current_quote_balance - free_balance) > Decimal("1e-8"):
                        logger.info(
                            f"Account Position: {asset} balance updated to {free_balance:.4f}"
                        )
                        state_updates["available_balance"] = free_balance
                elif asset == base_asset:
                    if abs(current_base_quantity - free_balance) > Decimal("1e-12"):
                        logger.info(
                            f"Account Position: {asset} quantity updated to {free_balance:.8f}"
                        )
                        state_updates["symbol_quantity"] = free_balance
                        if free_balance <= 0 and state_manager.get_state("in_position"):
                            logger.warning(
                                f"Account Position: Base asset {asset} is now {free_balance}, but state was 'in_position'. Correcting state."
                            )
                            state_updates["in_position"] = False
                            state_updates["entry_details"] = None
                            if state_manager.get_state("status") == "EXITING":
                                state_updates["status"] = "RUNNING"
            except (InvalidOperation, TypeError):
                logger.warning(
                    f"Account Position: Could not convert balance for {asset}: '{free_balance_str}'"
                )

    if state_updates:
        state_manager.update_state(state_updates)
        # --- Added Broadcast ---
        # Broadcast the state update AFTER it has been applied by state_manager
        broadcast_state_update()
        logger.debug("Broadcasted state update after handling account position.")
        # --- End Added Broadcast ---


def _handle_balance_update(data: dict):
    """Gère les événements 'balanceUpdate' (moins fiable, informatif)."""
    asset = data.get("a")
    delta = data.get("d")
    clear_time = data.get("T")
    logger.debug(
        f"Balance Update Event: Asset={asset}, Delta={delta}, ClearTime={clear_time}"
    )

# --- Exports ---
__all__ = [
    "process_user_data_message",
]
