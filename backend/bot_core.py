# /Users/davidmichels/Desktop/trading-bot/backend/bot_core.py
import logging
import threading
import time
import collections
import queue # <-- FIX: Import queue module
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any

from binance import ThreadedWebsocketManager

# Importer état, config, locks
from state_manager import (
    bot_state, config_lock, kline_history, kline_history_lock,
    save_data, load_data, latest_price_queue # <-- FIX: Add latest_price_queue
)
from config_manager import bot_config, SYMBOL, TIMEFRAME_CONSTANT_MAP, config
# Importer le wrapper client et la stratégie
import binance_client_wrapper
import strategy
# Importer les handlers WS pour les passer au manager
import websocket_handlers

logger = logging.getLogger()

# --- Logique de Sortie ---
# (execute_exit function remains unchanged)
def execute_exit(reason: str) -> Optional[Dict[str, Any]]:
    """
    Fonction centralisée pour sortir d'une position.
    Appelée par SL/TP (ticker) ou signal indicateur (kline).
    """
    order_details = None
    performance_pct = None
    should_save = False
    symbol_to_exit = bot_state.get("symbol", SYMBOL) # Utiliser le symbole de l'état

    with config_lock: # Protéger l'accès à bot_state
        if not bot_state.get("in_position"):
            logger.debug(f"Execute_exit ({reason}): Ignoré car pas en position.")
            return None

        logger.info(f"Execute_exit: Déclenchement sortie pour raison: {reason}")
        entry_details_copy = bot_state.get("entry_details")
        # Utiliser la quantité de l'entrée si disponible, sinon la quantité en state (moins fiable)
        qty_to_sell = entry_details_copy.get("quantity") if entry_details_copy else bot_state.get("symbol_quantity", 0.0)

        if qty_to_sell is None or qty_to_sell <= 0:
            logger.error(f"Execute_exit: Quantité à vendre invalide ({qty_to_sell}). Sortie annulée.")
            return None

        symbol_info = binance_client_wrapper.get_symbol_info(symbol_to_exit)
        if not symbol_info:
             logger.error(f"Execute_exit: Impossible récupérer symbol_info pour {symbol_to_exit}. Sortie annulée.")
             return None

        formatted_qty_to_sell = strategy.format_quantity(qty_to_sell, symbol_info)
        if formatted_qty_to_sell <= 0:
            logger.error(f"Execute_exit: Quantité formatée invalide ({formatted_qty_to_sell}). Sortie annulée.")
            return None

        logger.info(f"Execute_exit: Tentative vente MARKET de {formatted_qty_to_sell} {symbol_to_exit}...")
        order_details = binance_client_wrapper.place_order(
            symbol=symbol_to_exit, side='SELL', quantity=formatted_qty_to_sell, order_type='MARKET'
        )

        if order_details:
            logger.info(f"Execute_exit: Ordre VENTE placé. OrderId: {order_details.get('orderId')}")
            # Calcul performance
            if entry_details_copy:
                try:
                    exit_qty = float(order_details.get('executedQty', 0))
                    exit_quote_qty = float(order_details.get('cummulativeQuoteQty', 0))
                    entry_price = entry_details_copy.get('avg_price')
                    if exit_qty > 0 and entry_price is not None and entry_price > 0:
                        avg_exit_price = exit_quote_qty / exit_qty
                        performance_pct = ((avg_exit_price / entry_price) - 1) * 100
                        logger.info(f"Execute_exit: Performance calculée: {performance_pct:.2f}%")
                    else: logger.warning("Execute_exit: Impossible calculer perf (données sortie/entrée invalides).")
                except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
                    logger.error(f"Execute_exit: Erreur calcul perf: {e}")
            else: logger.warning("Execute_exit: Détails entrée manquants pour calcul perf.")

            # Mise à jour état
            bot_state["in_position"] = False
            bot_state["entry_details"] = None
            should_save = True # Sauvegarder état et historique

            # Ajout à l'historique
            try:
                simplified_order = {
                    "timestamp": order_details.get('transactTime', int(time.time() * 1000)),
                    "orderId": order_details.get('orderId'), "symbol": order_details.get('symbol'),
                    "side": order_details.get('side'), "type": order_details.get('type'),
                    "origQty": order_details.get('origQty'), "executedQty": order_details.get('executedQty'),
                    "cummulativeQuoteQty": order_details.get('cummulativeQuoteQty'),
                    "price": order_details.get('price'), "status": order_details.get('status'),
                    "performance_pct": performance_pct
                }
                bot_state['order_history'].append(simplified_order)
                # Limiter taille historique
                max_len = bot_state.get('max_history_length', 100)
                if len(bot_state['order_history']) > max_len:
                    bot_state['order_history'] = bot_state['order_history'][-max_len:]
                logger.info(f"Execute_exit: Ordre sortie {simplified_order.get('orderId', 'N/A')} ajouté historique.")
                # --- AJOUT POUR RAFRAICHISSEMENT ---
                logger.info("EVENT:ORDER_HISTORY_UPDATED")
                if performance_pct is not None: logger.info(f"  Performance enregistrée: {performance_pct:.2f}%")
            except Exception as hist_err:
                logger.error(f"Execute_exit: Erreur ajout ordre sortie à historique: {hist_err}")

            logger.info("Execute_exit: Mise à jour soldes via User Data Stream attendue.")
        else:
            logger.error(f"Execute_exit: Échec placement ordre VENTE pour {symbol_to_exit}.")
            should_save = False # Ne pas sauvegarder si l'ordre échoue

    # Sauvegarder en dehors du lock principal
    if should_save:
        if not save_data():
             logger.error("Execute_exit: Echec sauvegarde état après sortie !")

    return order_details


