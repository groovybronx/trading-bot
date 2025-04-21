# /Users/davidmichels/Desktop/trading-bot/backend/strategy.py
import logging
import pandas as pd
import pandas_ta as ta
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Optional, Dict, Any, List, Tuple

# MODIFIÉ: Importer les instances des managers
from state_manager import state_manager
from config_manager import config_manager

# MODIFIÉ: Importer le wrapper pour les appels API (ex: get_symbol_info)
import binance_client_wrapper

logger = logging.getLogger(__name__) # MODIFIÉ: Utiliser __name__

# --- Fonctions Utilitaires (Peuvent être dans un fichier séparé 'utils.py') ---

def format_quantity(quantity: float, symbol_info: Dict[str, Any]) -> float:
    """
    Formate la quantité selon les règles LOT_SIZE du symbole.
    Retourne 0.0 si la quantité est inférieure à minQty ou en cas d'erreur.
    """
    if not symbol_info or 'filters' not in symbol_info:
        logger.error(f"format_quantity: Données symbol_info invalides ou manquantes.")
        return 0.0

    lot_size_filter = next((f for f in symbol_info['filters'] if f.get('filterType') == 'LOT_SIZE'), None)
    if not lot_size_filter:
        logger.warning(f"format_quantity: Filtre LOT_SIZE non trouvé pour {symbol_info.get('symbol')}. Formatage non appliqué, retourne quantité originale.")
        # Retourner l'original peut être dangereux si l'API le rejette. 0.0 est plus sûr.
        # Décision: Retourner 0.0 pour forcer l'échec si le filtre est manquant.
        logger.error(f"format_quantity: Filtre LOT_SIZE manquant pour {symbol_info.get('symbol')}. Impossible de formater. Retourne 0.0")
        return 0.0

    step_size_str = lot_size_filter.get('stepSize')
    min_qty_str = lot_size_filter.get('minQty')

    if step_size_str is None or min_qty_str is None:
        logger.error(f"format_quantity: stepSize ou minQty manquant dans LOT_SIZE filter pour {symbol_info.get('symbol')}. Retourne 0.0")
        return 0.0

    try:
        step_size = Decimal(step_size_str)
        min_qty = Decimal(min_qty_str)

        if step_size <= 0:
            logger.error(f"format_quantity: stepSize invalide ({step_size_str}) pour {symbol_info.get('symbol')}. Retourne 0.0")
            return 0.0

        quantity_decimal = Decimal(str(quantity))

        # 1. Vérifier minQty AVANT formatage
        if quantity_decimal < min_qty:
             # logger.warning(f"format_quantity: Quantité {quantity_decimal} < minQty ({min_qty}). Retourne 0.0")
             return 0.0

        # 2. Appliquer stepSize en utilisant quantize pour la précision
        # Calculer le nombre de décimales du step_size
        # Exemple: step_size = 0.001 -> Decimal('0.001') -> tuple = (0, (0, 0, 1), -3) -> exponent = -3
        # Exemple: step_size = 1 -> Decimal('1') -> tuple = (0, (1,), 0) -> exponent = 0
        exponent = step_size.as_tuple().exponent
        # quantize avec ROUND_DOWN pour tronquer aux décimales du step_size
        formatted_qty = quantity_decimal.quantize(Decimal('1e' + str(exponent)), rounding=ROUND_DOWN)

        # 3. Vérifier minQty APRÈS formatage
        if formatted_qty < min_qty:
             # logger.warning(f"format_quantity: Quantité formatée {formatted_qty} < minQty ({min_qty}) après stepSize. Retourne 0.0")
             # Ceci peut arriver si quantity était très proche de min_qty et a été arrondie vers le bas.
             return 0.0

        # logger.debug(f"format_quantity: Quantité {quantity} formatée à {float(formatted_qty)} (step: {step_size}, min: {min_qty})")
        return float(formatted_qty)

    except (InvalidOperation, TypeError, ValueError) as e:
        logger.error(f"format_quantity: Erreur formatage quantité pour {symbol_info.get('symbol')}: {e}. Qty='{quantity}', Step='{step_size_str}', Min='{min_qty_str}'. Retourne 0.0", exc_info=True)
        return 0.0

