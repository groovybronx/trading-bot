# /Users/davidmichels/Desktop/trading-bot/backend/strategies/swing_strategy.py
import logging
import pandas as pd
import pandas_ta as ta
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any, List

# Importer les utilitaires partagés
from utils.order_utils import format_quantity, get_min_notional

logger = logging.getLogger(__name__)

def calculate_indicators_and_signals(
    kline_data: List[List[Any]],
    config_dict: Dict[str, Any]
) -> Optional[pd.DataFrame]:
    """
    Calcule les indicateurs techniques (EMA, RSI, Volume MA) et génère des signaux
    basés sur la stratégie de croisement EMA/RSI.
    """
    if not kline_data:
        logger.warning("SWING: Données kline vides fournies pour calcul indicateurs.")
        return None

    columns = ['Open_Time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close_Time',
               'Quote_Asset_Volume', 'Number_of_Trades', 'Taker_Buy_Base_Asset_Volume',
               'Taker_Buy_Quote_Asset_Volume', 'Ignore']
    df = pd.DataFrame(kline_data, columns=columns)

    try:
        for col in ['Open', 'High', 'Low', 'Close', 'Volume', 'Quote_Asset_Volume',
                    'Taker_Buy_Base_Asset_Volume', 'Taker_Buy_Quote_Asset_Volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['Open_Time'] = pd.to_datetime(df['Open_Time'], unit='ms', errors='coerce')
        df['Close_Time'] = pd.to_datetime(df['Close_Time'], unit='ms', errors='coerce')

        essential_cols = ['Open_Time', 'Open', 'High', 'Low', 'Close', 'Volume']
        df.dropna(subset=essential_cols, inplace=True)

        if df.empty:
            logger.warning("SWING: DataFrame vide après nettoyage des données kline.")
            return None

    except Exception as e:
        logger.error(f"SWING: Erreur lors de la conversion/nettoyage des données kline: {e}", exc_info=True)
        return None

    try:
        ema_short_len = config_dict.get('EMA_SHORT_PERIOD', 9)
        ema_long_len = config_dict.get('EMA_LONG_PERIOD', 21)
        rsi_len = config_dict.get('RSI_PERIOD', 14)
        use_ema_filter = config_dict.get('USE_EMA_FILTER', False)
        ema_filter_len = config_dict.get('EMA_FILTER_PERIOD', 50)
        use_vol_confirm = config_dict.get('USE_VOLUME_CONFIRMATION', False)
        vol_ma_len = config_dict.get('VOLUME_AVG_PERIOD', 20)

        df.ta.ema(length=ema_short_len, append=True, col_names=('EMA_short',))
        df.ta.ema(length=ema_long_len, append=True, col_names=('EMA_long',))
        df.ta.rsi(length=rsi_len, append=True, col_names=('RSI',))

        if use_ema_filter:
            df.ta.ema(length=ema_filter_len, append=True, col_names=('EMA_filter',))
        if use_vol_confirm:
            df.ta.sma(close='Volume', length=vol_ma_len, append=True, col_names=('Volume_MA',))

        df.dropna(inplace=True)
        if df.empty:
            logger.warning("SWING: DataFrame vide après calcul indicateurs (historique insuffisant?).")
            return None

    except Exception as e:
        logger.error(f"SWING: Erreur lors du calcul des indicateurs TA: {e}", exc_info=True)
        return None

    df['signal'] = 'NONE'
    rsi_ob = config_dict.get('RSI_OVERBOUGHT', 75)
    rsi_os = config_dict.get('RSI_OVERSOLD', 25)

    buy_cond_ema_cross = (df['EMA_short'] > df['EMA_long']) & (df['EMA_short'].shift(1) <= df['EMA_long'].shift(1))
    buy_cond_rsi = (df['RSI'] < rsi_ob)
    buy_conditions = buy_cond_ema_cross & buy_cond_rsi

    if use_ema_filter and 'EMA_filter' in df.columns:
        buy_conditions &= (df['Close'] > df['EMA_filter'])
    if use_vol_confirm and 'Volume_MA' in df.columns:
        buy_conditions &= (df['Volume'] > df['Volume_MA'])

    df.loc[buy_conditions, 'signal'] = 'BUY'

    sell_cond_ema_cross = (df['EMA_short'] < df['EMA_long']) & (df['EMA_short'].shift(1) >= df['EMA_long'].shift(1))
    sell_conditions = sell_cond_ema_cross
    df.loc[sell_conditions, 'signal'] = 'SELL'

    # logger.debug(f"SWING: Indicateurs et signaux calculés. Dernier signal: {df['signal'].iloc[-1] if not df.empty else 'N/A'}") # Commenté
    return df

def check_entry_conditions(
    current_data: pd.Series,
    symbol: str,
    current_config: Dict[str, Any],
    available_balance: float,
    symbol_info: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Vérifie les conditions d'entrée SWING (signal BUY) et prépare l'ordre MARKET.
    """
    if current_data.get('signal') != 'BUY':
        return None

    logger.info(f"SWING Entry Check: Signal BUY détecté pour {symbol}.")

    try:
        entry_price_str = current_data.get('Close')
        if entry_price_str is None: raise ValueError("Prix de clôture manquant dans current_data")
        entry_price = Decimal(str(entry_price_str))

        risk_per_trade = Decimal(str(current_config.get("RISK_PER_TRADE", 0.01)))
        capital_allocation = Decimal(str(current_config.get("CAPITAL_ALLOCATION", 1.0)))
        stop_loss_pct = Decimal(str(current_config.get("STOP_LOSS_PERCENTAGE", 0.02)))

        stop_loss_price = entry_price * (Decimal(1) - stop_loss_pct)
        risk_per_unit = entry_price - stop_loss_price

        if risk_per_unit <= 0:
            logger.warning(f"SWING Entry: Risque par unité nul ou négatif (SL={stop_loss_price:.8f}, Entry={entry_price:.8f}).")
            return None

        capital_to_use = Decimal(str(available_balance)) * capital_allocation
        capital_to_risk = capital_to_use * risk_per_trade
        quantity_decimal = capital_to_risk / risk_per_unit

        formatted_quantity = format_quantity(float(quantity_decimal), symbol_info)
        if formatted_quantity <= 0:
            logger.warning(f"SWING Entry: Quantité calculée ({quantity_decimal:.8f}) invalide ou nulle après formatage.")
            return None

        min_notional = get_min_notional(symbol_info)
        order_notional = formatted_quantity * float(entry_price)

        if order_notional < min_notional:
            logger.warning(f"SWING Entry: Notionnel calculé ({order_notional:.4f}) < MIN_NOTIONAL ({min_notional:.4f}). Ordre non placé.")
            return None

        if order_notional > float(capital_to_use):
             logger.error(f"SWING Entry: Notionnel ({order_notional:.4f}) dépasse le capital alloué ({float(capital_to_use):.4f}). Ordre annulé.")
             return None

        logger.info(f"SWING Entry: Calcul taille position OK. Quantité={formatted_quantity} {symbol} (Risque: {capital_to_risk:.2f}, SL: {stop_loss_price:.4f})")

        order_params = {
            "symbol": symbol,
            "side": "BUY",
            "quantity": formatted_quantity,
            "order_type": "MARKET",
        }
        logger.info(f"SWING Entry Signal: Préparation ordre {order_params['side']} {order_params['order_type']} de {order_params['quantity']} {symbol}")
        return order_params

    except (InvalidOperation, TypeError, ValueError, ZeroDivisionError, KeyError) as e:
        logger.error(f"SWING Entry: Erreur calcul taille/préparation ordre: {e}", exc_info=True)
        return None

def check_exit_conditions(
    current_data: pd.Series,
    symbol: str
) -> bool:
    """
    Vérifie les conditions de sortie SWING (signal SELL).
    """
    if current_data.get('signal') == 'SELL':
        logger.info(f"SWING Exit Check: Signal SELL détecté pour {symbol}.")
        return True
    return False
