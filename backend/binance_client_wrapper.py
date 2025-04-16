import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
import time

# Importer la configuration pour les clés API et le mode testnet
try:
    import config
    API_KEY = config.BINANCE_API_KEY
    API_SECRET = config.BINANCE_API_SECRET
    USE_TESTNET = getattr(config, 'USE_TESTNET', False) # Par défaut, utiliser l'API réelle
except ImportError:
    logging.error("Fichier config.py non trouvé ou clés API non définies dans binance_client_wrapper.")
    # Utiliser des placeholders ou lever une erreur plus explicite
    API_KEY = "VOTRE_CLE_API_ICI"
    API_SECRET = "VOTRE_SECRET_API_ICI"
    USE_TESTNET = False

# Variable globale pour le client (ou passer le client en argument des fonctions)
_client = None

def get_client():
    """Initialise et retourne le client Binance (API réelle ou testnet)."""
    global _client
    if _client is None:
        try:
            if USE_TESTNET:
                _client = Client(API_KEY, API_SECRET, testnet=True)
                # _client.API_URL = 'https://testnet.binance.vision/api' # Déjà fait par testnet=True
                logging.info("Client Binance initialisé en mode TESTNET.")
            else:
                _client = Client(API_KEY, API_SECRET)
                logging.info("Client Binance initialisé en mode API réelle.")

            _client.ping() # Teste la connexion
            logging.info("Connexion à l'API Binance réussie.")

        except (BinanceAPIException, BinanceRequestException) as e:
            logging.error(f"Erreur API Binance lors de l'initialisation : {e}")
            _client = None
        except Exception as e:
            logging.error(f"Erreur inattendue lors de l'initialisation du client Binance : {e}")
            _client = None
    return _client

def get_klines(symbol, interval, limit=100, retries=3, delay=5):
    """
    Récupère les données klines pour un symbole et un intervalle donnés.
    Gère les erreurs API et les tentatives multiples.

    Args:
        symbol (str): Le symbole (ex: 'BTCUSDT').
        interval (str): L'intervalle (ex: Client.KLINE_INTERVAL_5MINUTE).
        limit (int): Le nombre de klines à récupérer.
        retries (int): Nombre de tentatives en cas d'erreur.
        delay (int): Délai en secondes entre les tentatives.

    Returns:
        list: Liste des klines si succès, None sinon.
    """
    client = get_client()
    if not client:
        return None

    for attempt in range(retries):
        try:
            klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
            logging.debug(f"Klines récupérées pour {symbol} ({interval}), limit={limit}.")
            # Vérifier si les données sont valides (non vides)
            if not klines:
                logging.warning(f"Aucune kline retournée pour {symbol} ({interval}). Tentative {attempt + 1}/{retries}")
                if attempt < retries - 1:
                    time.sleep(delay)
                    continue
                else:
                    logging.error(f"Échec de récupération des klines pour {symbol} après {retries} tentatives (données vides).")
                    return None
            return klines
        except (BinanceAPIException, BinanceRequestException) as e:
            logging.error(f"Erreur API Binance lors de la récupération des klines pour {symbol} ({interval}). Tentative {attempt + 1}/{retries}. Erreur : {e}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                logging.error(f"Échec final de récupération des klines pour {symbol} après {retries} tentatives.")
                return None
        except Exception as e:
            logging.error(f"Erreur inattendue lors de la récupération des klines pour {symbol} ({interval}). Tentative {attempt + 1}/{retries}. Erreur : {e}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                logging.error(f"Échec final de récupération des klines pour {symbol} après {retries} tentatives (erreur inattendue).")
                return None
    return None # Ne devrait pas être atteint, mais pour la clarté

def get_account_balance(asset='USDT'):
    """Récupère le solde disponible pour un actif spécifique."""
    client = get_client()
    if not client:
        return 0.0

    try:
        account_info = client.get_account()
        balance = next((item for item in account_info['balances'] if item["asset"] == asset), None)
        available_balance = float(balance['free']) if balance else 0.0
        logging.info(f"Solde {asset} disponible récupéré : {available_balance}")
        return available_balance
    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"Erreur API Binance lors de la récupération du solde {asset} : {e}")
        return 0.0
    except Exception as e:
        logging.error(f"Erreur inattendue lors de la récupération du solde {asset} : {e}")
        return 0.0

def get_symbol_info(symbol):
    """Récupère les informations et règles de trading pour un symbole."""
    client = get_client()
    if not client:
        return None
    try:
        info = client.get_symbol_info(symbol)
        if info:
            logging.debug(f"Informations récupérées pour le symbole {symbol}.")
            return info
        else:
            logging.error(f"Aucune information trouvée pour le symbole {symbol}.")
            return None
    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"Erreur API Binance lors de la récupération des infos pour {symbol} : {e}")
        return None
    except Exception as e:
        logging.error(f"Erreur inattendue lors de la récupération des infos pour {symbol} : {e}")
        return None

# --- Fonctions de passage d'ordres (à affiner/compléter) ---
# Ces fonctions pourraient être déplacées/combinées avec celles esquissées dans strategy.py

