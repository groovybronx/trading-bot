# /Users/davidmichels/Desktop/trading-bot/backend/websocket_handlers.py
import logging
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np # Import numpy for NaN comparison if needed

# --- Gestionnaires et Wrapper ---
from state_manager import state_manager
from config_manager import config_manager
import binance_client_wrapper

# --- Utilitaires ---
from websocket_utils import (
    broadcast_state_update,
    broadcast_ticker_update,
    broadcast_signal_event,
    broadcast_order_history_update, # Ajouté pour refresh après ordre
)
from utils.order_utils import format_quantity, get_min_notional, check_min_notional, format_price

# --- Logique Stratégie Spécifique ---
# SWING
from strategies.swing_strategy import (
    calculate_indicators_and_signals as swing_calculate,
    check_entry_conditions as swing_check_entry,
    check_exit_conditions as swing_check_exit,
)
# SCALPING (Order Book)
from strategies.scalping_strategy import (
    check_entry_conditions as scalping_check_entry,
    check_strategy_exit_conditions as scalping_check_strategy_exit,
    # check_sl_tp est maintenant géré par _check_common_sl_tp
)
# SCALPING 2 (Indicateurs)
from strategies.scalping_strategy_2 import (
    calculate_indicators,
    check_long_conditions,
    check_short_conditions,
    calculate_dynamic_sl_tp,
    check_exit_conditions as scalping_2_check_exit,
)

# --- Core (pour annulation/refresh) ---
import bot_core # Garder pour cancel_scalping_order et refresh_order_history

logger = logging.getLogger(__name__)

# --- Fonctions d'exécution d'ordre (Encapsulation) ---

def _execute_order_thread(order_params: Dict[str, Any], action: str, **kwargs):
    """Thread pour passer un ordre (entrée ou sortie) via le wrapper."""
    symbol = order_params.get("symbol")
    side = order_params.get("side")
    order_type = order_params.get("order_type")
    qty_info = order_params.get("quantity") or order_params.get("quoteOrderQty")
    price_info = f" @ {order_params.get('price')}" if order_params.get("price") else ""

    log_msg = f"Thread Exec Order ({action}): {side} {qty_info} {symbol} ({order_type}{price_info})"
    logger.info(log_msg)

    # --- Récupérer les SL/TP passés via kwargs ---
    sl_price_from_signal = kwargs.get("sl_price")
    tp1_price_from_signal = kwargs.get("tp1_price")
    tp2_price_from_signal = kwargs.get("tp2_price")
    # --- Fin Récupération ---

    order_result = None
    try:
        # Ne plus pop les clés _temp_ ici

        # --- Ajouter un clientOrderId unique pour lier l'ordre aux SL/TP ---
        # Utiliser timestamp + action comme base pour l'ID client
        client_order_id = f"bot_{action.lower()}_{int(time.time()*1000)}"
        order_params_with_cid = order_params.copy()
        order_params_with_cid["newClientOrderId"] = client_order_id
        # --- Fin Ajout clientOrderId ---

        # --- Stocker temporairement les SL/TP associés à cet ID client ---
        # Utiliser un dictionnaire global ou une structure dans state_manager
        # Ici, exemple simple avec un dict global (attention à la gestion mémoire si beaucoup d'ordres échouent)
        # Une meilleure solution serait une structure dédiée dans state_manager
        if action == "ENTRY" and sl_price_from_signal is not None:
             state_manager.store_pending_order_details(client_order_id, {
                 "sl_price": sl_price_from_signal,
                 "tp1_price": tp1_price_from_signal,
                 "tp2_price": tp2_price_from_signal,
             })
             logger.debug(f"Stored pending SL/TP for clientOrderId {client_order_id}")
        # --- Fin Stockage temporaire ---

        order_result = binance_client_wrapper.place_order(**order_params_with_cid) # Envoyer avec ID client

        if order_result and order_result.get("orderId"):
            order_id = order_result["orderId"]
            status = order_result.get("status", "UNKNOWN")
            api_client_order_id = order_result.get("clientOrderId") # Récupérer l'ID client de la réponse API
            logger.info(f"Order Placement API Result ({action}): ID {order_id}, ClientID {api_client_order_id}, Status {status}")

            # Si ordre LIMIT, mettre à jour l'état avec l'ID ouvert
            if order_type == "LIMIT" and status == "NEW":
                state_manager.update_state({
                    "open_order_id": order_id,
                    "open_order_timestamp": int(time.time() * 1000),
                    "status": "ENTERING" if action == "ENTRY" else state_manager.get_state("status")
                })
                broadcast_state_update()
            # Si ordre échoue immédiatement
            elif status in ["REJECTED", "EXPIRED", "CANCELED"]:
                 logger.warning(f"Order {order_id} (ClientID: {api_client_order_id}, Action: {action}) failed immediately via API (Status: {status}).")
                 # Nettoyer les détails SL/TP en attente si l'ordre échoue
                 if action == "ENTRY" and api_client_order_id:
                      state_manager.clear_pending_order_details(api_client_order_id)
                 # Si on tentait d'entrer/sortir, revenir à RUNNING
                 current_status = state_manager.get_state("status")
                 if current_status in ["ENTERING", "EXITING"]:
                      state_updates = {"status": "RUNNING", "open_order_id": None, "open_order_timestamp": None}
                      state_manager.update_state(state_updates)
                      broadcast_state_update()

            # Rafraîchir l'historique après la tentative
            if symbol:
                 threading.Thread(target=bot_core.refresh_order_history_via_rest, args=(symbol, 50), daemon=True).start()

        else:
            logger.error(f"Order Placement FAILED ({action}) via API for {symbol}. No valid result/orderId. ClientID: {client_order_id}. Response: {order_result}")
            # Nettoyer les détails SL/TP en attente si l'ordre échoue
            if action == "ENTRY" and client_order_id:
                 state_manager.clear_pending_order_details(client_order_id)
            current_status = state_manager.get_state("status")
            if current_status in ["ENTERING", "EXITING"]:
                state_updates = {"status": "RUNNING", "open_order_id": None, "open_order_timestamp": None}
                state_manager.update_state(state_updates)
                broadcast_state_update()

    except Exception as e:
        logger.error(f"CRITICAL Error during {action} order placement thread for {symbol}: {e}", exc_info=True)
        # Nettoyer les détails SL/TP en attente si erreur critique
        client_order_id_on_error = order_params_with_cid.get("newClientOrderId") if 'order_params_with_cid' in locals() else None
        if action == "ENTRY" and client_order_id_on_error:
             state_manager.clear_pending_order_details(client_order_id_on_error)
        state_updates = {"status": "ERROR", "open_order_id": None, "open_order_timestamp": None}
        state_manager.update_state(state_updates)
        broadcast_state_update()

