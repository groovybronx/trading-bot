# /Users/davidmichels/Desktop/trading-bot/backend/strategies/swing_strategy.py
import logging
import pandas as pd
import pandas_ta as ta
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any, List, Union

# Importer les utilitaires partagés mis à jour
from utils.order_utils import (
    format_quantity,
    get_min_notional,
    check_min_notional,
)

logger = logging.getLogger(__name__)

# calculate_indicators_and_signals reste inchangé...
def calculate_indicators_and_signals(
    kline_data: List[List[Any]],
    config_dict: Dict[str, Any]
) -> Optional[pd.DataFrame]:
    """ Calcule indicateurs (EMA, RSI, Volume MA) et génère signaux SWING. """
    if not kline_data:
        logger.warning("SWING: Données kline vides.")
        return None

    columns = ['Open_Time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close_Time',
               'Quote_Asset_Volume', 'Number_of_Trades', 'Taker_Buy_Base_Asset_Volume',
               'Taker_Buy_Quote_Asset_Volume', 'Ignore']
    df = pd.DataFrame(kline_data, columns=columns)

    try:
        # Conversion en numérique/datetime
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']: df[col] = pd.to_numeric(df[col], errors='coerce')
        df['Open_Time'] = pd.to_datetime(df['Open_Time'], unit='ms', errors='coerce')
        df.dropna(subset=['Open_Time', 'Open', 'High', 'Low', 'Close', 'Volume'], inplace=True)
        if df.empty: logger.warning("SWING: DataFrame vide après nettoyage."); return None
    except Exception as e:
        logger.error(f"SWING: Erreur conversion/nettoyage klines: {e}", exc_info=True); return None

    try:
        # Récupérer périodes depuis config (format interne, déjà int)
        ema_s = config_dict.get('EMA_SHORT_PERIOD', 9)
        ema_l = config_dict.get('EMA_LONG_PERIOD', 21)
        rsi_p = config_dict.get('RSI_PERIOD', 14)
        use_ema_f = config_dict.get('USE_EMA_FILTER', False)
        ema_f = config_dict.get('EMA_FILTER_PERIOD', 50)
        use_vol = config_dict.get('USE_VOLUME_CONFIRMATION', False)
        vol_p = config_dict.get('VOLUME_AVG_PERIOD', 20)

        # Calcul indicateurs
        df.ta.ema(length=ema_s, append=True, col_names=('EMA_short',))
        df.ta.ema(length=ema_l, append=True, col_names=('EMA_long',))
        df.ta.rsi(length=rsi_p, append=True, col_names=('RSI',))
        if use_ema_f: df.ta.ema(length=ema_f, append=True, col_names=('EMA_filter',))
        if use_vol: df.ta.sma(close='Volume', length=vol_p, append=True, col_names=('Volume_MA',))

        df.dropna(inplace=True) # Supprimer lignes avec NaN après calculs
        if df.empty: logger.warning("SWING: DataFrame vide après calcul indicateurs."); return None
    except Exception as e:
        logger.error(f"SWING: Erreur calcul indicateurs TA: {e}", exc_info=True); return None

    # Génération signaux
    df['signal'] = 'NONE'
    rsi_ob = config_dict.get('RSI_OVERBOUGHT', 75) # Déjà int
    rsi_os = config_dict.get('RSI_OVERSOLD', 25) # Déjà int

    # Conditions Achat
    buy_cond = (df['EMA_short'] > df['EMA_long']) & (df['EMA_short'].shift(1) <= df['EMA_long'].shift(1))
    buy_cond &= (df['RSI'] < rsi_ob) # Doit être SOUS surachat pour acheter sur croisement haussier
    if use_ema_f and 'EMA_filter' in df.columns: buy_cond &= (df['Close'] > df['EMA_filter'])
    if use_vol and 'Volume_MA' in df.columns: buy_cond &= (df['Volume'] > df['Volume_MA'])
    df.loc[buy_cond, 'signal'] = 'BUY'

    # Conditions Vente (sortie de position)
    sell_cond = (df['EMA_short'] < df['EMA_long']) & (df['EMA_short'].shift(1) >= df['EMA_long'].shift(1))
    # Optionnel: Ajouter condition RSI > rsi_os pour éviter vente en zone survente?
    # sell_cond &= (df['RSI'] > rsi_os)
    df.loc[sell_cond, 'signal'] = 'SELL'

    return df