# --- Thread Keepalive User Data Stream ---
# (run_keepalive function remains unchanged)
def run_keepalive():
    """Boucle pour envoyer périodiquement des keepalives pour le listenKey."""
    logger.info("Keepalive Thread: Démarrage.")
    local_listen_key = None
    with config_lock:
        local_listen_key = bot_state.get('listen_key')

    if not local_listen_key:
        logger.error("Keepalive Thread: ListenKey non trouvé. Arrêt.")
        return

    keepalive_interval_seconds = 30 * 60 # Toutes les 30 minutes

    while True:
        stop_req = False
        with config_lock: stop_req = bot_state.get("stop_keepalive_requested", False)
        if stop_req: break

        try:
            success = binance_client_wrapper.keepalive_user_data_stream(local_listen_key)
            if success: logger.debug(f"Keepalive Thread: Keepalive réussi pour {local_listen_key[:5]}...")
            else: logger.error(f"Keepalive Thread: Échec keepalive pour {local_listen_key[:5]}... Clé expirée?")

            # Attente intelligente vérifiant l'arrêt
            wait_start_time = time.time()
            while time.time() - wait_start_time < keepalive_interval_seconds:
                with config_lock: stop_req_inner = bot_state.get("stop_keepalive_requested", False)
                if stop_req_inner: break
                time.sleep(1) # Vérifier chaque seconde
            if stop_req_inner: break # Sortir de la boucle while principale si arrêt demandé pendant l'attente

        except Exception as e:
            logger.exception(f"Keepalive Thread: Erreur inattendue: {e}")
            time.sleep(60) # Pause après erreur

    logger.info("Keepalive Thread: Arrêt.")


