import pandas as pd
import pandas_ta as ta
import logging
import math # Pour les ajustements de quantité (floor, log10)
import binance_client_wrapper # Import the wrapper

# Importer la configuration (pour les périodes, niveaux RSI, etc.)
try:
    import config
    # Définir les paramètres à partir de config.py ou utiliser des valeurs par défaut
    # Ces valeurs seront écrasées par bot.py lors de la mise à jour via l'API
    EMA_SHORT_PERIOD = getattr(config, 'EMA_SHORT_PERIOD', 9)
    EMA_LONG_PERIOD = getattr(config, 'EMA_LONG_PERIOD', 21)
    EMA_FILTER_PERIOD = getattr(config, 'EMA_FILTER_PERIOD', 50) # Optionnel
    RSI_PERIOD = getattr(config, 'RSI_PERIOD', 14)
    RSI_OVERBOUGHT = getattr(config, 'RSI_OVERBOUGHT', 75)
    RSI_OVERSOLD = getattr(config, 'RSI_OVERSOLD', 25)
    VOLUME_AVG_PERIOD = getattr(config, 'VOLUME_AVG_PERIOD', 20) # Pour la confirmation de volume
    USE_EMA_FILTER = getattr(config, 'USE_EMA_FILTER', True) # Activer/désactiver le filtre EMA long
    USE_VOLUME_CONFIRMATION = getattr(config, 'USE_VOLUME_CONFIRMATION', False) # Activer/désactiver confirmation volume

except ImportError:
    logging.warning("Fichier config.py non trouvé. Utilisation des paramètres par défaut pour la stratégie.")
    # Valeurs par défaut si config.py n'est pas là
    EMA_SHORT_PERIOD = 9
    EMA_LONG_PERIOD = 21
    EMA_FILTER_PERIOD = 50
    RSI_PERIOD = 14
    RSI_OVERBOUGHT = 75
    RSI_OVERSOLD = 25
    VOLUME_AVG_PERIOD = 20
    USE_EMA_FILTER = True
    USE_VOLUME_CONFIRMATION = False


def calculate_indicators(df):
    """
    Calcule les indicateurs techniques nécessaires sur le DataFrame de klines.
    Utilise les paramètres globaux du module (mis à jour par bot.py).
    """
    if df is None or df.empty:
        logging.error("DataFrame vide fourni pour le calcul des indicateurs.")
        return None

    try:
        # Assurer les types de données corrects
        df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
        df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
        df.dropna(subset=['Close', 'Volume'], inplace=True)

        if df.empty:
             logging.error("DataFrame vide après nettoyage des NaN.")
             return None

        # Utiliser les variables globales du module pour les périodes
        df[f'EMA_{EMA_SHORT_PERIOD}'] = ta.ema(df['Close'], length=EMA_SHORT_PERIOD)
        df[f'EMA_{EMA_LONG_PERIOD}'] = ta.ema(df['Close'], length=EMA_LONG_PERIOD)
        if USE_EMA_FILTER:
            df[f'EMA_{EMA_FILTER_PERIOD}'] = ta.ema(df['Close'], length=EMA_FILTER_PERIOD)

        df[f'RSI_{RSI_PERIOD}'] = ta.rsi(df['Close'], length=RSI_PERIOD)

        if USE_VOLUME_CONFIRMATION:
            df[f'Volume_MA_{VOLUME_AVG_PERIOD}'] = ta.sma(df['Volume'], length=VOLUME_AVG_PERIOD)

        df.dropna(inplace=True) # Supprimer les NaN générés par les indicateurs

        return df

    except Exception as e:
        logging.exception(f"Erreur lors du calcul des indicateurs") # Utiliser exception pour traceback
        return None


