# /Users/davidmichels/Desktop/trading-bot/backend/bot_core.py
import logging
import os
import threading
import time
import collections
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any, Tuple, List
import dotenv
import json

dotenv.load_dotenv()

from binance.websocket.spot.websocket_stream import SpotWebsocketStreamClient
from binance.error import ClientError, ServerError

# --- Imports ---
from state_manager import state_manager
from config_manager import config_manager, SYMBOL
import binance_client_wrapper

# MODIFIÉ: Importer les handlers pour appeler execute_exit et cancel_scalping_order
import websocket_handlers
from websocket_utils import broadcast_state_update

logger = logging.getLogger(__name__)

KEEPALIVE_INTERVAL_SECONDS = 30 * 60

# --- Fonctions Helper pour Logique Sortie (Supprimées car centralisées dans websocket_handlers) ---
# _calculate_exit_quantity, _place_exit_order, _handle_exit_order_result sont supprimées.

# --- Fonctions Ordres Stratégie (Appelées par Handlers ou API) ---

def cancel_scalping_order(symbol: str, order_id: int):
    """Annule un ordre LIMIT ouvert."""
    logger.info(f"Attempting to cancel Order: {order_id} on {symbol}...")
    result = binance_client_wrapper.cancel_order(symbol=symbol, orderId=order_id)

    if result:
        status = result.get("status")
        logger.info(f"API Cancel Result for order {order_id}: Status={status}")
        # Rafraîchir l'historique
        logger.debug(
            f"cancel_scalping_order: Triggering history refresh for {symbol} via REST..."
        )
        threading.Thread(
            target=refresh_order_history_via_rest, args=(symbol, 50), daemon=True
        ).start()
        # L'état (open_order_id) sera mis à jour par _handle_execution_report
    else:
        logger.error(f"Failed API request to cancel order {order_id}.")


# --- Thread Principal Bot ---

def run_bot():
    """Thread principal (simplifié, la logique est dans les handlers WS)."""
    try:
        current_state = state_manager.get_state()
        strategy_type = config_manager.get_value("STRATEGY_TYPE")
        symbol = current_state.get("symbol")
        logger.info(f"Run Bot Thread: Started ({strategy_type}) for {symbol}")

        while not state_manager.get_state("stop_main_requested"):
            # La logique principale est maintenant déclenchée par les messages WebSocket
            # et traitée dans websocket_handlers. Ce thread peut rester simple.
            time.sleep(
                5
            )  # Dormir pour éviter 100% CPU, vérifier stop flag périodiquement

    except Exception as e:
        logger.critical("Run Bot Thread: Major error!", exc_info=True)
        state_manager.update_state({"status": "ERROR", "stop_main_requested": True})
        broadcast_state_update()
    finally:
        logger.info("Run Bot Thread: Finishing.")
        current_status = state_manager.get_state("status")
        if current_status not in ["STOPPING", "STOPPED", "ERROR"]:
            state_manager.update_state({"status": "STOPPED"})
            broadcast_state_update()
        if state_manager.get_state("main_thread") == threading.current_thread():
            state_manager.update_state({"main_thread": None})


# --- Thread Keepalive ---

def run_keepalive():
    """Thread pour renouveler le listenKey."""
    logger.info("Keepalive Thread: Started.")
    while not state_manager.get_state("stop_keepalive_requested"):
        listen_key = state_manager.get_state("listen_key")
        if listen_key:
            logger.debug(f"Keepalive Thread: Sending keepalive for {listen_key[:5]}...")
            success = binance_client_wrapper.renew_listen_key(listen_key)
            if not success:
                logger.error(
                    f"Keepalive Thread: Failed keepalive for {listen_key[:5]}. Stopping thread."
                )
                state_manager.update_state({"listen_key": None})
                break  # Sortir si échec
        else:
            logger.warning("Keepalive Thread: No listen_key found. Waiting 60s.")
            wait_time = 60
            for _ in range(wait_time):
                if state_manager.get_state("stop_keepalive_requested"):
                    break
                time.sleep(1)
            if state_manager.get_state("stop_keepalive_requested"):
                break
            continue

        wait_interval = KEEPALIVE_INTERVAL_SECONDS
        for _ in range(wait_interval):
            if state_manager.get_state("stop_keepalive_requested"):
                break
            time.sleep(1)
        if state_manager.get_state("stop_keepalive_requested"):
            break

    logger.info("Keepalive Thread: Finishing.")
    if state_manager.get_state("keepalive_thread") == threading.current_thread():
        state_manager.update_state({"keepalive_thread": None})


