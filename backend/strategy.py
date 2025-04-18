import logging
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
import pandas_ta as ta

# Importer le wrapper pour les appels API (placer ordre)
import binance_client_wrapper
# Importer la config pour certaines valeurs par défaut si nécessaire (ex: stop loss)
import config

# Configuration du logging (partagé avec bot.py)
logger = logging.getLogger()

# --- Fonctions Utilitaires ---

def format_quantity(quantity: float, symbol_info: Dict[str, Any]) -> float:
    """
    Formate la quantité selon les règles LOT_SIZE du symbole en utilisant Decimal.

    Args:
        quantity: La quantité théorique.
        symbol_info: Informations du symbole de Binance.

    Returns:
        Quantité formatée, ou 0.0 si erreur ou formatage impossible.
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
        quantity_decimal = Decimal(str(quantity)) # Conversion float -> str -> Decimal pour précision

        # Arrondir vers le bas (floor) au multiple de step_size
        # formatted_quantity_decimal = quantity_decimal.quantize(step_size, rounding=ROUND_DOWN) # Arrondi aux décimales
        formatted_quantity_decimal = (quantity_decimal // step_size) * step_size # Arrondi au multiple inférieur

        # Vérifier si la quantité formatée est >= minQty
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

    Args:
        balance: Solde disponible (ou alloué) de l'asset de cotation (ex: USDT).
        risk_per_trade: Pourcentage du capital à risquer (ex: 0.01 pour 1%).
        entry_price: Prix d'entrée prévu.
        stop_loss_price: Prix du stop-loss prévu.
        symbol_info: Informations du symbole de Binance.

    Returns:
        Quantité formatée à trader, ou 0.0 si invalide ou erreur.
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
            # format_quantity a déjà loggué l'erreur ou l'avertissement
            return 0.0

        # Vérifier MIN_NOTIONAL (ou NOTIONAL pour les ordres MARKET)
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

    Args:
        klines_list: Liste de listes contenant les données klines de Binance.
        strategy_config: Dictionnaire contenant les paramètres de la stratégie
                         (EMA_SHORT_PERIOD, RSI_PERIOD, USE_EMA_FILTER, etc.).

    Returns:
        DataFrame Pandas avec indicateurs et signaux, ou None si erreur.
    """
    if not klines_list:
        logger.error("Aucune donnée kline fournie pour calculate_indicators_and_signals.")
        return None

    # Récupérer les paramètres depuis la config passée
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
        # 1. Créer le DataFrame
        columns = ['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time',
                   'Quote asset volume', 'Number of trades', 'Taker buy base asset volume',
                   'Taker buy quote asset volume', 'Ignore']
        df = pd.DataFrame(klines_list, columns=columns)

        # 2. Convertir les types et nettoyer
        numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'Quote asset volume']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(subset=numeric_cols, inplace=True)
        if df.empty:
            logger.error("DataFrame vide après nettoyage initial.")
            return None
        # df['Close time'] = pd.to_datetime(df['Close time'], unit='ms') # Optionnel pour affichage

        # 3. Calculer les indicateurs avec pandas_ta
        df.ta.ema(length=ema_short, append=True)
        df.ta.ema(length=ema_long, append=True)
        df.ta.rsi(length=rsi_period, append=True)
        if use_ema_filter:
            df.ta.ema(length=ema_filter, append=True)
        if use_volume_confirm:
            df.ta.sma(close='Volume', length=vol_avg_period, prefix='VOL', append=True)

        # Supprimer les lignes avec NaN générés par les indicateurs
        df.dropna(inplace=True)
        if df.empty:
            logger.error("DataFrame vide après calcul des indicateurs et dropna.")
            return None

        # 4. Générer les signaux
        # Trouver les noms de colonnes générés par pandas_ta
        try:
            ema_short_col = df.columns[df.columns.str.startswith(f'EMA_{ema_short}')][0]
            ema_long_col = df.columns[df.columns.str.startswith(f'EMA_{ema_long}')][0]
            rsi_col = df.columns[df.columns.str.startswith(f'RSI_{rsi_period}')][0]
            ema_filter_col = f'EMA_{ema_filter}' if use_ema_filter and f'EMA_{ema_filter}' in df.columns else None
            vol_sma_col = df.columns[df.columns.str.startswith(f'VOL_SMA_{vol_avg_period}')][0] if use_volume_confirm and any(df.columns.str.startswith(f'VOL_SMA_{vol_avg_period}')) else None
        except IndexError as e:
             logger.error(f"Impossible de trouver une colonne d'indicateur attendue: {e}. Colonnes: {df.columns}")
             return None

        # Conditions d'achat (Long)
        buy_condition = (
            (df[ema_short_col] > df[ema_long_col]) &
            (df[ema_short_col].shift(1) <= df[ema_long_col].shift(1)) &
            (df[rsi_col] < rsi_ob)
        )

        if use_ema_filter and ema_filter_col:
            buy_condition = buy_condition & (df['Close'] > df[ema_filter_col])

        if use_volume_confirm and vol_sma_col:
            buy_condition = buy_condition & (df['Volume'] > df[vol_sma_col])

        # Conditions de vente (Sortie de Long)
        sell_condition = (
            (df[ema_short_col] < df[ema_long_col]) &
            (df[ema_short_col].shift(1) >= df[ema_long_col].shift(1)) &
            (df[rsi_col] > rsi_os)
        )

        # Appliquer les conditions pour créer la colonne 'signal'
        df['signal'] = 'HOLD' # Par défaut
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
    strategy_config: Dict[str, Any] # Ajouté pour le stop loss
) -> Optional[Dict[str, Any]]:
    """
    Vérifie les conditions d'entrée et place un ordre si nécessaire.

    Args:
        current_data: Données de la dernière bougie (incluant signaux).
        symbol: Symbole de trading.
        risk_per_trade: Risque par trade (ex: 0.01).
        capital_allocation: Allocation du capital (ex: 1.0).
        available_balance: Solde disponible de l'asset de cotation.
        symbol_info: Informations du symbole Binance.
        strategy_config: Configuration de la stratégie (pour stop loss).

    Returns:
        Détails de l'ordre (dict) si placé, None sinon.
    """
    signal = current_data.get('signal')

    if signal == 'BUY':
        logger.info(f"Signal d'ACHAT détecté pour {symbol}!")

        entry_price = current_data.get('Close')
        if entry_price is None or entry_price <= 0:
            logger.error("Prix de clôture invalide pour l'entrée.")
            return None

        # Définir un stop-loss (exemple simple basé sur % de config)
        stop_loss_percentage = strategy_config.get('STOP_LOSS_PERCENTAGE', config.STOP_LOSS_PERCENTAGE) # Utilise config comme fallback
        stop_loss_price = entry_price * (1 - stop_loss_percentage)

        # Calculer la taille de la position
        effective_balance = available_balance * capital_allocation
        quantity = calculate_position_size(
            effective_balance, risk_per_trade, entry_price, stop_loss_price, symbol_info
        )

        if quantity > 0:
            logger.info(f"Conditions d'entrée remplies. Tentative d'achat de {quantity} {symbol}...")
            order_details = binance_client_wrapper.place_order(
                symbol=symbol,
                side='BUY',
                quantity=quantity, # Quantité déjà formatée
                order_type='MARKET'
            )
            # place_order retourne les détails ou None (et logue déjà)
            return order_details
        else:
            logger.warning("Taille de position calculée est 0 ou invalide, pas d'ordre d'achat placé.")
            return None

    return None # Pas de signal BUY