def get_min_notional(symbol_info: Dict[str, Any]) -> float:
    """
    Récupère la valeur MIN_NOTIONAL pour le symbole.
    Retourne une valeur par défaut élevée (ex: 10.0) si non trouvé ou erreur.
    """
    default_min_notional = 10.0 # Valeur USDT par défaut (relativement sûre)
    if not symbol_info or 'filters' not in symbol_info:
        logger.error(f"get_min_notional: Données symbol_info invalides ou manquantes.")
        return default_min_notional

    # MODIFIÉ: Utiliser MIN_NOTIONAL ou MARKET_LOT_SIZE selon les versions API/symbole
    min_notional_filter = next((f for f in symbol_info['filters'] if f.get('filterType') == 'MIN_NOTIONAL'), None)
    # Fallback sur MARKET_LOT_SIZE si MIN_NOTIONAL n'existe pas (plus rare)
    # market_lot_size_filter = next((f for f in symbol_info['filters'] if f.get('filterType') == 'MARKET_LOT_SIZE'), None)

    notional_str = None
    filter_type = None

    if min_notional_filter and 'minNotional' in min_notional_filter:
        notional_str = min_notional_filter['minNotional']
        filter_type = 'MIN_NOTIONAL'
    # elif market_lot_size_filter and 'minQty' in market_lot_size_filter:
        # Ce n'est pas le notional, c'est la quantité min pour MARKET. Ne pas utiliser ici.
        # logger.warning(f"get_min_notional: MIN_NOTIONAL non trouvé, utilisation MARKET_LOT_SIZE non implémentée pour notional.")

    if notional_str and filter_type:
        try:
            min_notional_val = float(notional_str)
            # logger.debug(f"get_min_notional: Filtre {filter_type} trouvé pour {symbol_info.get('symbol')}: {min_notional_val}")
            return min_notional_val
        except (ValueError, TypeError):
            logger.error(f"get_min_notional: Impossible de convertir {filter_type} '{notional_str}' en float pour {symbol_info.get('symbol')}. Utilisation défaut {default_min_notional}.")
            return default_min_notional
    else:
        logger.warning(f"get_min_notional: Filtre MIN_NOTIONAL non trouvé pour {symbol_info.get('symbol')}. Utilisation défaut {default_min_notional}.")
        return default_min_notional

# --- Stratégie Scalping ---