# MODIFIÉ: Accepter **kwargs
def execute_entry(order_params: Dict[str, Any], **kwargs):
    """Lance un thread pour passer un ordre d'entrée."""
    if order_params.get("order_type") != "LIMIT":
         state_manager.update_state({"status": "ENTERING"})
         broadcast_state_update()
    # Passer une copie des paramètres ET les kwargs (contenant SL/TP) au thread
    threading.Thread(target=_execute_order_thread, args=(order_params.copy(), "ENTRY"), kwargs=kwargs, daemon=True).start()

def execute_exit(reason: str):
    """Prépare et lance un thread pour passer un ordre MARKET de sortie."""
    current_state = state_manager.get_state()
    symbol = current_state.get("symbol")
    base_asset = current_state.get("base_asset")
    # Utiliser la quantité de entry_details si disponible et fiable, sinon l'état
    entry_details = current_state.get("entry_details")
    qty_in_details = entry_details.get("quantity") if entry_details else None
    qty_in_state = current_state.get("symbol_quantity", Decimal("0.0"))

    # Choisir la quantité la plus pertinente (celle de l'entrée est souvent plus précise)
    # Convertir en Decimal pour comparaison
    try:
        qty_to_sell_raw = Decimal(str(qty_in_details)) if qty_in_details is not None else qty_in_state
    except (InvalidOperation, TypeError):
        logger.error(f"execute_exit: Invalid quantity in state/details. Details: {qty_in_details}, State: {qty_in_state}")
        # Tenter de forcer la sortie de l'état si incohérent
        if current_state.get("in_position"):
             state_manager.update_state({"in_position": False, "entry_details": None, "status": "RUNNING"})
             broadcast_state_update()
        return

    if not current_state.get("in_position") or qty_to_sell_raw <= 0 or not symbol or not base_asset:
        logger.warning(f"execute_exit called (Reason: {reason}) but not in valid position for {symbol}. Qty: {qty_to_sell_raw}")
        # Assurer que l'état est cohérent
        if current_state.get("in_position"):
             state_manager.update_state({"in_position": False, "entry_details": None})
             broadcast_state_update()
        return

    logger.info(f"Attempting EXIT for {symbol} (Reason: {reason}). Base Qty: {qty_to_sell_raw}")
    state_manager.update_state({"status": "EXITING"}) # Mettre en état EXITING
    broadcast_state_update()

    try:
        symbol_info = state_manager.get_symbol_info()
        if not symbol_info:
            symbol_info = binance_client_wrapper.get_symbol_info(symbol)
            if symbol_info: state_manager.update_symbol_info(symbol_info)
            else:
                logger.error(f"EXIT Order: Failed to get symbol info for {symbol}. Aborting exit.")
                state_manager.update_state({"status": "ERROR"}) # Erreur critique
                broadcast_state_update()
                return

        # Formater la quantité pour la vente (MARKET SELL utilise la quantité BASE)
        formatted_quantity_to_sell = format_quantity(qty_to_sell_raw, symbol_info)

        if formatted_quantity_to_sell is None or formatted_quantity_to_sell <= 0:
            logger.error(f"EXIT Order: Calculated quantity to sell invalid ({formatted_quantity_to_sell}) after formatting for {symbol}. Raw: {qty_to_sell_raw}. Aborting.")
            # Forcer la sortie de l'état de position si la quantité est invalide
            state_manager.update_state({"in_position": False, "entry_details": None, "symbol_quantity": Decimal("0.0"), "status": "RUNNING"})
            broadcast_state_update()
            return

        # Vérifier min_notional pour l'ordre MARKET SELL
        # Nécessite le prix actuel (approximatif)
        ticker = state_manager.get_book_ticker()
        current_price = Decimal(ticker.get('b', '0')) # Utiliser Bid pour vendre
        min_notional = get_min_notional(symbol_info)

        if current_price <= 0:
             logger.warning(f"EXIT Order: Invalid current price ({current_price}) for min_notional check. Proceeding anyway...")
        elif not check_min_notional(formatted_quantity_to_sell, current_price, min_notional):
             logger.error(f"EXIT Order: Estimated notional ({formatted_quantity_to_sell * current_price:.4f}) < MIN_NOTIONAL ({min_notional:.4f}). Order might fail. Aborting exit.")
             # Revenir à RUNNING car on n'a pas pu sortir
             state_manager.update_state({"status": "RUNNING"})
             broadcast_state_update()
             return

        exit_order_params = {
            "symbol": symbol,
            "side": "SELL",
            "order_type": "MARKET",
            "quantity": formatted_quantity_to_sell, # Le wrapper convertira en str
        }

        # Lancer le thread pour exécuter l'ordre
        # Passer une copie des paramètres
        threading.Thread(target=_execute_order_thread, args=(exit_order_params.copy(), "EXIT"), daemon=True).start()

    except Exception as e:
        logger.error(f"CRITICAL Error preparing EXIT order for {symbol}: {e}", exc_info=True)
        state_manager.update_state({"status": "ERROR"})
        broadcast_state_update()