def check_entry_conditions(
    current_data: pd.Series,
    symbol: str,
    current_config: Dict[str, Any],
    available_balance: Decimal, # Utiliser Decimal
    symbol_info: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Vérifie les conditions d'entrée SWING (signal BUY) et prépare l'ordre MARKET.
    Utilise Decimal et les nouvelles fonctions d'ordre_utils.
    """
    if current_data.get('signal') != 'BUY':
        return None

    logger.info(f"SWING Entry Check: Signal BUY détecté pour {symbol}.")

    try:
        # Utiliser Decimal pour les calculs
        entry_price = Decimal(str(current_data.get('Close'))) # Prix de clôture de la bougie du signal
        if entry_price <= 0: raise ValueError("Prix de clôture invalide")

        # Récupérer les fractions depuis la config
        risk_per_trade_frac = current_config.get("RISK_PER_TRADE", Decimal("0.01"))
        capital_allocation_frac = current_config.get("CAPITAL_ALLOCATION", Decimal("1.0"))
        stop_loss_frac = current_config.get("STOP_LOSS_PERCENTAGE", Decimal("0.02"))

        # Calcul SL et risque
        stop_loss_price = entry_price * (Decimal(1) - stop_loss_frac)
        risk_per_unit = entry_price - stop_loss_price # Différence de prix par unité de base asset

        if risk_per_unit <= 0:
            logger.warning(f"SWING Entry: Risque par unité nul ou négatif (SL={stop_loss_price:.8f}, Entry={entry_price:.8f}).")
            return None

        # --- NOUVELLE LOGIQUE SIZING ---
        max_risk = available_balance * risk_per_trade_frac
        max_capital = available_balance * capital_allocation_frac
        qty_risk = max_risk / risk_per_unit
        qty_capital = max_capital / entry_price
        quantity_unformatted = min(qty_risk, qty_capital)
        # --- FIN NOUVELLE LOGIQUE ---

        # Formater la quantité selon LOT_SIZE
        formatted_quantity = format_quantity(quantity_unformatted, symbol_info)

        if formatted_quantity is None or formatted_quantity <= 0:
            logger.warning(f"SWING Entry: Quantité ({quantity_unformatted:.8f}) invalide après formatage LOT_SIZE.")
            return None

        # Vérifier MIN_NOTIONAL avec la quantité formatée et le prix d'entrée
        min_notional = get_min_notional(symbol_info)
        if not check_min_notional(formatted_quantity, entry_price, min_notional):
            logger.warning(f"SWING Entry: Notionnel ({formatted_quantity * entry_price:.4f}) < MIN_NOTIONAL ({min_notional:.4f}) après formatage Qty. Ordre non placé.")
            return None # Annuler si on veut être strict

        # Vérifier si le notionnel de l'ordre dépasse le capital alloué
        order_notional = formatted_quantity * entry_price
        if order_notional > max_capital:
             logger.warning(f"SWING Entry: Notionnel ordre ({order_notional:.4f}) > capital alloué ({max_capital:.4f}). Ajustement quantité.")
             # Recalculer la quantité basée sur le capital_to_use
             quantity_unformatted = max_capital / entry_price
             formatted_quantity = format_quantity(quantity_unformatted, symbol_info)
             if formatted_quantity is None or formatted_quantity <= 0 or not check_min_notional(formatted_quantity, entry_price, min_notional):
                  logger.error("SWING Entry: Impossible d'ajuster la quantité pour respecter le capital et min_notional.")
                  return None
             logger.info(f"SWING Entry: Quantité ajustée à {formatted_quantity} pour respecter le capital.")

        logger.info(f"SWING Entry: Calcul taille OK. Qty={formatted_quantity} {symbol} (Risque max: {max_risk:.2f}, Capital max: {max_capital:.2f}, SL: {stop_loss_price:.4f})")

        # Préparer l'ordre MARKET
        order_params = {
            "symbol": symbol,
            "side": "BUY",
            "order_type": "MARKET",
            "quantity": formatted_quantity, # Le wrapper convertira en str
        }
        logger.info(f"SWING Entry Signal: Préparation ordre {order_params['side']} {order_params['order_type']} de {order_params['quantity']} {symbol}")
        return order_params

    except (InvalidOperation, TypeError, ValueError, ZeroDivisionError, KeyError) as e:
        logger.error(f"SWING Entry: Erreur calcul/préparation ordre: {e}", exc_info=True)
        return None

# check_exit_conditions reste inchangé...
def check_exit_conditions(
    current_data: pd.Series,
    symbol: str
) -> bool:
    """ Vérifie les conditions de sortie SWING (signal SELL). """
    if current_data.get('signal') == 'SELL':
        logger.info(f"SWING Exit Check: Signal SELL détecté pour {symbol}.")
        return True
    return False