# --- Boucle Principale du Bot (Thread) ---
# (run_bot function remains unchanged)
def run_bot():
    """
    Boucle principale du thread du bot. Initialise et attend l'arrêt.
    La logique principale est dans les callbacks WebSocket.
    """
    try:
        with config_lock:
            bot_state["status"] = "En cours"
            current_symbol = bot_state["symbol"]
            current_tf = bot_state["timeframe"]
        logger.info(f"Run Bot Thread: Démarrage pour {current_symbol} sur {current_tf}")

        # Récupération initiale infos symbole & assets (déjà fait dans start_bot_core)
        # Récupération initiale soldes (déjà fait dans start_bot_core)

        # Boucle d'attente principale
        while True:
            stop_req = False
            with config_lock: stop_req = bot_state.get("stop_main_requested", False)
            if stop_req:
                logger.info("Run Bot Thread: Arrêt demandé détecté.")
                break

            # Optionnel: Vérifications périodiques (ex: état WS Manager)
            # with config_lock:
            #     ws_man_check = bot_state.get("websocket_manager")
            #     if ws_man_check is None and not stop_req:
            #         logger.warning("Run Bot Thread: WS Manager semble inactif!")
            #         # Que faire ? Tenter de redémarrer ? -> Complexe

            time.sleep(1) # Pause pour éviter 100% CPU

    except Exception as e:
        logger.exception("Run Bot Thread: Erreur majeure.")
        with config_lock:
            bot_state["status"] = "Erreur Run"
            bot_state["stop_main_requested"] = True # Assurer l'arrêt

    finally:
        logger.info("Run Bot Thread: Fin exécution.")
        # Le nettoyage est géré par stop_bot_core, mais on met le statut final
        with config_lock:
            bot_state["status"] = "Arrêté"
            bot_state["main_thread"] = None
        # Sauvegarde finale (peut être redondant avec /stop mais sécuritaire)
        logger.info("Run Bot Thread: Sauvegarde finale des données...")
        save_data()


# --- Fonctions de Contrôle Start/Stop (appelées par l'API) ---