# --- Vérification SL/TP Centralisée ---
def _check_common_sl_tp(
    entry_details: Dict[str, Any],
    book_ticker: Dict[str, Any],
    current_config: Dict[str, Any],
) -> Optional[str]:
    """
    Vérifie Stop Loss et Take Profit (basé sur TP1).
    Utilisé par SCALPING et SWING.
    Retourne 'SL' ou 'TP' si atteint, sinon None. Utilise Decimal.
    """
    if not entry_details or not book_ticker: return None

    try:
        entry_price = Decimal(str(entry_details.get("avg_price", "0")))
        if entry_price <= 0: return None

        # Pour une position LONG: SL/TP déclenchés par le prix BID (prix de vente)
        current_price = Decimal(book_ticker.get("b", "0")) # Best Bid
        if current_price <= 0: return None

        # --- Stop Loss ---
        sl_frac = current_config.get("STOP_LOSS_PERCENTAGE", Decimal("0.005")) # Déjà Decimal
        stop_loss_price = entry_price * (Decimal(1) - sl_frac)
        if current_price <= stop_loss_price:
            logger.info(f"SL Hit: Bid {current_price:.4f} <= SL {stop_loss_price:.4f} (Entry: {entry_price:.4f})")
            return "SL"

        # --- Take Profit (basé sur TP1) ---
        tp1_frac = current_config.get("TAKE_PROFIT_1_PERCENTAGE", Decimal("0.01")) # Déjà Decimal
        take_profit_price = entry_price * (Decimal(1) + tp1_frac)

        if current_price >= take_profit_price:
            logger.info(f"TP Hit: Bid {current_price:.4f} >= TP1 {take_profit_price:.4f} (Entry: {entry_price:.4f})")
            return "TP" # Sortie totale au TP1

    except (InvalidOperation, TypeError, KeyError) as e:
        logger.error(f"Check SL/TP Error: {e}", exc_info=True)

    return None


# --- Handlers de Messages WebSocket ---