# --- Rafraîchissement Historique Ordres ---
def refresh_order_history_via_rest(symbol: Optional[str] = None, limit: int = 50):
    """Récupère l'historique récent via REST et met à jour StateManager."""
    if not symbol:
        symbol = state_manager.get_state("symbol")
    if not symbol:
        logger.error("refresh_order_history_via_rest: Symbol not available.")
        return

    logger.info(f"Refreshing order history for {symbol} via REST (limit={limit})...")
    try:
        all_orders_data = binance_client_wrapper.get_all_orders(
            symbol=symbol, limit=limit
        )
        if all_orders_data is None:
            logger.error("Failed to fetch order history via REST.")
            return
        # Remplace l'historique interne et diffuse la mise à jour
        state_manager.replace_order_history(all_orders_data)
        logger.info(f"Order history for {symbol} refreshed successfully via REST.")
    except Exception as e:
        logger.error(f"Error during REST order history refresh: {e}", exc_info=True)


# --- Fonctions Contrôle (Orchestration Démarrage/Arrêt) ---

def _initialize_client_and_config() -> bool:
    """Initialise client Binance et charge config."""
    logger.info("Start Core: Initializing Binance Client...")
    if binance_client_wrapper.get_client() is None:
        state_manager.update_state({"status": "ERROR"})
        broadcast_state_update()
        return False
    logger.info("Start Core: Binance Client initialized. Config loaded.")
    return True


def _load_and_prepare_state() -> bool:
    """Charge état persistant, récupère infos symbole/balances initiales."""
    logger.info("Start Core: Loading state & preparing initial data...")
    current_state = state_manager.get_state()  # Chargé à l'init du manager
    logger.info(
        f"Start Core: State loaded (in_position={current_state.get('in_position')})."
    )

    current_symbol = config_manager.get_value("SYMBOL", SYMBOL)
    symbol_info = binance_client_wrapper.get_symbol_info(current_symbol)
    if not symbol_info:
        logger.error(f"Start Core: Cannot retrieve info for symbol {current_symbol}.")
        state_manager.update_state({"status": "ERROR"})
        broadcast_state_update()
        return False

    # Mettre en cache symbol_info
    state_manager.update_symbol_info(symbol_info)

    base_asset = symbol_info.get("baseAsset")
    quote_asset = symbol_info.get("quoteAsset")
    if not base_asset or not quote_asset:
        logger.error(f"Start Core: Base/Quote asset missing for {current_symbol}.")
        state_manager.update_state({"status": "ERROR"})
        broadcast_state_update()
        return False

    initial_quote = binance_client_wrapper.get_account_balance(asset=quote_asset)
    initial_base = binance_client_wrapper.get_account_balance(asset=base_asset)

    # Utiliser Decimal pour les balances récupérées
    initial_quote_decimal = initial_quote if initial_quote is not None else Decimal("0.0")
    initial_base_decimal = initial_base if initial_base is not None else Decimal("0.0")

    state_updates = {
        "symbol": current_symbol,
        "base_asset": base_asset,
        "quote_asset": quote_asset,
        "available_balance": initial_quote_decimal,
        "symbol_quantity": initial_base_decimal,
    }

    # Vérification cohérence position/quantité
    loaded_in_position = current_state.get("in_position", False)
    loaded_entry_details = current_state.get("entry_details")
    fetched_base_qty = state_updates["symbol_quantity"]

    final_in_position = loaded_in_position
    final_entry_details = loaded_entry_details

    # Utiliser une petite tolérance pour la quantité base
    base_qty_tolerance = Decimal("1e-12")

    if loaded_in_position and fetched_base_qty <= base_qty_tolerance:
        logger.warning(
            f"Start Core: Consistency Check - In position but base qty ({fetched_base_qty}) <= tolerance. Forcing OUT."
        )
        final_in_position = False
        final_entry_details = None
    elif not loaded_in_position and fetched_base_qty > base_qty_tolerance:
        logger.warning(
            f"Start Core: Consistency Check - NOT in position but base qty ({fetched_base_qty}) > tolerance. Keeping OUT."
        )
        final_in_position = False
        final_entry_details = None
    elif loaded_in_position and not loaded_entry_details:
        logger.warning(
            "Start Core: Consistency Check - In position but no entry_details. Forcing OUT."
        )
        final_in_position = False
        final_entry_details = None

    state_updates["in_position"] = final_in_position
    state_updates["entry_details"] = final_entry_details

    state_manager.update_state(state_updates)
    logger.info(
        f"Start Core: Initial State - Symbol:{current_symbol}, Quote:{quote_asset}={state_updates['available_balance']:.4f}, Base:{base_asset}={state_updates['symbol_quantity']:.8f}, Position:{final_in_position}"
    )
    return True