def start_bot_core() -> tuple[bool, str]:
    """
    Logique principale pour démarrer le bot, les WebSockets et les threads.
    Retourne (succès, message).
    """
    global bot_state, kline_history # Accès direct pour modif/init

    with config_lock:
        if bot_state.get("main_thread") and bot_state["main_thread"].is_alive():
            return False, "Bot déjà en cours."

        # --- Nettoyage Complet avant démarrage ---
        logger.info("Start Core: Nettoyage état précédent...")
        # (Cette logique est maintenant dans stop_bot_core, appelée avant start si nécessaire)
        # stop_bot_core() # Assurer un état propre - Appelée par la route API /start

    # 1. Initialisation Client Binance
    if binance_client_wrapper.get_client() is None:
        msg = "Échec initialisation client Binance."
        logger.error(f"Start Core: {msg}")
        return False, msg

    logger.info("Start Core: Démarrage...")

    # 2. Chargement Données Persistantes
    loaded_data = load_data()
    with config_lock:
        if loaded_data:
            state_data = loaded_data.get("state", {})
            history_data = loaded_data.get("history", [])
            bot_state["in_position"] = state_data.get("in_position", False)
            bot_state["entry_details"] = state_data.get("entry_details") # None si absent
            bot_state["order_history"] = list(history_data) # Assurer une liste
            # Limiter taille historique au chargement
            max_len = bot_state.get('max_history_length', 100)
            if len(bot_state['order_history']) > max_len:
                bot_state['order_history'] = bot_state['order_history'][-max_len:]
            logger.info("Start Core: État et historique restaurés.")
        else:
            bot_state["in_position"] = False
            bot_state["entry_details"] = None
            bot_state["order_history"] = []
            logger.info("Start Core: Initialisation avec état et historique vides.")

        # Vider queue ticker
        # --- FIX for lines 257, 258, 259 ---
        while not latest_price_queue.empty():
            try:
                latest_price_queue.get_nowait()
            except queue.Empty: # Use imported queue module
                break
        # --- END FIX ---
        logger.info("Start Core: Queue de prix ticker vidée.")

        # 3. Pré-remplir l'historique kline
        with kline_history_lock:
            kline_history.clear()
            current_tf = bot_config["TIMEFRAME_STR"]
            required_limit = bot_state["required_klines"]
            binance_interval = TIMEFRAME_CONSTANT_MAP.get(current_tf)
            current_symbol = bot_state["symbol"]

            if binance_interval:
                logger.info(f"Start Core: Pré-remplissage historique avec {required_limit} klines ({current_symbol} {current_tf})...")
                initial_klines = binance_client_wrapper.get_klines(
                    symbol=current_symbol, interval=binance_interval, limit=required_limit
                )
                if initial_klines and len(initial_klines) >= required_limit:
                    # S'assurer que maxlen est correct (si changé via API pendant arrêt)
                    if kline_history.maxlen != required_limit:
                         kline_history = collections.deque(maxlen=required_limit)
                    kline_history.extend(initial_klines)
                    logger.info(f"Start Core: Historique klines pré-rempli ({len(kline_history)} bougies).")
                elif initial_klines:
                     logger.warning(f"Start Core: N'a pu récupérer que {len(initial_klines)}/{required_limit} klines initiales.")
                     kline_history.extend(initial_klines)
                else:
                    logger.error("Start Core: Échec récupération klines initiales.")
            else:
                logger.error(f"Start Core: Timeframe '{current_tf}' invalide pour pré-remplissage.")

        # 4. Récupérer infos symbole et soldes initiaux
        symbol_info = binance_client_wrapper.get_symbol_info(bot_state["symbol"])
        if not symbol_info:
            msg = f"Impossible de récupérer les informations pour {bot_state['symbol']}."
            logger.error(f"Start Core: {msg}")
            return False, msg
        bot_state['base_asset'] = symbol_info.get('baseAsset', '')
        bot_state['quote_asset'] = symbol_info.get('quoteAsset', 'USDT')
        if not bot_state['base_asset']:
            msg = f"Asset de base non trouvé pour {bot_state['symbol']}."
            logger.error(f"Start Core: {msg}")
            return False, msg
        logger.info(f"Start Core: Assets détectés: Base='{bot_state['base_asset']}', Quote='{bot_state['quote_asset']}'")

        initial_quote = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
        initial_base = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
        if initial_quote is None: initial_quote = 0.0; logger.warning(f"Start Core: Impossible lire solde initial {bot_state['quote_asset']}. Utilisation 0.")
        bot_state["available_balance"] = initial_quote

        # --- FIX for line 308 ---
        if initial_base is not None:
            bot_state["symbol_quantity"] = initial_base
        elif bot_state["in_position"]:
            entry_details = bot_state.get("entry_details") # Get potential details
            if entry_details: # Check if it's a valid dictionary
                 bot_state["symbol_quantity"] = entry_details.get("quantity", 0.0) # Safely get quantity
                 logger.warning(f"Start Core: Impossible lire solde {bot_state['base_asset']} (en pos). Utilisation qté entrée.")
            else:
                 # Defensive case: in position but no valid entry_details found
                 bot_state["symbol_quantity"] = 0.0
                 logger.error(f"Start Core: In position mais entry_details est invalide! Solde {bot_state['base_asset']} mis à 0.")
        else: # Not in position
            bot_state["symbol_quantity"] = 0.0
            logger.warning(f"Start Core: Impossible lire solde {bot_state['base_asset']} (pas en pos). Utilisation 0.")
        # --- END FIX ---

        logger.info(f"Start Core: Solde initial {bot_state['quote_asset']}: {bot_state['available_balance']:.4f}")
        logger.info(f"Start Core: Quantité initiale {bot_state['base_asset']}: {bot_state['symbol_quantity']:.6f}")


        # 5. Démarrage User Data Stream et Keepalive
        logger.info("Start Core: Obtention ListenKey User Data Stream...")
        new_listen_key = binance_client_wrapper.start_user_data_stream()
        if new_listen_key:
            bot_state["listen_key"] = new_listen_key
            bot_state["stop_keepalive_requested"] = False
            bot_state["keepalive_thread"] = threading.Thread(target=run_keepalive, daemon=True)
            bot_state["keepalive_thread"].start()
        else:
            logger.error("Start Core: Échec obtention ListenKey. User Data Stream non démarré.")
            # Continuer sans pour le moment

        # 6. Démarrage WebSocket Manager et Streams
        try:
            logger.info("Start Core: Démarrage WebSocket Manager...")
            use_testnet_ws = getattr(config, 'USE_TESTNET', False)
            # Utiliser les clés API de config.py (via config_manager)
            ws_manager = ThreadedWebsocketManager(
                api_key=config.BINANCE_API_KEY,
                api_secret=config.BINANCE_API_SECRET,
                testnet=use_testnet_ws
            )
            ws_manager.start()
            bot_state["websocket_manager"] = ws_manager # Stocker l'instance

            stream_symbol = bot_state["symbol"].lower()
            current_tf = bot_state["timeframe"]
            kline_interval_ws = TIMEFRAME_CONSTANT_MAP.get(current_tf)

            # Stream Ticker
            ticker_stream_name = ws_manager.start_symbol_miniticker_socket(
                callback=websocket_handlers.process_ticker_message, symbol=stream_symbol
            )
            bot_state["ticker_websocket_stream_name"] = ticker_stream_name
            logger.info(f"Start Core: Connecté stream Ticker: {ticker_stream_name}")

            # Stream Kline
            if kline_interval_ws:
                kline_stream_name = ws_manager.start_kline_socket(
                    callback=websocket_handlers.process_kline_message,
                    symbol=stream_symbol, interval=kline_interval_ws
                )
                bot_state["kline_websocket_stream_name"] = kline_stream_name
                logger.info(f"Start Core: Connecté stream Kline: {kline_stream_name} ({current_tf})")
            else:
                 logger.error(f"Start Core: Timeframe '{current_tf}' invalide pour stream Kline WS.")

            # Stream User Data (SI listenKey obtenu)
            if bot_state.get("listen_key"):
                user_stream_name = ws_manager.start_user_socket(
                    callback=websocket_handlers.process_user_data_message
                    # listen_key n'est PAS un argument ici
                )
                bot_state["user_data_stream_name"] = user_stream_name
                logger.info(f"Start Core: Connecté stream User Data: {user_stream_name}")
            else:
                logger.warning("Start Core: User Data Stream non démarré (ListenKey manquant).")

        except Exception as e:
            logger.exception("Start Core: Erreur critique démarrage WebSocket Manager/Streams.")
            # Nettoyage partiel en cas d'erreur démarrage WS
            stop_bot_core(partial_cleanup=True) # Tenter d'arrêter ce qui a pu démarrer
            return False, "Erreur démarrage WebSocket."

        # 7. Démarrage Thread Principal (run_bot)
        bot_state["status"] = "Démarrage..."
        bot_state["stop_main_requested"] = False
        bot_state["main_thread"] = threading.Thread(target=run_bot, daemon=True)
        bot_state["main_thread"].start()

    # Attendre un court instant pour que les threads démarrent
    time.sleep(1)
    return True, "Bot démarré avec succès."