def process_book_ticker_message(msg: Dict[str, Any]):
    """Callback @bookTicker: Met à jour état, diffuse ticker, vérifie SL/TP, timeout, logique SCALPING."""
    try:
        if not isinstance(msg, dict) or "s" not in msg: return # Ignorer messages invalides

        symbol = msg.get("s")
        current_state = state_manager.get_state()
        current_config = config_manager.get_config() # Config interne (fractions)
        configured_symbol = current_state.get("symbol")

        if symbol != configured_symbol: return # Ignorer messages pour autres symboles

        # Mettre à jour le ticker dans state_manager (qui gère aussi highest/lowest price)
        state_manager.update_book_ticker(msg)
        broadcast_ticker_update(msg) # Diffuser le ticker brut

        strategy_type = current_config.get("STRATEGY_TYPE")
        is_in_position = current_state.get("in_position", False)
        entry_details = current_state.get("entry_details")
        current_status = current_state.get("status")
        open_order_id = current_state.get("open_order_id")
        open_order_timestamp = current_state.get("open_order_timestamp")

        # --- Logique commune ---
        # Vérifier timeout ordre LIMIT en attente
        if open_order_id and current_status == "ENTERING": # Seulement si on attend une entrée LIMIT
             check_limit_order_timeout(configured_symbol, open_order_id, open_order_timestamp, current_config)
             return # Ne rien faire d'autre si on attend un ordre

        # Si en position, vérifier SL/TP (commun à SCALPING et SWING)
        if is_in_position and entry_details and current_status == "RUNNING":
            # Pour SCALPING2, la sortie est gérée dans process_kline_message ou check_exit_conditions
            if strategy_type != "SCALPING2":
                 sl_tp_result = _check_common_sl_tp(entry_details, msg, current_config)
                 if sl_tp_result:
                      execute_exit(f"Hit ({sl_tp_result})")
                      return # Sortie initiée

        # --- Logique spécifique à la stratégie ---
        if current_status == "RUNNING": # N'agir que si le bot est prêt
            if strategy_type == "SCALPING":
                if is_in_position and entry_details:
                    # Vérifier sortie spécifique stratégie SCALPING (ex: imbalance)
                    depth_data = state_manager.get_depth()
                    if depth_data and scalping_check_strategy_exit(configured_symbol, entry_details, msg, depth_data, current_config):
                        execute_exit("Signal Scalping Strategy Exit")
                        return
                elif not is_in_position:
                    # Vérifier entrée SCALPING
                    depth_data = state_manager.get_depth()
                    if not depth_data: return
                    symbol_info = state_manager.get_symbol_info()
                    if not symbol_info: logger.warning("SCALPING Entry Check: Symbol info indisponible."); return

                    entry_order_params = scalping_check_entry(
                        configured_symbol, msg, depth_data, current_config,
                        current_state.get("available_balance", Decimal("0.0")), # Passer Decimal
                        symbol_info
                    )
                    if entry_order_params:
                        execute_entry(entry_order_params)
                        # Pas de return ici, on peut continuer à écouter

            # SWING n'utilise pas bookTicker pour les entrées/sorties indicateurs
            # SCALPING2 non plus

    except Exception as e:
        logger.critical(f"!!! CRITICAL Exception in process_book_ticker_message: {e} !!!", exc_info=True)


def process_depth_message(msg: Dict[str, Any]):
    """Callback @depth: Met à jour snapshot de profondeur."""
    try:
        if isinstance(msg, dict) and "lastUpdateId" in msg and "bids" in msg and "asks" in msg:
            state_manager.update_depth(msg)
        # else: logger.warning(f"Received unrecognized depth message format: {msg}") # Verbeux
    except Exception as e:
        logger.error(f"Error processing depth message: {e}", exc_info=True)


def process_agg_trade_message(msg: Dict[str, Any]):
    """Callback @aggTrade: Stocke trades récents (si utile)."""
    # Actuellement non utilisé activement par les stratégies fournies
    pass


