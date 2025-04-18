import logging
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Optional, Dict, Any, List

import pandas as pd
import pandas_ta as ta

# Importer le wrapper pour les appels API (placer ordre)
import binance_client_wrapper
# Importer la config pour certaines valeurs par défaut si nécessaire (ex: stop loss)
import config

# Configuration du logging (partagé avec bot.py)
logger = logging.getLogger()

# --- Fonctions Utilitaires (format_quantity, calculate_position_size inchangées) ---

def format_quantity(quantity: float, symbol_info: Dict[str, Any]) -> float:
    """
    Formate la quantité selon les règles LOT_SIZE du symbole en utilisant Decimal.
    (Code inchangé par rapport à la version précédente)
    """
    try:
        lot_size_filter = next((f for f in symbol_info.get('filters', []) if f.get('filterType') == 'LOT_SIZE'), None)
        if not lot_size_filter:
            logger.error(f"Filtre LOT_SIZE manquant pour {symbol_info.get('symbol')}")
            return 0.0
        step_size_str = lot_size_filter.get('stepSize')
        min_qty_str = lot_size_filter.get('minQty')
        if not step_size_str or not min_qty_str:
            logger.error(f"stepSize ou minQty manquant dans LOT_SIZE pour {symbol_info.get('symbol')}")
            return 0.0
        step_size = Decimal(step_size_str)
        min_qty = Decimal(min_qty_str)
        quantity_decimal = Decimal(str(quantity))
        formatted_quantity_decimal = (quantity_decimal // step_size) * step_size
        if formatted_quantity_decimal < min_qty:
            logger.warning(f"Quantité formatée {formatted_quantity_decimal} < minQty ({min_qty_str}). Retourne 0.")
            return 0.0
        formatted_quantity = float(formatted_quantity_decimal)
        logger.debug(f"Quantité {quantity} formatée à {formatted_quantity} (step: {step_size_str}, min: {min_qty_str})")
        return formatted_quantity
    except (InvalidOperation, TypeError, ValueError, KeyError, AttributeError) as e:
        logger.error(f"Erreur lors du formatage de la quantité ({quantity}): {e}")
        return 0.0

def calculate_position_size(
    balance: float,
    risk_per_trade: float,
    entry_price: float,
    stop_loss_price: float,
    symbol_info: Dict[str, Any]
) -> float:
    """
    Calcule la taille de la position en fonction du risque, en tenant compte des règles LOT_SIZE et MIN_NOTIONAL.
    (Code inchangé par rapport à la version précédente)
    """
    try:
        if entry_price <= 0 or stop_loss_price <= 0:
            logger.error("Prix d'entrée ou de stop loss invalide (<= 0).")
            return 0.0
        risk_amount = balance * risk_per_trade
        risk_per_unit = abs(entry_price - stop_loss_price)
        if risk_per_unit == 0:
            logger.warning("Calcul taille position: Risque par unité est zéro (entry=stop_loss?).")
            return 0.0
        theoretical_quantity = risk_amount / risk_per_unit
        formatted_quantity = format_quantity(theoretical_quantity, symbol_info)
        if formatted_quantity <= 0:
            return 0.0
        notional_filter = next((f for f in symbol_info.get('filters', []) if f.get('filterType') in ['MIN_NOTIONAL', 'NOTIONAL']), None)
        if notional_filter:
            min_notional_str = notional_filter.get('minNotional')
            if min_notional_str:
                min_notional = float(min_notional_str)
                current_notional = formatted_quantity * entry_price
                if current_notional < min_notional:
                    logger.warning(
                        f"Taille calculée ({formatted_quantity}) trop petite pour {notional_filter['filterType']} "
                        f"({min_notional_str}). Notionnel actuel: {current_notional:.4f}"
                    )
                    return 0.0
        logger.info(
            f"Taille de position calculée: {formatted_quantity}"
            f" (Risque: {risk_amount:.4f}, Risque/unité: {risk_per_unit:.4f})"
        )
        return formatted_quantity
    except (TypeError, ValueError, KeyError, AttributeError, ZeroDivisionError) as e:
        logger.error(f"Erreur lors du calcul de la taille de position: {e}")
        return 0.0

# --- Logique de Stratégie ---

def calculate_indicators_and_signals(
    klines_list: List[List[Any]],
    strategy_config: Dict[str, Any]
) -> Optional[pd.DataFrame]:
    """
    Calcule les indicateurs et génère des signaux sur les données klines fournies.
    (Code inchangé par rapport à la version précédente)
    """
    if not klines_list:
        logger.error("Aucune donnée kline fournie pour calculate_indicators_and_signals.")
        return None
    ema_short = strategy_config.get('EMA_SHORT_PERIOD', 9)
    ema_long = strategy_config.get('EMA_LONG_PERIOD', 21)
    rsi_period = strategy_config.get('RSI_PERIOD', 14)
    rsi_ob = strategy_config.get('RSI_OVERBOUGHT', 75)
    rsi_os = strategy_config.get('RSI_OVERSOLD', 25)
    use_ema_filter = strategy_config.get('USE_EMA_FILTER', True)
    ema_filter = strategy_config.get('EMA_FILTER_PERIOD', 50)
    use_volume_confirm = strategy_config.get('USE_VOLUME_CONFIRMATION', False)
    vol_avg_period = strategy_config.get('VOLUME_AVG_PERIOD', 20)
    try:
        columns = ['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time',
                   'Quote asset volume', 'Number of trades', 'Taker buy base asset volume',
                   'Taker buy quote asset volume', 'Ignore']
        df = pd.DataFrame(klines_list, columns=columns)
        numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'Quote asset volume']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(subset=numeric_cols, inplace=True)
        if df.empty:
            logger.error("DataFrame vide après nettoyage initial.")
            return None
        df.ta.ema(length=ema_short, append=True)
        df.ta.ema(length=ema_long, append=True)
        df.ta.rsi(length=rsi_period, append=True)
        if use_ema_filter: df.ta.ema(length=ema_filter, append=True)
        if use_volume_confirm: df.ta.sma(close='Volume', length=vol_avg_period, prefix='VOL', append=True)
        df.dropna(inplace=True)
        if df.empty:
            logger.error("DataFrame vide après calcul des indicateurs et dropna.")
            return None
        try:
            ema_short_col = df.columns[df.columns.str.startswith(f'EMA_{ema_short}')][0]
            ema_long_col = df.columns[df.columns.str.startswith(f'EMA_{ema_long}')][0]
            rsi_col = df.columns[df.columns.str.startswith(f'RSI_{rsi_period}')][0]
            ema_filter_col = f'EMA_{ema_filter}' if use_ema_filter and f'EMA_{ema_filter}' in df.columns else None
            vol_sma_col = df.columns[df.columns.str.startswith(f'VOL_SMA_{vol_avg_period}')][0] if use_volume_confirm and any(df.columns.str.startswith(f'VOL_SMA_{vol_avg_period}')) else None
        except IndexError as e:
             logger.error(f"Impossible de trouver une colonne d'indicateur attendue: {e}. Colonnes: {df.columns}")
             return None
        buy_condition = (
            (df[ema_short_col] > df[ema_long_col]) &
            (df[ema_short_col].shift(1) <= df[ema_long_col].shift(1)) &
            (df[rsi_col] < rsi_ob)
        )
        if use_ema_filter and ema_filter_col: buy_condition = buy_condition & (df['Close'] > df[ema_filter_col])
        if use_volume_confirm and vol_sma_col: buy_condition = buy_condition & (df['Volume'] > df[vol_sma_col])
        sell_condition = (
            (df[ema_short_col] < df[ema_long_col]) &
            (df[ema_short_col].shift(1) >= df[ema_long_col].shift(1)) &
            (df[rsi_col] > rsi_os)
        )
        df['signal'] = 'HOLD'
        df.loc[buy_condition, 'signal'] = 'BUY'
        df.loc[sell_condition, 'signal'] = 'SELL'
        logger.debug(f"Calcul indicateurs/signaux terminé. Dernier signal: {df.iloc[-1]['signal']}")
        return df
    except KeyError as e:
        logger.error(f"Erreur de clé lors du calcul indicateurs/signaux (colonne manquante?): {e}")
        return None
    except Exception as e:
        logger.exception("Erreur inattendue lors du calcul des indicateurs/signaux.")
        return None