def generate_signals(df):
    """
    Génère les signaux d'achat (1), de vente (-1) ou neutre (0) basés sur la stratégie.
    Utilise les paramètres globaux du module (mis à jour par bot.py).
    """
    if df is None or df.empty:
        logging.error("DataFrame vide fourni pour la génération de signaux.")
        return None

    # Vérifier que les colonnes nécessaires existent après le calcul des indicateurs
    required_cols = [f'EMA_{EMA_SHORT_PERIOD}', f'EMA_{EMA_LONG_PERIOD}', f'RSI_{RSI_PERIOD}']
    if USE_EMA_FILTER: required_cols.append(f'EMA_{EMA_FILTER_PERIOD}')
    if USE_VOLUME_CONFIRMATION: required_cols.append(f'Volume_MA_{VOLUME_AVG_PERIOD}')

    if not all(col in df.columns for col in required_cols):
        logging.error(f"Colonnes d'indicateurs manquantes dans le DataFrame pour generate_signals. Colonnes présentes: {df.columns.tolist()}")
        return None

    try:
        df['signal'] = 0

        # Conditions de croisement EMA
        condition_crossover_bull = (df[f'EMA_{EMA_SHORT_PERIOD}'] > df[f'EMA_{EMA_LONG_PERIOD}']) & \
                                   (df[f'EMA_{EMA_SHORT_PERIOD}'].shift(1) <= df[f'EMA_{EMA_LONG_PERIOD}'].shift(1))
        condition_crossover_bear = (df[f'EMA_{EMA_SHORT_PERIOD}'] < df[f'EMA_{EMA_LONG_PERIOD}']) & \
                                   (df[f'EMA_{EMA_SHORT_PERIOD}'].shift(1) >= df[f'EMA_{EMA_LONG_PERIOD}'].shift(1))

        # Filtres (utilisant les globales du module)
        condition_ema_filter_long = (df['Close'] > df[f'EMA_{EMA_FILTER_PERIOD}']) if USE_EMA_FILTER else True
        condition_ema_filter_short = (df['Close'] < df[f'EMA_{EMA_FILTER_PERIOD}']) if USE_EMA_FILTER else True
        condition_rsi_ok_long = (df[f'RSI_{RSI_PERIOD}'] < RSI_OVERBOUGHT)
        condition_rsi_ok_short = (df[f'RSI_{RSI_PERIOD}'] > RSI_OVERSOLD)
        condition_volume_ok = (df['Volume'] > df[f'Volume_MA_{VOLUME_AVG_PERIOD}']) if USE_VOLUME_CONFIRMATION else True

        # Application des Conditions
        df.loc[condition_crossover_bull & condition_ema_filter_long & condition_rsi_ok_long & condition_volume_ok, 'signal'] = 1
        df.loc[condition_crossover_bear & condition_ema_filter_short & condition_rsi_ok_short & condition_volume_ok, 'signal'] = -1

        return df

    except KeyError as e:
        logging.error(f"Erreur de clé lors de la génération des signaux (colonne manquante ?) : {e}")
        return None
    except Exception as e:
        logging.exception(f"Erreur lors de la génération des signaux") # Utiliser exception pour traceback
        return None


def calculate_indicators_and_signals(klines_data):
    """
    Fonction principale pour traiter les données klines, calculer les indicateurs et générer les signaux.
    """
    if not klines_data:
        logging.error("Aucune donnée kline fournie.")
        return None

    columns = ['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time',
               'Quote asset volume', 'Number of trades', 'Taker buy base asset volume',
               'Taker buy quote asset volume', 'Ignore']
    try:
        df = pd.DataFrame(klines_data, columns=columns)
        df['Open time'] = pd.to_datetime(df['Open time'], unit='ms')
        df['Close time'] = pd.to_datetime(df['Close time'], unit='ms')
    except Exception as e:
        logging.error(f"Erreur lors de la création ou conversion du DataFrame initial: {e}")
        return None

    df_with_indicators = calculate_indicators(df.copy())
    if df_with_indicators is None:
        logging.error("Échec du calcul des indicateurs.")
        return None

    df_with_signals = generate_signals(df_with_indicators.copy())
    if df_with_signals is None:
        logging.error("Échec de la génération des signaux.")
        return None

    logging.info("Indicateurs et signaux calculés avec succès.")
    return df_with_signals

# --- Fonctions pour la gestion des ordres ---