def process_kline_message(msg: Dict[str, Any]):
    """Callback @kline: Met à jour historique et déclenche logique SWING et SCALPING2."""
    try:
        if not isinstance(msg, dict) or msg.get("e") != "kline" or "k" not in msg: return

        kline_data = msg["k"]
        symbol = kline_data.get("s")
        is_closed = kline_data.get("x", False)
        interval = kline_data.get("i")

        current_state = state_manager.get_state()
        current_config = config_manager.get_config()
        configured_symbol = current_state.get("symbol")
        configured_timeframe = current_state.get("timeframe")
        strategy_type = current_config.get("STRATEGY_TYPE")
        current_status = current_state.get("status")

        if symbol != configured_symbol or interval != configured_timeframe: return

        if is_closed and current_status == "RUNNING": # Agir seulement sur bougie fermée et si RUNNING
            logger.debug(f"Kline {symbol} ({interval}) CLOSED received.")
            formatted_kline = [
                kline_data.get("t"), kline_data.get("o"), kline_data.get("h"), kline_data.get("l"),
                kline_data.get("c"), kline_data.get("v"), kline_data.get("T"), kline_data.get("q"),
                kline_data.get("n"), kline_data.get("V"), kline_data.get("Q"), kline_data.get("B"),
            ]
            state_manager.add_kline(formatted_kline)
            full_kline_history = state_manager.get_kline_history_list()
            required_len = state_manager.get_required_klines()

            if len(full_kline_history) < required_len:
                logger.info(f"Kline WS ({strategy_type}): History ({len(full_kline_history)}/{required_len}) insufficient.")
                return

            # --- Logique SWING ---
            if strategy_type == "SWING":
                logger.debug(f"Kline WS (SWING): Calculating signals on {len(full_kline_history)} klines...")
                signals_df = swing_calculate(full_kline_history, current_config)
                if signals_df is None or signals_df.empty:
                    logger.warning("Kline WS (SWING): Failed to calculate signals.")
                    return
                # Utiliser la dernière ligne (bougie fermée) pour décision
                handle_swing_signals(signals_df.iloc[-1], current_state, current_config)

            # --- Logique SCALPING2 ---
            elif strategy_type == "SCALPING2":
                 # Convertir l'historique en DataFrame
                 df = pd.DataFrame(full_kline_history, columns=[
                     "timestamp", "open", "high", "low", "close", "volume", "close_time",
                     "quote_volume", "trades_count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"
                 ])
                 # Convertir en numérique/Decimal pour précision
                 numeric_cols = ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_volume", "taker_buy_quote_volume"]
                 for col in numeric_cols:
                     if col in df.columns: # Check if column exists
                         df[col] = pd.to_numeric(df[col], errors='coerce')
                         # Convertir en Decimal si numérique et non entièrement NaN
                         if pd.api.types.is_numeric_dtype(df[col]) and not df[col].isnull().all():
                             try:
                                 # CORRECTION: Utiliser une list comprehension pour la conversion Decimal
                                 new_col_values = []
                                 for val in df[col]:
                                     if pd.notna(val):
                                         try:
                                             new_col_values.append(Decimal(str(val)))
                                         except (InvalidOperation, TypeError):
                                             new_col_values.append(None) # Erreur conversion individuelle
                                             logger.warning(f"Could not convert value {val} in column {col} to Decimal.")
                                     else:
                                         new_col_values.append(None) # Garder None/NaN
                                 df[col] = new_col_values # Assigner la nouvelle liste
                             except Exception as conv_err: # Catch plus large au cas où
                                 logger.error(f"Error converting column {col} to Decimal using list comprehension: {conv_err}")
                                 df[col] = None # Mettre à None en cas d'erreur majeure
                         elif df[col].isnull().all():
                             # Si tout est NaN après to_numeric, garder comme object avec None
                             df[col] = df[col].astype(object)

                 df.dropna(subset=["open", "high", "low", "close", "volume"], inplace=True) # Garder dropna sur cols essentielles

                 if len(df) < required_len: # Re-vérifier après dropna
                      logger.info(f"Kline WS (SCALPING2): History ({len(df)}/{required_len}) insufficient after cleaning.")
                      return

                 logger.debug(f"Kline WS (SCALPING2): Calculating indicators on {len(df)} klines...")
                 df = calculate_indicators(df, current_config)

                 # Vérifier les conditions d'entrée/sortie sur les 2 dernières bougies
                 if len(df) >= 2:
                      handle_scalping2_signals(df.iloc[-2:], current_state, current_config)
                 else:
                      logger.warning("Kline WS (SCALPING2): Not enough data (>=2 rows) after indicator calculation.")

    except Exception as e:
        logger.critical(f"!!! CRITICAL Exception in process_kline_message: {e} !!!", exc_info=True)


def handle_swing_signals(latest_data: pd.Series, current_state: Dict[str, Any], current_config: Dict[str, Any]):
    """Gère les signaux pour la stratégie SWING."""
    is_in_position = current_state.get("in_position")
    configured_symbol = current_state.get("symbol")

    # CORRECTION: Vérifier si configured_symbol est valide
    if not configured_symbol:
        logger.error("handle_swing_signals: Configured symbol is missing in state.")
        return

    if not is_in_position:
        logger.debug("Kline WS (SWING): Checking entry conditions...")
        symbol_info = state_manager.get_symbol_info()
        if not symbol_info: logger.warning("SWING Entry Check: Symbol info indisponible."); return

        entry_order_params = swing_check_entry(
            latest_data, configured_symbol, current_config, # configured_symbol est maintenant vérifié
            current_state.get("available_balance", Decimal("0.0")), # Passer Decimal
            symbol_info
        )
        if entry_order_params:
            execute_entry(entry_order_params)

    elif is_in_position:
        logger.debug("Kline WS (SWING): Checking indicator exit conditions...")
        if swing_check_exit(latest_data, configured_symbol): # configured_symbol est maintenant vérifié
            execute_exit("Signal Indicateur SWING")