def _prefetch_kline_history() -> bool:
    """Précharge historique klines pour SWING ou SCALPING2."""
    strategy_type = config_manager.get_value("STRATEGY_TYPE")
    if strategy_type not in ["SWING", "SCALPING2"]:
        logger.info(f"Start Core ({strategy_type}): Kline prefetch skipped.")
        state_manager.clear_kline_history()
        return True

    current_tf = config_manager.get_value("TIMEFRAME", "1m") # Utiliser TIMEFRAME
    required_limit = state_manager.get_required_klines()
    symbol = state_manager.get_state("symbol")

    logger.info(
        f"Start Core ({strategy_type}): Prefetching {required_limit} klines ({symbol} {current_tf})..."
    )
    initial_klines = binance_client_wrapper.get_klines(
        symbol=symbol, interval=current_tf, limit=required_limit
    )

    if initial_klines and len(initial_klines) >= required_limit:
        state_manager.resize_kline_history(required_limit)
        state_manager.replace_kline_history(initial_klines)
        logger.info(
            f"Start Core ({strategy_type}): Kline history prefetched ({len(initial_klines)})."
        )
        return True
    elif initial_klines:
         logger.warning(f"Start Core ({strategy_type}): Prefetched only {len(initial_klines)}/{required_limit} klines. Might be insufficient.")
         state_manager.resize_kline_history(required_limit)
         state_manager.replace_kline_history(initial_klines)
         return True # Continuer mais avec un avertissement
    else:
        logger.error(f"Start Core ({strategy_type}): Failed to prefetch klines.")
        state_manager.clear_kline_history()
        return False # Échec critique


# --- Suppression de _prefetch_kline_history_scalping2 (fusionné dans _prefetch_kline_history) ---


def _start_main_thread() -> bool:
    """Démarre le thread principal du bot."""
    logger.info("Start Core: Starting main bot thread...")
    if (
        state_manager.get_state("main_thread")
        and state_manager.get_state("main_thread").is_alive()
    ):
        logger.error("Start Core: Main thread already running.")
        return False

    new_main_thread = threading.Thread(
        target=run_bot, daemon=True, name="BotCoreThread"
    )
    state_manager.update_state(
        {"main_thread": new_main_thread, "stop_main_requested": False}
    )
    new_main_thread.start()
    time.sleep(0.5)

    if new_main_thread.is_alive():
        logger.info("Start Core: Main bot thread started.")
        return True
    else:
        logger.error("Start Core: Failed to start main bot thread.")
        state_manager.update_state({"main_thread": None, "status": "ERROR"})
        broadcast_state_update()
        return False


def _stop_main_thread(timeout: int = 5) -> bool:
    """Arrête le thread principal du bot."""
    main_thread = state_manager.get_state("main_thread")
    if main_thread and main_thread.is_alive():
        logger.info("Stop Core: Sending stop signal to main thread...")
        state_manager.update_state({"stop_main_requested": True})
        main_thread.join(timeout=timeout)
        if main_thread.is_alive():
            logger.warning(f"Stop Core: Main thread did not stop within {timeout}s.")
            return False
        else:
            logger.info("Stop Core: Main thread stopped.")
            state_manager.update_state({"main_thread": None})
            return True
    elif main_thread:
        logger.info("Stop Core: Main thread already stopped.")
        state_manager.update_state({"main_thread": None})
        return True
    else:
        logger.info("Stop Core: No main thread found.")
        return True


# --- Gestion WebSocket ---

