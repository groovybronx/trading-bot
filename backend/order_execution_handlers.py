import logging
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional

# --- Gestionnaires et Wrapper ---
from manager.state_manager import state_manager
from manager.config_manager import config_manager
import binance_client_wrapper

# --- Utilitaires ---
from utils.order_utils import (
    format_quantity,
    get_min_notional,
    check_min_notional,
    format_price, # Not used here, but might be useful later
)
from utils.websocket_utils import broadcast_state_update, broadcast_stats_update # Needed for state/stats updates after order handling

# --- Core (pour order_manager) ---
from manager.order_manager import order_manager

# --- MODIFIED: Import DB ---
import db
from datetime import datetime, timezone # Needed for DB formatting

logger = logging.getLogger(__name__)

# --- Fonctions d'exécution d'ordre (Encapsulation) ---

def cancel_scalping_order(symbol: str, order_id: int):
    """Annule un ordre LIMIT ouvert en utilisant OrderManager."""
    logger.info(
        f"Attempting to cancel Order: {order_id} on {symbol} via OrderManager..."
    )
    # Use the imported OrderManager instance to cancel the order
    success = order_manager.cancel_order(symbol=symbol, order_id=order_id)

    if success:
        logger.info(
            f"OrderManager reported successful cancellation initiation for order {order_id}."
        )
        # OrderManager handles logging and state updates internally now.
    else:
        logger.error(
            f"OrderManager reported failure trying to cancel order {order_id}."
        )