def handle_scalping2_signals(last_two_rows: pd.DataFrame, current_state: Dict[str, Any], current_config: Dict[str, Any]):
    """Gère les signaux pour la stratégie SCALPING2."""
    # ... (début de la fonction inchangé: vérifs symbol, symbol_info, current/prev row, current_price, min_notional) ...
    is_in_position = current_state.get("in_position")
    configured_symbol = current_state.get("symbol")
    if not configured_symbol: # ... (vérification inchangée)
        logger.error("handle_scalping2_signals: Configured symbol is missing in state.")
        return
    symbol_info = state_manager.get_symbol_info()
    if not symbol_info: # ... (vérification inchangée)
        logger.warning("SCALPING2 Signal Handling: Symbol info indisponible.")
        return

    try:
        current_row = last_two_rows.iloc[-1]
        prev_row = last_two_rows.iloc[-2]
        required_cols_for_logic = ["close", "low", "high", "atr"]
        if any(pd.isna(current_row.get(col)) for col in required_cols_for_logic): # ... (vérification inchangée)
            missing_or_nan = {col: current_row.get(col) for col in required_cols_for_logic if pd.isna(current_row.get(col))}
            logger.warning(f"SCALPING2 Signal Handling: Missing or NaN critical data in current row: {missing_or_nan}")
            return
        current_price = current_row["close"]
        min_notional = get_min_notional(symbol_info)

        if not is_in_position:
            long_signal, long_reason = check_long_conditions(current_row, prev_row)
            short_signal, short_reason = check_short_conditions(current_row, prev_row)
            broadcast_signal_event("entry", "LONG", bool(long_signal), long_reason or "Condition non remplie", {"price": float(current_price), "symbol": configured_symbol})
            broadcast_signal_event("entry", "SHORT", bool(short_signal), short_reason or "Condition non remplie", {"price": float(current_price), "symbol": configured_symbol})

            side = None
            if long_signal: side = "BUY"
            # elif short_signal: side = "SELL"

            if side:
                entry_price = current_price
                # Calculer SL/TP dynamiques
                sl_price, tp1_price, tp2_price = calculate_dynamic_sl_tp(
                    entry_price=entry_price, side=side, config=current_config,
                    recent_low=current_row["low"], recent_high=current_row["high"], atr_value=current_row["atr"]
                )

                # --- Calcul taille position (inchangé) ---
                risk_frac = current_config.get("RISK_PER_TRADE", Decimal("0.01"))
                available_balance = current_state.get("available_balance", Decimal("0.0"))
                capital_alloc_frac = current_config.get("CAPITAL_ALLOCATION", Decimal("1.0"))
                capital_to_use = available_balance * capital_alloc_frac
                capital_to_risk = capital_to_use * risk_frac
                risk_per_unit = abs(entry_price - sl_price)
                if risk_per_unit <= 0: # ... (vérification inchangée)
                     logger.warning(f"SCALPING2 Entry ({side}): Risque par unité nul ou négatif. SL={sl_price}, Entry={entry_price}")
                     return
                quantity_unformatted = capital_to_risk / risk_per_unit
                formatted_quantity = format_quantity(quantity_unformatted, symbol_info)
                if formatted_quantity is None or formatted_quantity <= 0: # ... (vérification inchangée)
                    logger.warning(f"SCALPING2 Entry ({side}): Quantité ({quantity_unformatted:.8f}) invalide après formatage.")
                    return
                if not check_min_notional(formatted_quantity, entry_price, min_notional): # ... (vérification inchangée)
                    logger.warning(f"SCALPING2 Entry ({side}): Notionnel ({formatted_quantity * entry_price:.4f}) < MIN_NOTIONAL ({min_notional:.4f}). Ordre non placé.")
                    return
                order_notional = formatted_quantity * entry_price
                if order_notional > capital_to_use * Decimal("1.01"): # ... (vérification inchangée)
                     logger.error(f"SCALPING2 Entry ({side}): Notionnel ({order_notional:.4f}) > capital alloué ({capital_to_use:.4f}). Erreur calcul?")
                     return
                # --- Fin Calcul taille position ---

                # --- SUPPRIMER la mise à jour de l'état temporaire ---
                # temp_state_updates = { ... }
                # state_manager.update_state(temp_state_updates)
                # logger.debug(f"SCALPING2: Stored temp SL/TP: {temp_state_updates}")
                # --- FIN SUPPRESSION ---

                # Préparer ordre MARKET
                entry_order_params = {
                    "symbol": configured_symbol,
                    "side": side,
                    "order_type": "MARKET",
                    "quantity": formatted_quantity,
                }
                logger.info(f"SCALPING2 Entry Signal: {side} @ {entry_price:.8f} (SL: {sl_price:.8f}, TP1: {tp1_price:.8f})")

                # --- MODIFIÉ: Passer SL/TP à execute_entry ---
                execute_entry(
                    entry_order_params,
                    sl_price=sl_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price
                )
                # --- FIN MODIFICATION ---

        elif is_in_position:
            # --- Vérification sortie (inchangée) ---
            entry_details = current_state.get("entry_details", {})
            position_duration = int(time.time()) - int(entry_details.get("timestamp", time.time() * 1000) / 1000)
            # --- MODIFICATION: Vérifier existence ET validité des clés ---
            sl_price_in_details = entry_details.get("sl_price")
            tp1_price_in_details = entry_details.get("tp1_price")
            if sl_price_in_details is None or tp1_price_in_details is None or sl_price_in_details <= 0 or tp1_price_in_details <= 0:
                 logger.warning(f"SCALPING2 Exit Check: SL/TP prices missing, None, or invalid in entry_details: {entry_details}. Cannot check exit.")
                 # Optionnel: Tenter de recalculer SL/TP ici si possible?
                 # Ou forcer une sortie si l'état est incohérent?
                 return # Pour l'instant, on ne fait rien si SL/TP manquent

            should_exit, exit_reason = scalping_2_check_exit(
                current_price=current_price,
                position_data=entry_details,
                config=current_config,
                position_duration_seconds=position_duration,
            )
            broadcast_signal_event("exit", entry_details.get("side", ""), bool(should_exit), exit_reason, {"price": float(current_price), "symbol": configured_symbol})
            if should_exit:
                execute_exit(f"SCALPING2 Exit: {exit_reason}")
            # --- Fin Vérification sortie ---

    except (KeyError, IndexError, ValueError, InvalidOperation, TypeError) as e:
         logger.error(f"Erreur dans handle_scalping2_signals: {e}", exc_info=True)

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
            _handle_balance_update(data) # Moins fiable que outboundAccountPosition
    except Exception as e:
        logger.error(f"Error processing User Data message (Type: {event_type}): {e}", exc_info=True)