def _handle_websocket_message(ws_client_instance, raw_msg: str):
    """Callback central pour messages WebSocket combinés."""
    try:
        combined_data = json.loads(raw_msg)
        if not isinstance(combined_data, dict):
            logger.warning(f"Decoded combined message is not a dict: {combined_data}")
            return

        stream_name = combined_data.get("stream")
        data = combined_data.get("data")

        if "result" in combined_data and "id" in combined_data:
            logger.info(
                f"WebSocket ACK received (ID: {combined_data['id']}): {combined_data['result']}"
            )
            return

        if not stream_name or not isinstance(data, dict):
            # logger.debug(f"Non-combined or invalid WS message: {combined_data}") # Verbeux
            return

    except json.JSONDecodeError:
        logger.warning(f"Failed to decode combined WS JSON: {raw_msg}")
        return
    except Exception as e:
        logger.error(
            f"Error pre-processing combined WS message: {e} - Msg: {raw_msg}",
            exc_info=True,
        )
        return

    # --- Routage vers Handlers Spécifiques ---
    try:
        event_type = data.get("e")
        if event_type:
            if event_type == "kline":
                websocket_handlers.process_kline_message(data)
            elif event_type in [
                "executionReport",
                "outboundAccountPosition",
                "balanceUpdate",
            ]:
                websocket_handlers.process_user_data_message(data)
            # Ajouter d'autres types d'événements si nécessaire
            # elif event_type == 'aggTrade': websocket_handlers.process_agg_trade_message(data)
            elif event_type == "error":
                logger.error(f"WS Application Error: {data.get('m', 'Unknown error')}")
        else:  # Pas d'event type 'e' -> bookTicker ou depth
            if "bookTicker" in stream_name:
                websocket_handlers.process_book_ticker_message(data)
            elif "depth" in stream_name:
                websocket_handlers.process_depth_message(data)
            # else: logger.warning(f"Unrecognized combined message without 'e': Stream={stream_name}") # Verbeux

    except Exception as e:
        logger.error(
            f"Error routing/processing combined WS message: {e} - Stream: {stream_name}",
            exc_info=True,
        )


def _stop_keepalive_thread(timeout: int = 5) -> bool:
    """Arrête le thread keepalive."""
    keepalive_thread = state_manager.get_state("keepalive_thread")
    if keepalive_thread and keepalive_thread.is_alive():
        logger.info("Stop Core: Sending stop signal to Keepalive thread...")
        state_manager.update_state({"stop_keepalive_requested": True})
        keepalive_thread.join(timeout=timeout)
        if keepalive_thread.is_alive():
            logger.warning(
                f"Stop Core: Keepalive thread did not stop within {timeout}s."
            )
            return False
        else:
            logger.info("Stop Core: Keepalive thread stopped.")
            state_manager.update_state({"keepalive_thread": None})
            return True
    elif keepalive_thread:
        logger.info("Stop Core: Keepalive thread already stopped.")
        state_manager.update_state({"keepalive_thread": None})
        return True
    else:
        logger.info("Stop Core: No Keepalive thread found.")
        return True