def check_scalping_entry(
    current_symbol: str,
    # MODIFIÉ: Passer les données nécessaires explicitement
    book_ticker: Dict[str, Any],
    depth: Dict[str, Any],
    # trades: List[Dict[str, Any]], # Décommenter si utilisé
    current_config: Dict[str, Any],
    available_balance: float,
    symbol_info: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Vérifie les conditions d'entrée pour la stratégie de scalping.
    Utilise les données temps réel fournies.
    Retourne les détails de l'ordre à placer si les conditions sont remplies, sinon None.

    Args:
        current_symbol: Le symbole de trading (ex: 'BTCUSDT').
        book_ticker: Dernières données du book ticker.
        depth: Dernier snapshot du carnet d'ordres.
        current_config: Configuration actuelle du bot.
        available_balance: Solde disponible de l'asset de cotation (ex: USDT).
        symbol_info: Informations sur le symbole (pour filtres).

    Returns:
        Dictionnaire avec les paramètres de l'ordre ('symbol', 'side', 'quantity', 'order_type', 'price'?, 'time_in_force'?)
        ou None si aucune condition d'entrée n'est remplie.
    """
    # Vérifier si les données sont disponibles (fait avant l'appel normalement, mais double check)
    if not book_ticker or not depth or not depth.get('bids') or not depth.get('asks'):
        # logger.debug("Scalping Entry Check: Données temps réel manquantes ou invalides.")
        return None

    try:
        best_bid_price_str = book_ticker.get('b')
        best_ask_price_str = book_ticker.get('a')
        best_bid_qty_str = book_ticker.get('B')
        best_ask_qty_str = book_ticker.get('A')

        if not all([best_bid_price_str, best_ask_price_str, best_bid_qty_str, best_ask_qty_str]):
             logger.warning("Scalping Entry Check: Données book ticker incomplètes.")
             return None

        best_bid_price = Decimal(best_bid_price_str or '0')
        best_ask_price = Decimal(best_ask_price_str or '0')
        best_bid_qty = Decimal(best_bid_qty_str or '0')
        best_ask_qty = Decimal(best_ask_qty_str or '0')

        if best_bid_price <= 0 or best_ask_price <= 0:
            logger.warning(f"Scalping Entry Check: Prix invalides dans book ticker (bid={best_bid_price}, ask={best_ask_price}).")
            return None

    except (InvalidOperation, TypeError) as e:
        logger.error(f"Scalping Entry Check: Erreur conversion données book ticker: {e}")
        return None

    # --- PLACEHOLDER: Logique de Scalping ---
    # TODO: Implémentez VOTRE logique de décision d'entrée ici.
    # Utilisez book_ticker, depth, trades (si nécessaire), et current_config.
    # Cet exemple est TRÈS basique et ne doit PAS être utilisé en production.

    should_buy = False # Ou should_sell si vous tradez dans les deux sens

    # Exemple 1: Spread faible + Déséquilibre Achat
    try:
        relative_spread = (best_ask_price - best_bid_price) / best_ask_price if best_ask_price > 0 else Decimal('0')
        spread_threshold = Decimal(str(current_config.get("SCALPING_SPREAD_THRESHOLD", 0.0001)))

        levels = current_config.get("SCALPING_DEPTH_LEVELS", 5)
        # Assurer que les niveaux existent et sont valides
        valid_bids = [Decimal(level[1]) for level in depth['bids'][:levels] if len(level) > 1]
        valid_asks = [Decimal(level[1]) for level in depth['asks'][:levels] if len(level) > 1]

        if not valid_bids or not valid_asks:
             logger.warning("Scalping Entry Check: Données de profondeur invalides ou insuffisantes.")
             return None

        total_bid_qty = sum(valid_bids)
        total_ask_qty = sum(valid_asks)

        imbalance_ratio = total_bid_qty / total_ask_qty if total_ask_qty > 0 else Decimal('Infinity') # Ratio Bid/Ask
        imbalance_threshold = Decimal(str(current_config.get("SCALPING_IMBALANCE_THRESHOLD", 1.5)))

        # Condition d'achat (Exemple Simpliste)
        if relative_spread < spread_threshold and imbalance_ratio > imbalance_threshold:
            logger.info(f"SCALPING BUY Condition Met: Spread={relative_spread:.5f} (<{spread_threshold}), Imbalance={imbalance_ratio:.2f} (>{imbalance_threshold})")
            should_buy = True

    except (IndexError, TypeError, KeyError, ZeroDivisionError, InvalidOperation) as e:
        logger.error(f"Scalping Entry Check: Erreur calcul indicateurs (spread/imbalance): {e}", exc_info=True)
        return None
    # --- FIN PLACEHOLDER ---

    if should_buy:
        # --- Calcul Taille Position ---
        try:
            risk_per_trade = Decimal(str(current_config.get("RISK_PER_TRADE", 0.01)))
            capital_allocation = Decimal(str(current_config.get("CAPITAL_ALLOCATION", 1.0)))
            stop_loss_pct = Decimal(str(current_config.get("STOP_LOSS_PERCENTAGE", 0.005)))

            # Utiliser le prix ASK pour l'entrée (on achète au prix demandé)
            entry_price_decimal = best_ask_price
            stop_loss_price = entry_price_decimal * (Decimal(1) - stop_loss_pct)
            risk_per_unit = entry_price_decimal - stop_loss_price

            if risk_per_unit <= 0:
                logger.warning(f"Scalping Entry: Risque par unité nul ou négatif (SL trop large ou prix invalide?). SL={stop_loss_price:.8f}, Entry={entry_price_decimal:.8f}")
                return None

            capital_to_use = Decimal(str(available_balance)) * capital_allocation
            capital_to_risk = capital_to_use * risk_per_trade

            # Quantité basée sur le risque
            quantity_decimal = capital_to_risk / risk_per_unit

            # Formater selon les règles du symbole
            formatted_quantity = format_quantity(float(quantity_decimal), symbol_info)

            if formatted_quantity <= 0:
                logger.warning(f"Scalping Entry: Quantité calculée ({quantity_decimal:.8f}) est invalide ou nulle après formatage.")
                return None

            # Vérifier MIN_NOTIONAL
            min_notional = get_min_notional(symbol_info)
            order_notional = formatted_quantity * float(entry_price_decimal)

            if order_notional < min_notional:
                logger.warning(f"Scalping Entry: Notionnel calculé ({order_notional:.4f}) < MIN_NOTIONAL ({min_notional:.4f}). Tentative d'ajustement...")
                # Tenter d'augmenter pour juste dépasser min_notional
                required_qty_decimal = (Decimal(str(min_notional)) / entry_price_decimal) * Decimal('1.01') # +1% pour marge
                formatted_quantity = format_quantity(float(required_qty_decimal), symbol_info)
                order_notional = formatted_quantity * float(entry_price_decimal)

                if formatted_quantity <= 0 or order_notional < min_notional:
                     logger.error(f"Scalping Entry: Ajustement MIN_NOTIONAL échoué. Qty={formatted_quantity}, Notional={order_notional:.4f}. Ordre annulé.")
                     return None
                logger.info(f"Scalping Entry: Quantité ajustée à {formatted_quantity} pour MIN_NOTIONAL.")

            # Vérifier si la quantité ajustée ne dépasse pas le capital alloué
            if order_notional > float(capital_to_use):
                 logger.error(f"Scalping Entry: Notionnel ajusté ({order_notional:.4f}) dépasse le capital alloué ({float(capital_to_use):.4f}). Ordre annulé.")
                 return None

        except (InvalidOperation, TypeError, ValueError, ZeroDivisionError) as e:
            logger.error(f"Scalping Entry: Erreur calcul taille position: {e}", exc_info=True)
            return None

        # --- Préparer les paramètres de l'ordre ---
        order_params: Dict[str, Any] = {
            "symbol": current_symbol,
            "side": "BUY", # Basé sur should_buy
            "quantity": formatted_quantity,
            "order_type": current_config.get("SCALPING_ORDER_TYPE", "MARKET"),
        }

        if order_params["order_type"] == "LIMIT":
            # Pour un ordre LIMIT d'achat, on peut se placer au best ask ou légèrement en dessous
            # Stratégie: se placer au best ask pour augmenter chances d'exécution rapide
            limit_price = best_ask_price
            # TODO: Ajouter une logique pour ajuster le prix limite si désiré (ex: mid-price, etc.)
            order_params["price"] = str(limit_price)
            order_params["time_in_force"] = current_config.get("SCALPING_LIMIT_TIF", "GTC")

        logger.info(f"Scalping Entry Signal: Préparation ordre {order_params['side']} {order_params['order_type']} de {order_params['quantity']} {current_symbol}"
                    + (f" @ {order_params.get('price')}" if order_params["order_type"] == "LIMIT" else ""))
        return order_params

    return None # Pas de signal d'entrée

def check_scalping_exit(
    current_symbol: str,
    entry_details: Dict[str, Any],
    # MODIFIÉ: Passer les données nécessaires explicitement
    book_ticker: Dict[str, Any],
    depth: Dict[str, Any],
    # trades: List[Dict[str, Any]], # Décommenter si utilisé
    current_config: Dict[str, Any]
) -> bool:
    """
    Vérifie les conditions de sortie spécifiques à la stratégie de scalping
    (autres que SL/TP qui sont gérés par process_book_ticker_message).
    Retourne True si une sortie basée sur la stratégie est nécessaire, False sinon.

    Args:
        current_symbol: Le symbole de trading.
        entry_details: Détails de l'ordre d'entrée (prix moyen, quantité).
        book_ticker: Dernières données du book ticker.
        depth: Dernier snapshot du carnet d'ordres.
        current_config: Configuration actuelle du bot.

    Returns:
        True si la stratégie indique une sortie, False sinon.
    """
    # Vérifier si les données sont disponibles
    if not book_ticker or not depth or not depth.get('bids') or not depth.get('asks'):
        # logger.debug("Scalping Exit Check: Données temps réel manquantes.")
        return False

    try:
        best_bid_price_str = book_ticker.get('b') # Prix auquel on peut vendre immédiatement
        if not best_bid_price_str: return False # Impossible de déterminer le prix de sortie
        best_bid_price = Decimal(best_bid_price_str)
        if best_bid_price <= 0: return False

        entry_price = Decimal(str(entry_details.get("avg_price", "0")))
        if entry_price <= 0:
             logger.warning("Scalping Exit Check: Prix d'entrée invalide dans entry_details.")
             return False

    except (InvalidOperation, TypeError) as e:
        logger.error(f"Scalping Exit Check: Erreur conversion données book ticker/entrée: {e}")
        return False

    # --- PLACEHOLDER: Logique de sortie Scalping (autre que SL/TP) ---
    # TODO: Implémentez VOTRE logique de décision de sortie ici.
    # Exemples:
    #   - Inversion du déséquilibre du carnet.
    #   - Atteinte d'un objectif de profit dynamique basé sur la volatilité.
    #   - Signal de retournement basé sur les trades récents (aggressivité).
    #   - Expiration d'un certain temps en position sans atteindre TP.

    should_exit = False

    # Exemple: Sortir si le déséquilibre du carnet s'inverse fortement (si on est long)
    try:
        levels = current_config.get("SCALPING_DEPTH_LEVELS", 5)
        valid_bids = [Decimal(level[1]) for level in depth['bids'][:levels] if len(level) > 1]
        valid_asks = [Decimal(level[1]) for level in depth['asks'][:levels] if len(level) > 1]

        if not valid_bids or not valid_asks: return False # Données invalides

        total_bid_qty = sum(valid_bids)
        total_ask_qty = sum(valid_asks)
        imbalance_ratio = total_bid_qty / total_ask_qty if total_ask_qty > 0 else Decimal('Infinity')

        # Seuil de sortie (inverse du seuil d'entrée, ou une valeur fixe)
        # Si on est entré avec imbalance > 1.5, on pourrait sortir si < 1/1.5 = 0.66
        imbalance_entry_threshold = Decimal(str(current_config.get("SCALPING_IMBALANCE_THRESHOLD", 1.5)))
        exit_imbalance_threshold = Decimal('1') / imbalance_entry_threshold if imbalance_entry_threshold > 0 else Decimal('0')

        # Condition de sortie si on est LONG (acheté)
        # TODO: Adapter si on peut être SHORT
        if imbalance_ratio < exit_imbalance_threshold:
            logger.info(f"SCALPING EXIT Condition Met: Imbalance={imbalance_ratio:.2f} (<{exit_imbalance_threshold:.2f})")
            should_exit = True

    except (IndexError, TypeError, KeyError, ZeroDivisionError, InvalidOperation) as e:
        logger.error(f"Scalping Exit Check: Erreur calcul indicateur sortie (imbalance): {e}")
        # Ne pas sortir en cas d'erreur de calcul
        should_exit = False

    # --- FIN PLACEHOLDER ---

    return should_exit


# --- Ancienne Stratégie (EMA/RSI) ---

def calculate_indicators_and_signals(
    kline_data: List[List[Any]],
    config_dict: Dict[str, Any] # MODIFIÉ: Renommé pour clarté
) -> Optional[pd.DataFrame]:
    """
    Calcule les indicateurs techniques (EMA, RSI, Volume MA) et génère des signaux
    basés sur la stratégie de croisement EMA/RSI.
    Utilisé seulement si STRATEGY_TYPE == 'SWING'.
    """
    if not kline_data:
        logger.warning("calculate_indicators: Données kline vides fournies.")
        return None

    # Noms des colonnes selon l'API Binance (vérifier si toujours exact)
    columns = ['Open_Time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close_Time',
               'Quote_Asset_Volume', 'Number_of_Trades', 'Taker_Buy_Base_Asset_Volume',
               'Taker_Buy_Quote_Asset_Volume', 'Ignore']
    df = pd.DataFrame(kline_data, columns=columns)

    # Conversion des types et gestion erreurs/NaN
    try:
        for col in ['Open', 'High', 'Low', 'Close', 'Volume', 'Quote_Asset_Volume',
                    'Taker_Buy_Base_Asset_Volume', 'Taker_Buy_Quote_Asset_Volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce') # Coerce met NaN si erreur
        df['Open_Time'] = pd.to_datetime(df['Open_Time'], unit='ms', errors='coerce')
        df['Close_Time'] = pd.to_datetime(df['Close_Time'], unit='ms', errors='coerce')

        # Supprimer les lignes où les conversions essentielles ont échoué (NaN)
        essential_cols = ['Open_Time', 'Open', 'High', 'Low', 'Close', 'Volume']
        df.dropna(subset=essential_cols, inplace=True)

        if df.empty:
            logger.warning("calculate_indicators: DataFrame vide après nettoyage des données kline.")
            return None

    except Exception as e:
        logger.error(f"calculate_indicators: Erreur lors de la conversion/nettoyage des données kline: {e}", exc_info=True)
        return None

    # Calcul des indicateurs avec pandas_ta
    try:
        # Récupérer les périodes depuis la config fournie
        ema_short_len = config_dict.get('EMA_SHORT_PERIOD', 9)
        ema_long_len = config_dict.get('EMA_LONG_PERIOD', 21)
        rsi_len = config_dict.get('RSI_PERIOD', 14)
        use_ema_filter = config_dict.get('USE_EMA_FILTER', False)
        ema_filter_len = config_dict.get('EMA_FILTER_PERIOD', 50)
        use_vol_confirm = config_dict.get('USE_VOLUME_CONFIRMATION', False)
        vol_ma_len = config_dict.get('VOLUME_AVG_PERIOD', 20)

        # Calculs
        df.ta.ema(length=ema_short_len, append=True, col_names=('EMA_short',))
        df.ta.ema(length=ema_long_len, append=True, col_names=('EMA_long',))
        df.ta.rsi(length=rsi_len, append=True, col_names=('RSI',))

        if use_ema_filter:
            df.ta.ema(length=ema_filter_len, append=True, col_names=('EMA_filter',))
        if use_vol_confirm:
            # Utiliser 'Volume' comme source pour la SMA
            df.ta.sma(close='Volume', length=vol_ma_len, append=True, col_names=('Volume_MA',))

        # Supprimer les lignes avec NaN introduits par les calculs d'indicateurs (au début)
        df.dropna(inplace=True)
        if df.empty:
            logger.warning("calculate_indicators: DataFrame vide après calcul des indicateurs (historique insuffisant?).")
            return None

    except Exception as e:
        logger.error(f"calculate_indicators: Erreur lors du calcul des indicateurs TA: {e}", exc_info=True)
        return None

    # Génération des signaux
    df['signal'] = 'NONE' # Initialiser la colonne signal
    rsi_ob = config_dict.get('RSI_OVERBOUGHT', 75)
    rsi_os = config_dict.get('RSI_OVERSOLD', 25)

    # Conditions d'achat (Long) - Croisement EMA haussier
    buy_cond_ema_cross = (df['EMA_short'] > df['EMA_long']) & (df['EMA_short'].shift(1) <= df['EMA_long'].shift(1))
    buy_cond_rsi = (df['RSI'] < rsi_ob) # Ne pas acheter en surachat extrême

    # Combinaison initiale
    buy_conditions = buy_cond_ema_cross & buy_cond_rsi

    # Ajouter filtres optionnels
    if use_ema_filter and 'EMA_filter' in df.columns:
        buy_conditions &= (df['Close'] > df['EMA_filter']) # Prix au-dessus de l'EMA longue
    if use_vol_confirm and 'Volume_MA' in df.columns:
        buy_conditions &= (df['Volume'] > df['Volume_MA']) # Volume au-dessus de la moyenne

    df.loc[buy_conditions, 'signal'] = 'BUY'

    # Conditions de vente (Sortie de Long) - Croisement EMA baissier
    # Note: On pourrait ajouter une condition RSI > rsi_os pour éviter de vendre en survente,
    # mais la stratégie de base est souvent juste le croisement inverse.
    sell_cond_ema_cross = (df['EMA_short'] < df['EMA_long']) & (df['EMA_short'].shift(1) >= df['EMA_long'].shift(1))
    # sell_cond_rsi = (df['RSI'] > rsi_os) # Optionnel: Ne pas vendre en survente extrême

    sell_conditions = sell_cond_ema_cross # & sell_cond_rsi (si ajouté)

    df.loc[sell_conditions, 'signal'] = 'SELL'

    # logger.debug(f"calculate_indicators: Indicateurs et signaux calculés. Dernier signal: {df['signal'].iloc[-1] if not df.empty else 'N/A'}")
    return df

def check_entry_conditions(
    current_data: pd.Series, # Dernière ligne du DataFrame avec indicateurs/signaux
    symbol: str,
    # MODIFIÉ: Passer config et état nécessaires
    current_config: Dict[str, Any],
    available_balance: float,
    symbol_info: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Vérifie les conditions d'entrée pour la stratégie EMA/RSI et prépare l'ordre.
    Retourne les détails de l'ordre MARKET à placer, ou None.
    (Utilisé seulement si STRATEGY_TYPE == 'SWING')
    """
    if current_data.get('signal') != 'BUY':
        return None # Pas de signal d'achat

    logger.info(f"SWING Entry Check: Signal BUY détecté pour {symbol}.")

    # --- Calcul Taille Position ---
    try:
        entry_price_str = current_data.get('Close') # Utiliser le prix de clôture de la bougie du signal
        if entry_price_str is None: raise ValueError("Prix de clôture manquant dans current_data")
        entry_price = Decimal(str(entry_price_str))

        risk_per_trade = Decimal(str(current_config.get("RISK_PER_TRADE", 0.01)))
        capital_allocation = Decimal(str(current_config.get("CAPITAL_ALLOCATION", 1.0)))
        stop_loss_pct = Decimal(str(current_config.get("STOP_LOSS_PERCENTAGE", 0.02))) # SL pour SWING

        stop_loss_price = entry_price * (Decimal(1) - stop_loss_pct)
        risk_per_unit = entry_price - stop_loss_price

        if risk_per_unit <= 0:
            logger.warning(f"SWING Entry: Risque par unité nul ou négatif (SL={stop_loss_price:.8f}, Entry={entry_price:.8f}).")
            return None

        capital_to_use = Decimal(str(available_balance)) * capital_allocation
        capital_to_risk = capital_to_use * risk_per_trade
        quantity_decimal = capital_to_risk / risk_per_unit

        # Formater et vérifier filtres
        formatted_quantity = format_quantity(float(quantity_decimal), symbol_info)
        if formatted_quantity <= 0:
            logger.warning(f"SWING Entry: Quantité calculée ({quantity_decimal:.8f}) invalide ou nulle après formatage.")
            return None

        min_notional = get_min_notional(symbol_info)
        order_notional = formatted_quantity * float(entry_price)

        if order_notional < min_notional:
            logger.warning(f"SWING Entry: Notionnel calculé ({order_notional:.4f}) < MIN_NOTIONAL ({min_notional:.4f}). Ordre non placé.")
            # Pour SWING, on n'ajuste généralement pas, on saute le trade.
            return None

        if order_notional > float(capital_to_use):
             logger.error(f"SWING Entry: Notionnel ({order_notional:.4f}) dépasse le capital alloué ({float(capital_to_use):.4f}). Ordre annulé.")
             return None

        logger.info(f"SWING Entry: Calcul taille position OK. Quantité={formatted_quantity} {symbol} (Risque: {capital_to_risk:.2f}, SL: {stop_loss_price:.4f})")

        # Préparer l'ordre MARKET (typiquement pour SWING basé sur clôture)
        order_params = {
            "symbol": symbol,
            "side": "BUY",
            "quantity": formatted_quantity,
            "order_type": "MARKET", # Ordre au marché pour entrer rapidement après le signal
        }
        logger.info(f"SWING Entry Signal: Préparation ordre {order_params['side']} {order_params['order_type']} de {order_params['quantity']} {symbol}")
        return order_params

    except (InvalidOperation, TypeError, ValueError, ZeroDivisionError, KeyError) as e:
        logger.error(f"SWING Entry: Erreur calcul taille/préparation ordre: {e}", exc_info=True)
        return None

def check_exit_conditions(
    current_data: pd.Series,
    symbol: str
    # MODIFIÉ: Pas besoin d'autres args pour cette version simple
) -> bool:
    """
    Vérifie les conditions de sortie pour la stratégie EMA/RSI (signal SELL).
    Retourne True si un signal de sortie est détecté.
    (Utilisé seulement si STRATEGY_TYPE == 'SWING')
    """
    if current_data.get('signal') == 'SELL':
        logger.info(f"SWING Exit Check: Signal SELL détecté pour {symbol}.")
        return True
    return False