def _handle_execution_report(data: dict):
    """Gère les mises à jour d'exécution d'ordre."""
    order_id = data.get("i")
    symbol = data.get("s")
    side = data.get("S")
    order_type = data.get("o")
    status = data.get("X")
    client_order_id = data.get("c") # Récupérer l'ID client de l'exécution
    reject_reason = data.get("r", "NONE")
    filled_qty_str = data.get("z", "0")
    filled_quote_qty_str = data.get("Z", "0")
    order_time = data.get("T")

    logger.info(
        f"Execution Report: ID={order_id}, ClientID={client_order_id}, Symbol={symbol}, Side={side}, Type={order_type}, Status={status}"
        + (f", FilledQty={filled_qty_str}, FilledQuoteQty={filled_quote_qty_str}" if status in ["FILLED", "PARTIALLY_FILLED"] else "")
        + (f", Reason={reject_reason}" if status == "REJECTED" else "")
    )

    state_manager.add_or_update_order_history(data)
    state_updates = {}
    current_state = state_manager.get_state()
    current_open_order_id = current_state.get("open_order_id")
    current_status = current_state.get("status")
    is_in_position = current_state.get("in_position")

    # Si un ordre ouvert est terminé
    if status not in ["NEW", "PARTIALLY_FILLED"] and current_open_order_id == order_id:
        logger.info(f"ExecutionReport: Clearing open order ID {order_id} (status: {status}).")
        state_updates["open_order_id"] = None
        state_updates["open_order_timestamp"] = None
        # Si ordre échoue pendant ENTERING/EXITING
        if status in ["CANCELED", "REJECTED", "EXPIRED"] and current_status in ["ENTERING", "EXITING"]:
            state_updates["status"] = "RUNNING"
            if current_status == "EXITING": state_updates["in_position"] = True
            # --- Nettoyer pending SL/TP si entrée échoue ---
            if current_status == "ENTERING" and client_order_id:
                 state_manager.clear_pending_order_details(client_order_id)
            # --- Fin Nettoyage ---

    # Si un ordre est complètement rempli
    if status == "FILLED":
        try:
            filled_qty = Decimal(filled_qty_str)
            filled_quote_qty = Decimal(filled_quote_qty_str)

            if filled_qty > 0:
                avg_price = filled_quote_qty / filled_qty

                # --- Entrée en position ---
                if side == "BUY" and current_status == "ENTERING" and not is_in_position:
                    logger.info(f"ExecutionReport (FILLED BUY): Entering position. AvgPrice={avg_price:.4f}, Qty={filled_qty}")

                    # --- Récupérer SL/TP via clientOrderId ---
                    pending_details = state_manager.get_and_clear_pending_order_details(client_order_id) if isinstance(client_order_id, str) else None
                    sl_price = pending_details.get("sl_price") if pending_details else None
                    tp1_price = pending_details.get("tp1_price") if pending_details else None
                    tp2_price = pending_details.get("tp2_price") if pending_details else None
                    if sl_price is None and client_order_id:
                         logger.warning(f"ExecutionReport (FILLED BUY): Could not retrieve pending SL/TP for ClientID {client_order_id}. SL/TP might be missing in entry_details.")
                    # --- Fin Récupération ---

                    state_updates["in_position"] = True
                    state_updates["entry_details"] = {
                        "order_id": order_id,
                        "avg_price": avg_price,
                        "quantity": filled_qty,
                        "timestamp": order_time,
                        "side": side,
                        "highest_price": avg_price,
                        "lowest_price": avg_price,
                        # --- Ajouter SL/TP récupérés ---
                        "sl_price": sl_price,
                        "tp1_price": tp1_price,
                        "tp2_price": tp2_price,
                        # --- Fin Ajout ---
                    }
                    state_updates["status"] = "RUNNING"
                    state_updates["open_order_id"] = None
                    state_updates["open_order_timestamp"] = None
                    # --- SUPPRIMER Nettoyage clés temporaires (fait par get_and_clear) ---
                    # state_updates["_temp_entry_sl"] = None
                    # ...
                    # --- FIN SUPPRESSION ---

                    logger.info(f"StateManager updated: In Position, Entry Details: {state_updates['entry_details']}")

                # --- Sortie de position ---
                elif side == "SELL" and current_status == "EXITING" and is_in_position:
                    logger.info(f"ExecutionReport (FILLED SELL): Exiting position. AvgPrice={avg_price:.4f}, Qty={filled_qty}")
                    state_updates["in_position"] = False
                    state_updates["entry_details"] = None
                    state_updates["status"] = "RUNNING"
                    state_updates["open_order_id"] = None
                    state_updates["open_order_timestamp"] = None

            else: # filled_qty <= 0
                logger.warning(f"ExecutionReport (FILLED): Order {order_id} (ClientID: {client_order_id}) has zero filled quantity?")
                # Nettoyer pending SL/TP si entrée échoue avec 0 rempli
                if current_status == "ENTERING" and client_order_id:
                     state_manager.clear_pending_order_details(client_order_id)
                # Revenir à l'état précédent
                if current_status in ["ENTERING", "EXITING"]:
                     state_updates["status"] = "RUNNING"
                     if current_status == "EXITING": state_updates["in_position"] = True

        except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
            logger.error(f"ExecutionReport (FILLED): Error processing order {order_id} (ClientID: {client_order_id}): {e}", exc_info=True)
            # Nettoyer pending SL/TP en cas d'erreur
            if current_status == "ENTERING" and client_order_id:
                 state_manager.clear_pending_order_details(client_order_id)
            state_updates["status"] = "ERROR"

    if state_updates:
        state_manager.update_state(state_updates)
        broadcast_state_update()