def calculate_position_size(account_balance, risk_per_trade, entry_price, stop_loss_price, symbol_info):
    """
    Calcule la taille de la position en fonction du risque, en tenant compte des règles de Binance.
    """
    if account_balance <= 0:
        logging.error("Solde du compte invalide pour calculer la taille de position.")
        return 0
    if entry_price <= 0 or stop_loss_price <= 0:
        logging.error("Prix d'entrée ou stop-loss invalide.")
        return 0
    if not symbol_info or 'filters' not in symbol_info:
        logging.error("Informations symbole invalides ou filtre manquant.")
        return 0

    try:
        risk_amount = account_balance * risk_per_trade
        stop_loss_distance = abs(entry_price - stop_loss_price)

        if stop_loss_distance == 0:
            logging.error("Distance du stop-loss est zéro. Impossible de calculer la taille.")
            return 0

        theoretical_quantity = risk_amount / stop_loss_distance

        lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
        if not lot_size_filter:
            logging.error("Filtre LOT_SIZE non trouvé.")
            return 0

        min_qty = float(lot_size_filter.get('minQty', 0))
        max_qty = float(lot_size_filter.get('maxQty', float('inf'))) # Utiliser infini si non défini
        step_size = float(lot_size_filter.get('stepSize', 0))

        if step_size <= 0:
             logging.error(f"Step size invalide ({step_size}) pour {symbol_info.get('symbol')}")
             return 0

        # Calculer le nombre de décimales à partir de step_size
        decimal_places = int(-math.log10(step_size))

        # Arrondir la quantité vers le bas au multiple de step_size
        quantity = math.floor(theoretical_quantity / step_size) * step_size
        # Formater pour éviter les problèmes de précision flottante (optionnel mais plus sûr)
        quantity = float(f"{quantity:.{decimal_places}f}")

        if quantity < min_qty:
            logging.warning(f"Quantité calculée ({quantity}) < minQty ({min_qty}). Aucune position prise.")
            return 0
        if quantity > max_qty:
            logging.warning(f"Quantité calculée ({quantity}) > maxQty ({max_qty}). Ajustement à maxQty.")
            quantity = max_qty
            # Re-vérifier minQty après ajustement
            if quantity < min_qty:
                 logging.error(f"maxQty ({max_qty}) < minQty ({min_qty}). Problème de configuration symbole?")
                 return 0

        # Vérification Notional (valeur minimale de l'ordre en USDT)
        notional_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'NOTIONAL'), None)
        if notional_filter:
            min_notional = float(notional_filter.get('minNotional', 0))
            order_value = quantity * entry_price
            if order_value < min_notional:
                logging.warning(f"Valeur notionnelle de l'ordre ({order_value:.2f}) < minNotional ({min_notional}). Aucune position prise.")
                return 0

        logging.info(f"Taille de position calculée : {quantity} (risque : {risk_amount:.2f} USDT, distance SL : {stop_loss_distance:.4f})")
        return quantity

    except Exception as e:
        logging.exception(f"Erreur lors du calcul de la taille de la position") # Utiliser exception
        return 0


def check_entry_conditions(current_signal_data, symbol, risk_per_trade, capital_allocation, available_balance, symbol_info):
    """
    Vérifie s'il faut entrer en position et place l'ordre si toutes les conditions sont remplies.
    Utilise le client géré par binance_client_wrapper.
    """
    try:
        signal = current_signal_data.get('signal', 0) # Utiliser .get pour éviter KeyError
        if signal == 0:
            return False

        side = 'BUY' if signal == 1 else 'SELL'
        logging.info(f"*** Signal d'entrée {side} identifié pour {symbol} ***")

        entry_price = current_signal_data.get('Close')
        if entry_price is None:
             logging.error("Prix de clôture manquant dans les données pour check_entry_conditions.")
             return False

        # Exemple simple de stop-loss (à améliorer potentiellement avec ATR, etc.)
        stop_loss_percent = 0.003 # 0.3%
        stop_loss_price = entry_price * (1 - stop_loss_percent) if side == 'BUY' else entry_price * (1 + stop_loss_percent)

        quantity = calculate_position_size(available_balance, risk_per_trade, entry_price, stop_loss_price, symbol_info)
        if quantity <= 0: # Vérifier <= 0 car calculate_position_size retourne 0 en cas d'erreur/quantité invalide
            # L'erreur est déjà loggée par calculate_position_size
            return False

        logging.info(f"Tentative de placement d'ordre {side} {quantity} {symbol} au marché...")
        order = binance_client_wrapper.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type='MARKET'
        )

        # place_order retourne l'ordre en cas de succès, None en cas d'échec
        return order is not None

    except Exception as e:
        logging.exception(f"Erreur lors de la vérification des conditions d'entrée")
        return False