def _execute_order_thread(order_params: Dict[str, Any], action: str, **kwargs):
    """Thread pour passer un ordre (entrée ou sortie) via le wrapper ou order_manager."""
    symbol = order_params.get("symbol")
    side = order_params.get("side")
    order_type = order_params.get("order_type")
    qty_info = order_params.get("quantity") or order_params.get("quoteOrderQty")
    price_info = f" @ {order_params.get('price')}" if order_params.get("price") else ""

    log_msg = f"Thread Exec Order ({action}): {side} {qty_info} {symbol} ({order_type}{price_info})"
    logger.info(log_msg)

    current_config = config_manager.get_config()
    cooldown_ms = current_config.get("ORDER_COOLDOWN_MS", 0)
    last_order_ts = state_manager.get_last_order_timestamp() or 0
    now_ms = int(time.time() * 1000)
    if cooldown_ms > 0 and (now_ms - last_order_ts) < cooldown_ms:
        logger.warning(
            f"COOLDOWN GLOBAL ACTIF: {cooldown_ms - (now_ms - last_order_ts)}ms restants avant nouvel ordre. Ordre ignoré."
        )
        return

    # --- Moved SL/TP retrieval and storage EARLIER ---
    # Récupérer SL/TP depuis order_params (fourni par la stratégie)
    sl_price = order_params.get("sl_price")
    tp1_price = order_params.get("tp1_price")
    tp2_price = order_params.get("tp2_price")

    # Générer l'ID client
    client_order_id = f"bot_{action.lower()}_{int(time.time()*1000)}"

    # Stocker les détails SL/TP IMMÉDIATEMENT si c'est une entrée et que SL est valide
    # ET stocker l'ID client généré dans le state manager
    pending_details_stored = False
    if action == "ENTRY":
        # Convertir en Decimal pour la vérification, si ce n'est pas déjà fait
        try:
            sl_price_dec = Decimal(str(sl_price)) if sl_price is not None else None
        except (InvalidOperation, TypeError):
            sl_price_dec = None
            logger.warning(
                f"Could not convert sl_price '{sl_price}' to Decimal for validation."
            )

        if sl_price_dec is not None and sl_price_dec > 0:
            state_manager.store_pending_order_details(
                client_order_id,
                {
                    "sl_price": sl_price,  # Stocker la valeur originale (probablement float)
                    "tp1_price": tp1_price,
                    "tp2_price": tp2_price,
                },
            )
            pending_details_stored = True
            state_manager.set_last_entry_client_id(
                client_order_id
            )  # Store the generated ID
            logger.debug(
                f"Stored pending SL/TP and last_entry_client_id for {client_order_id} (SL: {sl_price}, TP1: {tp1_price}, TP2: {tp2_price})"
            )
        else:
            logger.debug(
                f"SL price invalid ({sl_price}) or not found in order_params for ENTRY action, ClientID {client_order_id}. Not storing pending details or last_entry_client_id."
            )
            state_manager.set_last_entry_client_id(
                None
            )  # Ensure it's cleared if not stored
    # --- End moved section ---

    order_result = None
    order_params_with_cid = order_params.copy()
    # Remove SL/TP from params sent to API/OrderManager if they exist, they are handled internally
    order_params_with_cid.pop("sl_price", None)
    order_params_with_cid.pop("tp1_price", None)
    order_params_with_cid.pop("tp2_price", None)
    order_params_with_cid["newClientOrderId"] = client_order_id

    state_manager.set_last_order_timestamp(now_ms)

    try:
        # Use order_manager to place the order
        qty_float = (
            float(order_params_with_cid["quantity"])
            if "quantity" in order_params_with_cid
            else None
        )
        price_float = (
            float(order_params_with_cid["price"])
            if "price" in order_params_with_cid
            and order_params_with_cid["price"] is not None
            else None
        )
        quote_qty_float = (
            float(order_params_with_cid["quoteOrderQty"])
            if "quoteOrderQty" in order_params_with_cid
            else None
        )

        if (
            order_params_with_cid["order_type"] == "MARKET"
            and order_params_with_cid["side"] == "BUY"
            and quote_qty_float is not None
        ):
            logger.warning(
                f"Market BUY with quoteOrderQty detected. Using direct binance_client_wrapper.place_order for ClientID {client_order_id}."
            )
            order_result = binance_client_wrapper.place_order(**order_params_with_cid)
            # --- Added Logging for ClientID comparison ---
            if order_result:
                api_returned_cid = order_result.get("clientOrderId")
                logger.info(
                    f"MARKET BUY Direct Call: Generated ClientID='{client_order_id}', API Returned ClientID='{api_returned_cid}'"
                )
            else:
                logger.warning(
                    f"MARKET BUY Direct Call: No result returned from API for Generated ClientID='{client_order_id}'"
                )
            # --- End Added Logging ---
        elif qty_float is not None:
            order_result = order_manager.place_order(
                symbol=order_params_with_cid["symbol"],
                side=order_params_with_cid["side"],
                order_type=order_params_with_cid["order_type"],
                quantity=qty_float,
                price=price_float,
            )
        else:
            logger.error(
                f"Order Placement ({action}): Invalid parameters for OrderManager. Qty: {qty_float}, Price: {price_float}, QuoteQty: {quote_qty_float}"
            )
            order_result = None

        if order_result and order_result.get("orderId"):
            order_id = order_result["orderId"]
            status = order_result.get("status", "UNKNOWN")
            api_client_order_id = order_result.get("clientOrderId")
            logger.info(
                f"Order Placement API Result ({action}): ID {order_id}, ClientID {api_client_order_id}, Status {status}"
            )

            if order_type == "LIMIT" and status == "NEW":
                state_manager.update_state(
                    {
                        "open_order_id": order_id,
                        "open_order_timestamp": int(time.time() * 1000),
                        "status": (
                            "ENTERING"
                            if action == "ENTRY"
                            else state_manager.get_state("status")
                        ),
                    }
                )
                broadcast_state_update() # Broadcast state change
            elif status in ["REJECTED", "EXPIRED", "CANCELED"]:
                logger.warning(
                    f"Order {order_id} (ClientID: {api_client_order_id}, Action: {action}) failed immediately via API (Status: {status})."
                )
                # --- Cleanup pending details AND last_entry_client_id if order failed immediately ---
                if (
                    action == "ENTRY" and pending_details_stored
                ):  # Check if we stored details
                    state_manager.clear_pending_order_details(
                        client_order_id
                    )  # Use generated client_order_id
                    state_manager.set_last_entry_client_id(None)  # Clear stored ID
                    logger.debug(
                        f"Cleared pending details and last_entry_client_id for failed order ClientID: {client_order_id}"
                    )
                # --- End Cleanup ---
                current_status = state_manager.get_state("status")
                if current_status in ["ENTERING", "EXITING"]:
                    state_updates = {
                        "status": "RUNNING",
                        "open_order_id": None,
                        "open_order_timestamp": None,
                    }
                    state_manager.update_state(state_updates)
                    broadcast_state_update() # Broadcast state change

        else:
            logger.error(
                f"Order Placement FAILED ({action}) via API for {symbol}. No valid result/orderId. ClientID: {client_order_id}. Response: {order_result}"
            )
            # --- Cleanup pending details AND last_entry_client_id if order placement failed completely ---
            if (
                action == "ENTRY" and pending_details_stored
            ):  # Check if we stored details
                state_manager.clear_pending_order_details(
                    client_order_id
                )  # Use generated client_order_id
                state_manager.set_last_entry_client_id(None)  # Clear stored ID
                logger.debug(
                    f"Cleared pending details and last_entry_client_id for failed order placement ClientID: {client_order_id}"
                )
            # --- End Cleanup ---
            current_status = state_manager.get_state("status")
            if current_status in ["ENTERING", "EXITING"]:
                state_updates = {
                    "status": "RUNNING",
                    "open_order_id": None,
                    "open_order_timestamp": None,
                }
                state_manager.update_state(state_updates)
                broadcast_state_update() # Broadcast state change

    except Exception as e:
        logger.error(
            f"CRITICAL Error during {action} order placement thread for {symbol}: {e}",
            exc_info=True,
        )
        # --- Cleanup pending details AND last_entry_client_id on exception ---
        if action == "ENTRY" and pending_details_stored:  # Check if we stored details
            state_manager.clear_pending_order_details(
                client_order_id
            )  # Use generated client_order_id
            state_manager.set_last_entry_client_id(None)  # Clear stored ID
            logger.debug(
                f"Cleared pending details and last_entry_client_id due to exception for ClientID: {client_order_id}"
            )
        # --- End Cleanup ---
        state_updates = {
            "status": "ERROR",
            "open_order_id": None,
            "open_order_timestamp": None,
        }
        state_manager.update_state(state_updates)
        broadcast_state_update() # Broadcast state change