# (stop_bot_core function remains unchanged)
def stop_bot_core(partial_cleanup=False) -> tuple[bool, str]:
    """
    Logique principale pour arrêter le bot, les WebSockets et les threads.
    `partial_cleanup` est utilisé si appelé après une erreur de démarrage.
    Retourne (succès, message).
    """
    logger.info(f"Stop Core: Arrêt demandé {'(nettoyage partiel)' if partial_cleanup else ''}...")
    stopped_something = False

    with config_lock:
        # 1. Signaler l'arrêt aux threads
        if bot_state.get("main_thread") and bot_state["main_thread"].is_alive():
            bot_state["stop_main_requested"] = True
            stopped_something = True
        if bot_state.get("keepalive_thread") and bot_state["keepalive_thread"].is_alive():
            bot_state["stop_keepalive_requested"] = True
            stopped_something = True

        # Mettre le statut immédiatement si ce n'est pas un nettoyage partiel
        if not partial_cleanup and stopped_something:
             bot_state["status"] = "Arrêt en cours..."
        elif not partial_cleanup and not stopped_something:
             # Si rien n'était actif, vérifier si des WS ou listen key trainent
             if bot_state.get("websocket_manager") or bot_state.get("listen_key"):
                 logger.warning("Stop Core: Threads inactifs mais WS/ListenKey présents? Tentative nettoyage.")
                 stopped_something = True # Forcer le nettoyage WS/Key
             else:
                 return False, "Bot déjà arrêté."

    # --- Arrêt hors du lock principal ---

    # 2. Arrêt Thread Keepalive (attendre un peu)
    keepalive_thread_to_stop = bot_state.get("keepalive_thread")
    if keepalive_thread_to_stop and keepalive_thread_to_stop.is_alive():
        logger.info("Stop Core: Attente arrêt thread Keepalive...")
        keepalive_thread_to_stop.join(timeout=5)
        if keepalive_thread_to_stop.is_alive(): logger.warning("Stop Core: Thread Keepalive n'a pas pu être arrêté.")
        with config_lock: bot_state["keepalive_thread"] = None

    # 3. Arrêt WebSockets
    ws_man_to_stop = bot_state.get("websocket_manager")
    if ws_man_to_stop:
        logger.info("Stop Core: Arrêt WebSocket Manager...")
        try:
            # Pas besoin de stopper les sockets individuellement, ws_man.stop() le fait
            ws_man_to_stop.stop()
            logger.info("Stop Core: Ordre d'arrêt envoyé au WebSocket Manager.")
        except Exception as e: logger.error(f"Stop Core: Erreur arrêt WebSocket Manager: {e}")
        finally:
             with config_lock:
                 # Vérifier si c'est toujours la même instance avant de nullifier
                 if bot_state.get("websocket_manager") == ws_man_to_stop:
                     bot_state["websocket_manager"] = None
                     bot_state["ticker_websocket_stream_name"] = None
                     bot_state["kline_websocket_stream_name"] = None
                     bot_state["user_data_stream_name"] = None

    # 4. Fermeture ListenKey
    listen_key_to_close = bot_state.get('listen_key')
    if listen_key_to_close:
        logger.info(f"Stop Core: Fermeture ListenKey {listen_key_to_close[:5]}...")
        binance_client_wrapper.close_user_data_stream(listen_key_to_close)
        with config_lock: bot_state['listen_key'] = None

    # 5. Attendre arrêt thread principal (run_bot)
    main_thread_to_stop = bot_state.get("main_thread")
    if main_thread_to_stop and main_thread_to_stop.is_alive():
        logger.info("Stop Core: Attente arrêt thread principal (run_bot)...")
        main_thread_to_stop.join(timeout=10)
        if main_thread_to_stop.is_alive(): logger.warning("Stop Core: Thread principal (run_bot) n'a pas terminé.")
        else: logger.info("Stop Core: Thread principal (run_bot) terminé.")
        with config_lock: bot_state["main_thread"] = None

    # Statut final
    with config_lock:
        bot_state["status"] = "Arrêté"
        # S'assurer que les flags sont bien remis à False pour un futur démarrage
        bot_state["stop_main_requested"] = False
        bot_state["stop_keepalive_requested"] = False

    logger.info("Stop Core: Processus d'arrêt terminé.")
    return True, "Bot arrêté avec succès."


# Exporter les fonctions nécessaires
__all__ = ['execute_exit', 'run_keepalive', 'run_bot', 'start_bot_core', 'stop_bot_core']