def check_entry_conditions(
    current_data: pd.Series,
    symbol: str,
    risk_per_trade: float,
    capital_allocation: float,
    available_balance: float,
    symbol_info: Dict[str, Any],
    strategy_config: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Vérifie les conditions d'entrée basées sur les indicateurs et place un ordre si nécessaire.
    (Code inchangé par rapport à la version précédente)
    """
    signal = current_data.get('signal')
    if signal == 'BUY':
        logger.info(f"Signal d'ACHAT (indicateur) détecté pour {symbol}!")
        entry_price = current_data.get('Close')
        if entry_price is None or entry_price <= 0:
            logger.error("Prix de clôture invalide pour l'entrée.")
            return None
        stop_loss_percentage = strategy_config.get('STOP_LOSS_PERCENTAGE', config.STOP_LOSS_PERCENTAGE)
        stop_loss_price = entry_price * (1 - stop_loss_percentage)
        effective_balance = available_balance * capital_allocation
        quantity = calculate_position_size(
            effective_balance, risk_per_trade, entry_price, stop_loss_price, symbol_info
        )
        if quantity > 0:
            logger.info(f"Conditions d'entrée remplies. Tentative d'achat de {quantity} {symbol}...")
            order_details = binance_client_wrapper.place_order(
                symbol=symbol, side='BUY', quantity=quantity, order_type='MARKET'
            )
            return order_details
        else:
            logger.warning("Taille de position calculée est 0 ou invalide, pas d'ordre d'achat placé.")
            return None
    return None

def check_exit_conditions(
    current_data: pd.Series,
    symbol: str, # Symbol ajouté pour la cohérence, même si non utilisé ici
    # Les autres paramètres (qty, symbol_info) ne sont plus nécessaires ici
    # car la sortie basée sur indicateur appelle maintenant execute_exit
) -> bool:
    """
    Vérifie UNIQUEMENT si un signal de sortie basé sur les indicateurs est présent.
    Ne place PAS d'ordre ici. Retourne True si signal SELL, False sinon.
    """
    signal = current_data.get('signal')
    if signal == 'SELL':
        logger.info(f"Signal de VENTE (indicateur) détecté pour {symbol}.")
        return True
    return False

# --- Bloc d'Exemple/Test (inchangé) ---
if __name__ == '__main__':
    # ... (code de test inchangé) ...
    pass