def execute_entry(order_params: Dict[str, Any], **kwargs):
    """Lance un thread pour passer un ordre d'entrée."""
    # Update state immediately for non-LIMIT orders, thread will handle LIMIT status
    if order_params.get("order_type") != "LIMIT":
         state_manager.update_state({"status": "ENTERING"})
         broadcast_state_update() # Broadcast state change

    threading.Thread(
        target=_execute_order_thread,
        args=(order_params.copy(), "ENTRY"),
        kwargs=kwargs,
        daemon=True,
    ).start()


def execute_exit(reason: str):
    """Prépare et lance un thread pour passer un ordre MARKET de sortie."""
    current_state = state_manager.get_state()
    symbol = current_state.get("symbol")
    base_asset = current_state.get("base_asset")
    entry_details = current_state.get("entry_details")
    qty_in_details = entry_details.get("quantity") if entry_details else None
    qty_in_state = current_state.get("symbol_quantity", Decimal("0.0"))

    try:
        qty_to_sell_raw = (
            Decimal(str(qty_in_details)) if qty_in_details is not None else qty_in_state
        )
    except (InvalidOperation, TypeError):
        logger.error(
            f"execute_exit: Invalid quantity in state/details. Details: {qty_in_details}, State: {qty_in_state}"
        )
        if current_state.get("in_position"):
            state_manager.update_state(
                {"in_position": False, "entry_details": None, "status": "RUNNING"}
            )
            broadcast_state_update() # Broadcast state change
        return

    if (
        not current_state.get("in_position")
        or qty_to_sell_raw <= 0
        or not symbol
        or not base_asset
    ):
        logger.warning(
            f"execute_exit called (Reason: {reason}) but not in valid position for {symbol}. Qty: {qty_to_sell_raw}"
        )
        if current_state.get("in_position"):
            state_manager.update_state({"in_position": False, "entry_details": None})
            broadcast_state_update() # Broadcast state change
        return

    logger.info(
        f"Attempting EXIT for {symbol} (Reason: {reason}). Base Qty: {qty_to_sell_raw}"
    )
    state_manager.update_state({"status": "EXITING"})
    broadcast_state_update() # Broadcast state change

    try:
        symbol_info = state_manager.get_symbol_info()
        if not symbol_info:
            symbol_info = binance_client_wrapper.get_symbol_info(symbol)
            if symbol_info:
                state_manager.update_symbol_info(symbol_info)
            else:
                logger.error(
                    f"EXIT Order: Failed to get symbol info for {symbol}. Aborting exit."
                )
                state_manager.update_state({"status": "ERROR"})
                broadcast_state_update() # Broadcast state change
                return

        formatted_quantity_to_sell = format_quantity(qty_to_sell_raw, symbol_info)

        if formatted_quantity_to_sell is None or formatted_quantity_to_sell <= 0:
            logger.error(
                f"EXIT Order: Calculated quantity to sell invalid ({formatted_quantity_to_sell}) after formatting for {symbol}. Raw: {qty_to_sell_raw}. Aborting."
            )
            state_manager.update_state(
                {
                    "in_position": False,
                    "entry_details": None,
                    "symbol_quantity": Decimal("0.0"),
                    "status": "RUNNING",
                }
            )
            broadcast_state_update() # Broadcast state change
            return

        ticker = state_manager.get_book_ticker()
        current_price = Decimal(ticker.get("a", "0"))
        min_notional = get_min_notional(symbol_info)

        if current_price <= 0:
            logger.warning(
                f"EXIT Order: Invalid current price ({current_price}) for min_notional check. Proceeding anyway..."
            )
        elif not check_min_notional(
            formatted_quantity_to_sell, current_price, min_notional
        ):
            logger.error(
                f"EXIT Order: Estimated notional ({formatted_quantity_to_sell * current_price:.4f}) < MIN_NOTIONAL ({min_notional:.4f}). Order might fail. Aborting exit."
            )
            state_manager.update_state({"status": "RUNNING"})
            broadcast_state_update() # Broadcast state change
            return

        exit_order_params = {
            "symbol": symbol,
            "side": "SELL",
            "order_type": "MARKET",
            "quantity": formatted_quantity_to_sell,
        }

        threading.Thread(
            target=_execute_order_thread,
            args=(exit_order_params.copy(), "EXIT"),
            daemon=True,
        ).start()

    except Exception as e:
        logger.error(
            f"CRITICAL Error preparing EXIT order for {symbol}: {e}", exc_info=True
        )
        state_manager.update_state({"status": "ERROR"})
        broadcast_state_update() # Broadcast state change


# --- Timeout pour Ordres LIMIT ---
def check_limit_order_timeout(
    symbol: str,
    order_id: Optional[int],
    order_timestamp: Optional[int],
    current_config: Dict[str, Any],
):
    """Vérifie si un ordre LIMIT ouvert a dépassé son timeout."""
    if not order_id or not order_timestamp:
        return

    timeout_ms = current_config.get("SCALPING_LIMIT_ORDER_TIMEOUT_MS")
    if timeout_ms is None or timeout_ms <= 0:
        return

    current_time_ms = int(time.time() * 1000)
    elapsed_ms = current_time_ms - order_timestamp

    if elapsed_ms > timeout_ms:
        logger.warning(
            f"LIMIT Order {order_id} exceeded timeout ({elapsed_ms}ms > {timeout_ms}ms). Attempting cancellation..."
        )
        threading.Thread(
            target=cancel_scalping_order, args=(symbol, order_id), daemon=True
        ).start()

# --- Exports ---
__all__ = [
    "execute_entry",
    "execute_exit",
    "check_limit_order_timeout",
    "cancel_scalping_order", # Exporting this as it's called from check_limit_order_timeout
]