def _start_websockets() -> bool:
    """Démarre client WebSocket et souscrit aux streams combinés."""
    logger.info("Start Core: Starting WebSocket Client (Combined Mode)...")
    if state_manager.get_state("websocket_client"):
        logger.warning("Start Core: Existing WS client found. Stopping first...")
        _stop_websockets(is_partial_stop=True)

    listen_key = None
    try:
        use_testnet = config_manager.get_value("USE_TESTNET", True)
        current_symbol = state_manager.get_state("symbol")
        strategy_type = config_manager.get_value("STRATEGY_TYPE")
        current_config = config_manager.get_config()
        if not current_symbol:
            raise ValueError("Symbol missing in state.")

        # CORRECTION: Fournir l'URL de base, la bibliothèque ajoute /stream pour is_combined=True
        ws_stream_url = (
            "wss://testnet.binance.vision" # URL de base Testnet
            if use_testnet
            else "wss://stream.binance.com:9443" # URL de base Production (garder le port)
        )   
        ws_client = SpotWebsocketStreamClient(
            stream_url=ws_stream_url,
            on_message=_handle_websocket_message,
            on_close=lambda *args: logger.info("WebSocket Client: Connection closed."),
            on_error=lambda _, e: logger.error(f"WebSocket Client: Error: {e}"),
            is_combined=True, # Important pour l'URL /stream
        )
        state_manager.update_state({"websocket_client": ws_client})
        logger.info(f"WebSocket Client created (URL: {ws_stream_url})")

        stream_symbol_lower = current_symbol.lower()
        streams_to_subscribe = []

        # 1. Listen Key (User Data)
        logger.info("Start Core: Obtaining ListenKey...")
        listen_key = binance_client_wrapper.create_listen_key()
        if not listen_key:
            raise ConnectionError("Failed to obtain ListenKey.")
        state_manager.update_state({"listen_key": listen_key})
        logger.info(f"Start Core: ListenKey obtained: {listen_key[:5]}...")
        streams_to_subscribe.append(listen_key)

        # 2. Market Data Streams
        streams_to_subscribe.append(
            f"{stream_symbol_lower}@bookTicker"
        )  # Toujours utile

        if strategy_type == "SCALPING":
            depth_levels = current_config.get("SCALPING_DEPTH_LEVELS", 5)
            depth_speed = current_config.get("SCALPING_DEPTH_SPEED", "100ms")
            streams_to_subscribe.append(
                f"{stream_symbol_lower}@depth{depth_levels}@{depth_speed}"
            )
            logger.info("Start Core (SCALPING): Added bookTicker, depth streams.")

        elif strategy_type in ["SCALPING2", "SWING"]:
            current_tf = state_manager.get_state("timeframe")
            streams_to_subscribe.append(f"{stream_symbol_lower}@kline_{current_tf}")
            logger.info(
                f"Start Core ({strategy_type}): Added bookTicker, kline_{current_tf} streams."
            )

        # 3. Souscription
        if streams_to_subscribe:
            logger.info(f"Start Core: Subscribing to combined: {streams_to_subscribe}")
            ws_client.subscribe(stream=streams_to_subscribe, id=1)
            time.sleep(1)  # Attendre ACK potentiel
        else:
            logger.warning("Start Core: No streams to subscribe?")

        # 4. Démarrer Keepalive
        logger.info("Start Core: Starting Keepalive Thread...")
        if (
            state_manager.get_state("keepalive_thread")
            and state_manager.get_state("keepalive_thread").is_alive()
        ):
            logger.warning(
                "Start Core: Keepalive thread already running? Stopping first..."
            )
            _stop_keepalive_thread()
        new_keepalive_thread = threading.Thread(
            target=run_keepalive, daemon=True, name="KeepaliveThread"
        )
        state_manager.update_state(
            {
                "keepalive_thread": new_keepalive_thread,
                "stop_keepalive_requested": False,
            }
        )
        new_keepalive_thread.start()
        if not new_keepalive_thread.is_alive():
            raise ConnectionError("Failed to start Keepalive thread!")
        logger.info("Start Core: Keepalive thread started.")

        logger.info("Start Core: WebSockets and Keepalive started.")
        return True

    except (ValueError, ConnectionError, ClientError, ServerError) as e:
        logger.critical(
            f"Start Core: Error during WS/Keepalive startup: {e}", exc_info=True
        )
        if listen_key:
            binance_client_wrapper.close_listen_key(listen_key)
        _stop_websockets(is_partial_stop=True)
        state_manager.update_state({"status": "ERROR", "listen_key": None})
        broadcast_state_update()
        return False
    except Exception as e:
        logger.critical(
            f"Start Core: Unexpected error during WS/Keepalive startup: {e}",
            exc_info=True,
        )
        if listen_key:
            binance_client_wrapper.close_listen_key(listen_key)
        _stop_websockets(is_partial_stop=True)
        state_manager.update_state({"status": "ERROR", "listen_key": None})
        broadcast_state_update()
        return False