def _handle_account_position(data: dict):
    """Gère les mises à jour de balance (événement outboundAccountPosition)."""
    balances = data.get("B", [])
    state_updates = {}
    quote_asset = state_manager.get_state("quote_asset")
    base_asset = state_manager.get_state("base_asset")

    # Utiliser Decimal pour les comparaisons
    current_quote_balance = state_manager.get_state("available_balance") # Déjà Decimal
    current_base_quantity = state_manager.get_state("symbol_quantity")   # Déjà Decimal

    for balance_info in balances:
        asset = balance_info.get("a")
        free_balance_str = balance_info.get("f") # Solde disponible

        if asset and free_balance_str is not None:
            try:
                free_balance = Decimal(free_balance_str)
                if asset == quote_asset:
                    # Comparer avec une tolérance
                    if abs(current_quote_balance - free_balance) > Decimal("1e-8"): # Tolérance
                        logger.info(f"Account Position: {asset} balance updated to {free_balance:.4f}")
                        state_updates["available_balance"] = free_balance
                elif asset == base_asset:
                    if abs(current_base_quantity - free_balance) > Decimal("1e-12"): # Tolérance plus fine pour base asset
                        logger.info(f"Account Position: {asset} quantity updated to {free_balance:.8f}")
                        state_updates["symbol_quantity"] = free_balance
                        # --- Cohérence Position ---
                        # Si la quantité base devient <= 0 mais on est marqué "in_position", corriger.
                        if free_balance <= 0 and state_manager.get_state("in_position"):
                             logger.warning(f"Account Position: Base asset {asset} is now {free_balance}, but state was 'in_position'. Correcting state.")
                             state_updates["in_position"] = False
                             state_updates["entry_details"] = None
                             if state_manager.get_state("status") == "EXITING": # Si on attendait la sortie
                                  state_updates["status"] = "RUNNING"
                        # Si la quantité base devient > 0 mais on est marqué "not in_position", problème?
                        # Ceci peut arriver si l'ordre d'entrée est rempli avant que executionReport ne soit traité.
                        # On laisse executionReport gérer l'entrée en position.
            except (InvalidOperation, TypeError):
                logger.warning(f"Account Position: Could not convert balance for {asset}: '{free_balance_str}'")

    if state_updates:
        state_manager.update_state(state_updates)
        broadcast_state_update()


def _handle_balance_update(data: dict):
    """Gère les événements 'balanceUpdate' (moins fiable, informatif)."""
    asset = data.get("a")
    delta = data.get("d") # Changement de balance
    clear_time = data.get("T")
    logger.debug(f"Balance Update Event: Asset={asset}, Delta={delta}, ClearTime={clear_time}")
    # On ne met pas à jour l'état principal ici, on se fie à outboundAccountPosition


# --- Limit Order Timeout Check ---
def check_limit_order_timeout(
    symbol: str,
    order_id: Optional[int],
    order_timestamp: Optional[int],
    current_config: Dict[str, Any],
):
    """Vérifie si un ordre LIMIT ouvert a dépassé son timeout."""
    if not order_id or not order_timestamp: return

    timeout_ms = current_config.get("SCALPING_LIMIT_ORDER_TIMEOUT_MS") # Déjà int
    if timeout_ms is None or timeout_ms <= 0: return

    current_time_ms = int(time.time() * 1000)
    elapsed_ms = current_time_ms - order_timestamp

    if elapsed_ms > timeout_ms:
        logger.warning(f"LIMIT Order {order_id} exceeded timeout ({elapsed_ms}ms > {timeout_ms}ms). Attempting cancellation...")
        # Lancer l'annulation dans un thread séparé
        threading.Thread(target=bot_core.cancel_scalping_order, args=(symbol, order_id), daemon=True).start()
        # L'état sera mis à jour par executionReport (CANCELED)


# --- Exports ---
__all__ = [
    "process_book_ticker_message", "process_depth_message", "process_agg_trade_message",
    "process_kline_message", "process_user_data_message",
    "execute_entry", "execute_exit" # Exporter les fonctions d'exécution
]