def check_exit_conditions(
    current_data: pd.Series,
    symbol: str,
    current_quantity: float,
    symbol_info: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Vérifie les conditions de sortie (signal SELL) et place un ordre si nécessaire.

    Args:
        current_data: Données de la dernière bougie (incluant signaux).
        symbol: Symbole de trading.
        current_quantity: Quantité actuelle détenue de l'asset de base.
        symbol_info: Informations du symbole Binance.

    Returns:
        Détails de l'ordre (dict) si placé, None sinon.
    """
    signal = current_data.get('signal')

    if signal == 'SELL':
        logger.info(f"Signal de VENTE (sortie) détecté pour {symbol}!")

        # Formater la quantité à vendre pour respecter les règles
        quantity_to_sell = format_quantity(current_quantity, symbol_info)

        if quantity_to_sell > 0:
            logger.info(f"Conditions de sortie remplies. Tentative de vente de {quantity_to_sell} {symbol}...")
            order_details = binance_client_wrapper.place_order(
                symbol=symbol,
                side='SELL',
                quantity=quantity_to_sell, # Quantité déjà formatée
                order_type='MARKET'
            )
            # place_order retourne les détails ou None (et logue déjà)
            return order_details
        else:
            logger.warning(f"Quantité à vendre ({current_quantity}) formatée à 0 ou invalide, pas d'ordre de vente placé.")
            return None

    return None # Pas de signal SELL


# --- Bloc d'Exemple/Test ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger.info("Exécution du bloc de test de strategy.py")

    # Simuler une configuration de stratégie
    test_strategy_config = {
        "EMA_SHORT_PERIOD": 9, "EMA_LONG_PERIOD": 21, "RSI_PERIOD": 14,
        "RSI_OVERBOUGHT": 75, "RSI_OVERSOLD": 25, "USE_EMA_FILTER": True,
        "EMA_FILTER_PERIOD": 50, "USE_VOLUME_CONFIRMATION": False,
        "VOLUME_AVG_PERIOD": 20, "STOP_LOSS_PERCENTAGE": 0.02
    }

    # Simuler des données klines
    base_price = 27000
    dummy_klines = []
    for i in range(200):
        open_p = base_price + (i % 10) * 10
        high_p = open_p + 50
        low_p = open_p - 50
        close_p = low_p + 70 + (i % 5) * 5
        volume = 100 + (i % 20) * 5
        timestamp = 1678886400000 + i * 60000
        dummy_klines.append([
            timestamp, str(open_p), str(high_p), str(low_p), str(close_p), str(volume),
            timestamp + 59999, str(close_p * volume / 10), 100 + i, str(volume / 2), str(close_p * volume / 20), '0'
        ])

    # Calculer la longueur requise pour les indicateurs
    required_length = max(
        test_strategy_config['EMA_LONG_PERIOD'],
        test_strategy_config['EMA_FILTER_PERIOD'] if test_strategy_config['USE_EMA_FILTER'] else 0,
        test_strategy_config['RSI_PERIOD'],
        test_strategy_config['VOLUME_AVG_PERIOD'] if test_strategy_config['USE_VOLUME_CONFIRMATION'] else 0
    ) + 5 # Marge de sécurité

    print(f"\n--- Test calculate_indicators_and_signals ---")
    if len(dummy_klines) >= required_length:
        results_df = calculate_indicators_and_signals(dummy_klines, test_strategy_config)
        if results_df is not None and not results_df.empty:
            print("Calculs terminés. Dernières lignes avec signaux :")
            print(results_df.tail())
            print("\nSignaux générés (uniquement BUY/SELL):")
            print(results_df[results_df['signal'] != 'HOLD']['signal'])
        else:
            print("Erreur lors du calcul ou DataFrame vide après calcul.")
    else:
        print(f"Pas assez de données simulées ({len(dummy_klines)}) pour calculer les indicateurs (besoin >= {required_length}).")

    # Simuler symbol_info pour les tests suivants
    dummy_symbol_info = {
        'symbol': 'BTCUSDT',
        'filters': [
            {'filterType': 'PRICE_FILTER', 'minPrice': '0.01', 'maxPrice': '1000000.00', 'tickSize': '0.01'},
            {'filterType': 'LOT_SIZE', 'minQty': '0.00001000', 'maxQty': '9000.00000000', 'stepSize': '0.00001000'},
            {'filterType': 'NOTIONAL', 'minNotional': '10.00000000', 'applyMinToMarket': True, 'maxNotional': '9000000.00000000', 'avgPriceMins': 5},
            # ... autres filtres ...
        ]
    }

    print("\n--- Test calculate_position_size ---")
    qty = calculate_position_size(1000.0, 0.01, 27000.0, 26900.0, dummy_symbol_info)
    print(f"Quantité calculée pour 1000 USDT, risque 1%, entrée 27k, SL 26.9k: {qty}")
    qty_too_small = calculate_position_size(10.0, 0.01, 27000.0, 26900.0, dummy_symbol_info)
    print(f"Quantité calculée pour 10 USDT (devrait être 0 car < minNotional): {qty_too_small}")

    print("\n--- Test check_entry_conditions (simulation) ---")
    if results_df is not None and not results_df.empty:
        last_data = results_df.iloc[-1].copy()
        last_data['signal'] = 'BUY' # Forcer un signal d'achat
        print(f"Test avec signal BUY, solde 1000 USDT...")
        # Simuler un appel (ne place pas d'ordre réel car le wrapper n'est pas initialisé ici)
        # result = check_entry_conditions(last_data, 'BTCUSDT', 0.01, 1.0, 1000.0, dummy_symbol_info, test_strategy_config)
        # print(f"Résultat simulation check_entry_conditions: {result}") # Devrait être None car place_order échoue
        print("Simulation d'appel à check_entry_conditions (pas d'ordre réel placé).")
    else:
        print("Impossible de tester check_entry_conditions car les calculs précédents ont échoué.")

    print("\n--- Test check_exit_conditions (simulation) ---")
    if results_df is not None and not results_df.empty:
        last_data = results_df.iloc[-1].copy()
        last_data['signal'] = 'SELL' # Forcer un signal de vente
        print(f"Test avec signal SELL, quantité détenue 0.1 BTC...")
        # Simuler un appel
        # result = check_exit_conditions(last_data, 'BTCUSDT', 0.1, dummy_symbol_info)
        # print(f"Résultat simulation check_exit_conditions: {result}") # Devrait être None
        print("Simulation d'appel à check_exit_conditions (pas d'ordre réel placé).")
    else:
        print("Impossible de tester check_exit_conditions car les calculs précédents ont échoué.")