def check_exit_conditions(symbol):
    """Vérifie s'il faut sortir d'une position existante (TP/SL/Signal inverse)."""
    # Placeholder - Logique à implémenter
    # 1. Récupérer la position actuelle (si elle existe) via le wrapper
    # 2. Récupérer le prix actuel via le wrapper
    # 3. Calculer les indicateurs/signaux actuels
    # 4. Vérifier les conditions de sortie :
    #    - Atteinte du Take Profit (si défini)
    #    - Atteinte du Stop Loss (si défini)
    #    - Signal inverse sur les indicateurs
    # 5. Si une condition de sortie est remplie, placer un ordre MARKET inverse via le wrapper
    #    pour clôturer la position.
    # 6. Mettre à jour bot_state['in_position'] = False dans bot.py après la clôture.
    logging.debug(f"Vérification des conditions de sortie pour {symbol} (non implémenté).")
    pass # Retourner True si la position a été clôturée, False sinon

# Exemple d'utilisation (pourrait être dans bot.py)
if __name__ == '__main__':
    # ... (code d'exemple inchangé) ...
    logging.basicConfig(level=logging.INFO)
    dummy_klines = [
        [1678886400000, '27000', '27100', '26900', '27050', '100', 1678886699999, '2705000', 1000, '50', '1352500', '0'],
        [1678886700000, '27050', '27200', '27000', '27150', '120', 1678886999999, '3258000', 1200, '60', '1629000', '0'],
    ] * 100

    required_length = max(EMA_SHORT_PERIOD, EMA_LONG_PERIOD, EMA_FILTER_PERIOD if USE_EMA_FILTER else 0, RSI_PERIOD, VOLUME_AVG_PERIOD if USE_VOLUME_CONFIRMATION else 0) + 5

    if len(dummy_klines) > required_length:
        results = calculate_indicators_and_signals(dummy_klines)
        if results is not None:
            print("Calculs terminés. Dernières lignes avec signaux :")
            print(results.tail())
            print("\nSignaux générés (1=Achat, -1=Vente):")
            print(results[results['signal'] != 0]['signal'])
        else:
            print("Erreur lors du calcul.")
    else:
        print(f"Pas assez de données simulées ({len(dummy_klines)}) pour calculer les indicateurs (besoin > {required_length}).")

    dummy_symbol_info = {
        'symbol': 'BTCUSDT',
        'filters': [
            {'filterType': 'PRICE_FILTER', 'minPrice': '0.01', 'maxPrice': '1000000.00', 'tickSize': '0.01'},
            {'filterType': 'LOT_SIZE', 'minQty': '0.00001', 'maxQty': '9000.0', 'stepSize': '0.00001'},
            {'filterType': 'NOTIONAL', 'minNotional': '10.0', 'applyMinToMarket': True, 'maxNotional': '9000000.0', 'avgPriceMins': 5},
            # ... autres filtres ...
        ]
    }
    print("\nExemple calcul taille position:")
    qty = calculate_position_size(1000, 0.01, 27000, 26900, dummy_symbol_info)
    print(f"Quantité calculée: {qty}")
    qty_notional_fail = calculate_position_size(100, 0.01, 27000, 26900, dummy_symbol_info) # Devrait échouer sur minNotional
    print(f"Quantité calculée (échec notional attendu): {qty_notional_fail}")
    qty_minqty_fail = calculate_position_size(1000, 0.00001, 27000, 26999, dummy_symbol_info) # Devrait échouer sur minQty
    print(f"Quantité calculée (échec minQty attendu): {qty_minqty_fail}")