def place_order(symbol, side, quantity, order_type='MARKET', price=None, stop_loss_price=None, take_profit_price=None):
    """
    Place un ordre sur Binance avec gestion d'erreur.

    Args:
        symbol (str): Le symbole (ex: 'BTCUSDT').
        side (str): 'BUY' ou 'SELL'.
        quantity (float): La quantité à acheter/vendre (déjà formatée selon les règles du symbole).
        order_type (str): Le type d'ordre ('MARKET', 'LIMIT', etc.).
        price (float, optional): Le prix pour les ordres LIMIT.
        stop_loss_price (float, optional): Le prix du stop-loss (pour les ordres OCO).
        take_profit_price (float, optional): Le prix du take-profit (pour les ordres OCO).

    Returns:
        dict: Les informations de l'ordre si succès, None sinon.
    """
    client = get_client()
    if not client:
        return None

    try:
        logging.info(f"Tentative de placement d'un ordre {order_type} {side} de {quantity} {symbol.replace('USDT', '')}...")

        if order_type == 'MARKET':
            order = client.create_order(
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity
            )
        elif order_type == 'LIMIT' and price is not None:
            order = client.create_order(
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                price=price
            )
        # elif order_type == 'OCO' and price is not None and stop_loss_price is not None and take_profit_price is not None:
        #     # Gérer les ordres OCO (One-Cancels-the-Other) - Plus complexe, nécessite des validations
        #     # et une gestion précise des prix.  À implémenter avec soin.
        #     # Exemple (à adapter) :
        #     # order = client.create_oco_order(
        #     #     symbol=symbol,
        #     #     side=side,
        #     #     quantity=quantity,
        #     #     price=price, # Prix limite
        #     #     stopPrice=stop_loss_price, # Prix de déclenchement du stop
        #     #     stopLimitPrice=stop_loss_price, # Prix limite du stop
        #     #     stopLimitTimeInForce='GTC'
        #     # )
        #     logging.warning("Les ordres OCO ne sont pas encore implémentés.")
        #     return None # Pour l'instant, ne pas utiliser OCO
        else:
            logging.error(f"Type d'ordre non supporté ou paramètres manquants pour {order_type}.")
            return None

        logging.info(f"Ordre {order_type} {side} placé avec succès pour {quantity} {symbol.replace('USDT', '')}. OrderId: {order.get('orderId')}")
        return order

    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"Erreur API Binance lors du placement de l'ordre {order_type} {side} pour {symbol} : {e}")
        return None
    except Exception as e:
        logging.error(f"Erreur inattendue lors du placement de l'ordre {order_type} {side} pour {symbol} : {e}")
        return None

def place_market_order(symbol, side, quantity):
    """Place un ordre au marché simple."""
    # Utiliser la fonction place_order avec le type d'ordre MARKET
    return place_order(symbol, side, quantity, order_type='MARKET')


# --- Autres fonctions utiles (get_open_orders, cancel_order, etc.) ---
# ... à implémenter selon les besoins ...


# Exemple d'utilisation
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    client_instance = get_client()
    if client_instance:
        print("\n--- Test get_klines ---")
        klines = get_klines('BTCUSDT', Client.KLINE_INTERVAL_1MINUTE, limit=5)
        if klines:
            print(f"Récupéré {len(klines)} klines pour BTCUSDT 1m.")
            # print(klines[-1]) # Afficher la dernière kline
        else:
            print("Échec de la récupération des klines.")

        print("\n--- Test get_account_balance ---")
        balance = get_account_balance('USDT')
        print(f"Solde USDT disponible : {balance}")

        print("\n--- Test get_symbol_info ---")
        info = get_symbol_info('BTCUSDT')
        if info:
            print(f"Filtres pour BTCUSDT récupérés (exemple: LOT_SIZE):")
            lot_size_filter = next((f for f in info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            if lot_size_filter:
                print(f"  minQty: {lot_size_filter.get('minQty')}, maxQty: {lot_size_filter.get('maxQty')}, stepSize: {lot_size_filter.get('stepSize')}")
            else:
                print("  Filtre LOT_SIZE non trouvé.")
        else:
            print("Échec de la récupération des infos symbole.")

        # --- ATTENTION : Le test suivant place un ordre réel si les clés sont valides ! ---
        # print("\n--- Test place_market_order (ATTENTION : ORDRE RÉEL SI CLÉS VALIDES) ---")
        # Décommentez avec prudence et une petite quantité pour tester
        # test_symbol = 'BTCUSDT'
        # test_side = 'BUY'
        # test_quantity = 0.001 # Mettre une quantité valide selon minQty/stepSize !
        # symbol_info_test = get_symbol_info(test_symbol)
        # if symbol_info_test:
        #     lot_size = next((f for f in symbol_info_test['filters'] if f['filterType'] == 'LOT_SIZE'), None)
        #     if lot_size and test_quantity >= float(lot_size['minQty']):
        #         # order_result = place_market_order(test_symbol, test_side, test_quantity)
        #         # if order_result:
        #         #     print("Ordre de test placé (simulé ou réel) :", order_result)
        #         # else:
        #         #     print("Échec du placement de l'ordre de test.")
        #         print(f"Placement d'ordre pour {test_quantity} {test_symbol} non exécuté dans cet exemple.")
        #     else:
        #         print(f"Quantité de test {test_quantity} invalide pour {test_symbol} (minQty: {lot_size.get('minQty') if lot_size else 'N/A'}).")
        # else:
        #      print(f"Impossible de vérifier les règles pour {test_symbol}, ordre non placé.")
    else:
        print("Impossible d'initialiser le client Binance.")