def _stop_websockets(is_partial_stop: bool = False) -> bool:
    """Arrête client WebSocket et thread keepalive."""
    log_prefix = "Stop Core (Partial):" if is_partial_stop else "Stop Core:"
    _stop_keepalive_thread()  # Arrêter keepalive d'abord
    ws_client = state_manager.get_state("websocket_client")
    if ws_client:
        logger.info(f"{log_prefix} Stopping WebSocket Client...")
        try:
            # Tenter de se désabonner avant d'arrêter (best effort)
            listen_key = state_manager.get_state("listen_key")
            if listen_key:
                 try: ws_client.unsubscribe(stream=[listen_key], id=99)
                 except Exception as unsub_e: logger.warning(f"Error unsubscribing listen key: {unsub_e}")
            ws_client.stop()
            time.sleep(0.5)
            logger.info(f"{log_prefix} WebSocket Client stop initiated.")
        except Exception as e:
            logger.error(f"{log_prefix} Error stopping WS Client: {e}", exc_info=True)
        finally:
            state_manager.update_state({"websocket_client": None})
            logger.info(f"{log_prefix} WebSocket Client reference cleared.")
        return True
    else:
        logger.info(f"{log_prefix} No active WebSocket Client found.")
        return True


# --- Fonctions Contrôle Publiques ---

def start_bot_core() -> tuple[bool, str]:
    """Fonction principale pour démarrer le bot."""
    logger.info("=" * 10 + " BOT START REQUESTED " + "=" * 10)
    current_status = state_manager.get_state("status")
    if current_status not in ["Arrêté", "STOPPED", "ERROR"]:
        logger.warning(
            f"Start Core: Attempted start while status is '{current_status}'."
        )
        return False, f"Bot is already {current_status}."

    state_manager.update_state({"status": "STARTING"})
    broadcast_state_update()
    state_manager.clear_realtime_data()

    if not _initialize_client_and_config():
        return False, "Échec initialisation client/config."
    if not _load_and_prepare_state():
        return False, "Échec chargement état/données initiales."
    if not _prefetch_kline_history(): # Gère SWING et SCALPING2
        state_manager.update_state({"status": "ERROR"})
        broadcast_state_update()
        return False, "Échec préchargement Klines (requis pour SWING/SCALPING2)."
    if not _start_websockets():
        return False, "Échec démarrage WebSockets."
    if not _start_main_thread():
        _stop_websockets(is_partial_stop=True)  # Nettoyer WS si thread principal échoue
        return False, "Échec démarrage thread principal."

    state_manager.update_state({"status": "RUNNING"})
    broadcast_state_update()
    logger.info(f"Start Core: Bot started successfully (Status: RUNNING).")
    return True, "Bot démarré avec succès."


def stop_bot_core(partial_cleanup: bool = False) -> tuple[bool, str]:
    """Fonction principale pour arrêter le bot."""
    log_prefix = "Stop Core (Partial):" if partial_cleanup else "Stop Core:"
    logger.info(f"{log_prefix} Stop requested...")
    current_status = state_manager.get_state("status")
    if not partial_cleanup and current_status in ["Arrêté", "STOPPED"]:
        logger.info(f"{log_prefix} Bot already stopped.")
        return False, "Bot déjà arrêté."

    if not partial_cleanup:
        state_manager.update_state({"status": "STOPPING"})
        broadcast_state_update()

    _stop_main_thread()
    _stop_websockets(is_partial_stop=partial_cleanup)

    listen_key_to_close = state_manager.get_state("listen_key")
    if listen_key_to_close:
        logger.info(f"{log_prefix} Closing ListenKey {listen_key_to_close[:5]}...")
        binance_client_wrapper.close_listen_key(listen_key_to_close)

    final_status = (
        "STOPPED" if not partial_cleanup else state_manager.get_state("status")
    )
    # Nettoyer l'état
    state_updates_on_stop = {
        "status": final_status,
        "stop_main_requested": False,
        "open_order_id": None,
        "open_order_timestamp": None,
        "listen_key": None,
        "websocket_client": None,
        "keepalive_thread": None,
        "stop_keepalive_requested": False,
        # Nettoyer aussi les clés temporaires
        "_temp_entry_sl": None,
        "_temp_entry_tp1": None,
        "_temp_entry_tp2": None,
    }
    state_manager.update_state(state_updates_on_stop)
    broadcast_state_update()

    if not partial_cleanup:
        logger.info(f"{log_prefix} Saving final state...")
        state_manager.save_persistent_data()

    logger.info(f"{log_prefix} Stop sequence completed. Final Status: {final_status}")
    return True, f"Bot arrêté (Status: {final_status})."


# --- Exports ---
__all__ = [
    # "execute_exit", # Centralisé dans websocket_handlers
    "run_bot",
    "start_bot_core",
    "stop_bot_core",
    "cancel_scalping_order",
    "refresh_order_history_via_rest",
]
