import logging
import threading
import time
from typing import Optional, List, Dict, Any

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# Importer la configuration pour les clés API et le mode testnet
try:
    import config
    API_KEY = config.BINANCE_API_KEY
    API_SECRET = config.BINANCE_API_SECRET
    USE_TESTNET = getattr(config, 'USE_TESTNET', False)
except ImportError:
    logging.error("Fichier config.py non trouvé ou clés API non définies dans binance_client_wrapper.")
    API_KEY = "YOUR_API_KEY"
    API_SECRET = "YOUR_SECRET_KEY"
    USE_TESTNET = False

# Variable globale pour le client et lock pour la gestion thread-safe
_client: Optional[Client] = None
_client_lock = threading.Lock()

# Configuration du logging (partagé avec bot.py)
logger = logging.getLogger()

def get_client() -> Optional[Client]:
    """
    Initialise et retourne le client Binance (API réelle ou testnet) de manière thread-safe.
    Retourne None si l'initialisation échoue.
    """
    global _client
    with _client_lock:
        if _client is None:
            try:
                if not API_KEY or not API_SECRET or API_KEY == "YOUR_API_KEY" or API_SECRET == "YOUR_SECRET_KEY":
                    logger.error("Clés API Binance non configurées ou invalides dans config.py.")
                    return None

                if USE_TESTNET:
                    _client = Client(API_KEY, API_SECRET, testnet=True)
                    logger.info("Client Binance initialisé en mode TESTNET.")
                else:
                    _client = Client(API_KEY, API_SECRET)
                    logger.info("Client Binance initialisé en mode API réelle.")

                _client.ping()
                logger.info("Connexion à l'API Binance réussie (ping OK).")

            except (BinanceAPIException, BinanceRequestException) as e:
                logger.error(f"Erreur API Binance lors de l'initialisation : {e}")
                _client = None
            except Exception as e:
                # Utiliser logging.exception pour inclure la traceback
                logger.exception(f"Erreur inattendue lors de l'initialisation du client Binance : {e}")
                _client = None
        return _client

def get_klines(
    symbol: str,
    interval: str,
    limit: int = 100,
    retries: int = 3,
    delay: int = 5
) -> Optional[List[List[Any]]]:
    """
    Récupère les données klines pour un symbole et un intervalle donnés.
    Gère les erreurs API et les tentatives multiples.

    Returns:
        Liste de klines ou None en cas d'échec final.
    """
    client = get_client()
    if not client:
        logger.error("Client Binance non initialisé pour get_klines.")
        return None

    for attempt in range(retries):
        try:
            klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
            logger.debug(f"Klines récupérées pour {symbol} ({interval}), limit={limit}.")

            # Vérifier si la liste est vide (peut arriver pour des symboles/intervalles sans données récentes)
            if not klines:
                logger.warning(f"Aucune kline retournée pour {symbol} ({interval}). Tentative {attempt + 1}/{retries}")
                if attempt < retries - 1:
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Échec de récupération des klines pour {symbol} après {retries} tentatives (données vides).")
                    return None # Échec final après retries si toujours vide
            if isinstance(klines, list) and all(isinstance(item, list) for item in klines):
                return klines # Succès - Confirmed it's a list of lists
            else:
                # This case *shouldn't* happen based on API behavior, but handles Pylance's concern
                # and potential unexpected API changes.
                logger.error(f"Type inattendu reçu de client.get_klines pour {symbol}: {type(klines)}. Attendu: List[List[Any]]")
                return None # Return None as per the function's type hint on failure/unexpected type

        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(
                f"Erreur API Binance lors de la récupération des klines pour {symbol} ({interval}). "
                f"Tentative {attempt + 1}/{retries}. Erreur : {e}"
            )
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                logger.error(f"Échec final de récupération des klines pour {symbol} après {retries} tentatives.")
                return None # Échec final après retries
        except Exception as e:
            logger.exception(
                f"Erreur inattendue lors de la récupération des klines pour {symbol} ({interval}). "
                f"Tentative {attempt + 1}/{retries}."
            )
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                logger.error(f"Échec final de récupération des klines pour {symbol} après {retries} tentatives (erreur inattendue).")
                return None # Échec final après retries
    return None # Si la boucle se termine sans succès (ne devrait pas arriver logiquement)

def get_account_balance(asset: str = 'USDT') -> Optional[float]:
    """
    Récupère le solde disponible ('free') pour un actif spécifique.

    Returns:
        Solde en float, 0.0 si l'asset n'est pas trouvé, None si erreur API/autre.
    """
    client = get_client()
    if not client:
        logger.error("Client Binance non initialisé pour get_account_balance.")
        return None

    try:
        account_info = client.get_account()
        balances = account_info.get('balances', [])
        balance_info = next((item for item in balances if item.get("asset") == asset), None)

        if balance_info and 'free' in balance_info:
            try:
                available_balance = float(balance_info['free'])
                logger.info(f"Solde {asset} disponible récupéré : {available_balance}")
                return available_balance
            except (ValueError, TypeError):
                 logger.error(f"Impossible de convertir le solde 'free' ({balance_info['free']}) en float pour {asset}.")
                 return None # Erreur de conversion
        else:
            logger.warning(f"Aucune information de solde trouvée pour l'asset {asset} dans le compte.")
            return 0.0 # Considérer 0 si l'asset n'est pas dans le compte

    except (BinanceAPIException, BinanceRequestException) as e:
        logger.error(f"Erreur API Binance lors de la récupération du solde {asset} : {e}")
        return None
    except Exception as e:
        logger.exception(f"Erreur inattendue lors de la récupération du solde {asset}.")
        return None

def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Récupère les informations et règles de trading pour un symbole.

    Returns:
        Dictionnaire d'informations ou None si non trouvé ou erreur.
    """
    client = get_client()
    if not client:
        logger.error("Client Binance non initialisé pour get_symbol_info.")
        return None
    try:
        info = client.get_symbol_info(symbol)
        if info:
            logger.debug(f"Informations récupérées pour le symbole {symbol}.")
            return info
        else:
            logger.warning(f"Aucune information trouvée pour le symbole {symbol} (symbole inexistant?).")
            return None
    except (BinanceAPIException, BinanceRequestException) as e:
        logger.error(f"Erreur API Binance lors de la récupération des infos pour {symbol} : {e}")
        return None
    except Exception as e:
        logger.exception(f"Erreur inattendue lors de la récupération des infos pour {symbol}.")
        return None

def get_symbol_ticker(symbol: str) -> Optional[Dict[str, str]]:
    """
    Récupère les informations du ticker (prix actuel) pour un symbole spécifique.

    Returns:
        Dictionnaire {'symbol': '...', 'price': '...'} ou None si erreur.
    """
    client = get_client()
    if not client:
        logger.error("Client Binance non initialisé pour get_symbol_ticker.")
        return None

    try:
        logger.debug(f"Récupération du ticker pour {symbol}...")
        ticker = client.get_symbol_ticker(symbol=symbol)
        logger.debug(f"Ticker pour {symbol} reçu: {ticker}")
        return ticker
    except (BinanceAPIException, BinanceRequestException) as e:
        logger.error(f"Erreur API/Request Binance lors de la récupération du ticker pour {symbol}: {e}")
        return None
    except Exception as e:
        logger.exception(f"Erreur inattendue lors de la récupération du ticker pour {symbol}")
        return None

def place_order(
    symbol: str,
    side: str,
    quantity: float,
    order_type: str = 'MARKET',
    price: Optional[str] = None,
    time_in_force: str = 'GTC'
) -> Optional[Dict[str, Any]]:
    """
    Place un ordre sur Binance avec gestion d'erreur.
    Simplifié pour MARKET et LIMIT GTC.

    Args:
        symbol: Le symbole (ex: 'BTCUSDT').
        side: 'BUY' ou 'SELL'.
        quantity: La quantité à acheter/vendre (doit être formatée correctement avant l'appel).
        order_type: 'MARKET' ou 'LIMIT'.
        price: Le prix formaté en string pour les ordres LIMIT.
        time_in_force: Time in force pour LIMIT (par défaut 'GTC').

    Returns:
        Les informations de l'ordre si succès, None sinon.
    """
    client = get_client()
    if not client:
        logger.error("Client Binance non initialisé pour place_order.")
        return None

    try:
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': quantity, # La quantité doit être un float ou Decimal formaté en string si nécessaire par l'API
        }

        if order_type == 'LIMIT':
            if price is None:
                logger.error("Le prix est requis pour un ordre LIMIT.")
                return None
            params['price'] = price
            params['timeInForce'] = time_in_force
        elif order_type != 'MARKET':
            logger.error(f"Type d'ordre '{order_type}' non supporté par cette fonction simplifiée.")
            return None

        # Log avant de placer l'ordre
        log_price_info = f"au prix {price}" if order_type == 'LIMIT' else "au marché"
        logger.info(f"Tentative de placement d'un ordre {order_type} {side} de {quantity} {symbol} {log_price_info}...")

        # Placer l'ordre
        order = client.create_order(**params)

        # Log après succès
        order_id = order.get('orderId', 'N/A')
        status = order.get('status', 'N/A')
        logger.info(
            f"Ordre {order_type} {side} placé avec succès pour {quantity} {symbol}. "
            f"OrderId: {order_id}, Statut: {status}"
        )
        return order

    except (BinanceAPIException, BinanceRequestException) as e:
        logger.error(
            f"Erreur API Binance lors du placement de l'ordre {order_type} {side} pour {symbol}: "
            f"Code={getattr(e, 'code', 'N/A')}, Message={e}"
        )
        return None
    except Exception as e:
        logger.exception(f"Erreur inattendue lors du placement de l'ordre {order_type} {side} pour {symbol}.")
        return None

# --- Bloc d'Exemple/Test ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    logger.info("Exécution du bloc de test de binance_client_wrapper.py")

    client_instance = get_client()
    if client_instance:
        print("\n--- Test get_klines ---")
        klines = get_klines('BTCUSDT', Client.KLINE_INTERVAL_1MINUTE, limit=5)
        if klines: print(f"Récupéré {len(klines)} klines pour BTCUSDT 1m.")
        else: print("Échec de la récupération des klines.")

        print("\n--- Test get_account_balance (USDT) ---")
        balance_usdt = get_account_balance('USDT')
        if balance_usdt is not None: print(f"Solde USDT disponible : {balance_usdt}")
        else: print("Échec de la récupération du solde USDT.")

        print("\n--- Test get_symbol_info ---")
        info = get_symbol_info('BTCUSDT')
        if info:
            print(f"Filtres pour BTCUSDT récupérés (exemple: LOT_SIZE):")
            lot_size = next((f for f in info.get('filters', []) if f.get('filterType') == 'LOT_SIZE'), None)
            notional = next((f for f in info.get('filters', []) if f.get('filterType') in ['MIN_NOTIONAL', 'NOTIONAL']), None)
            if lot_size: print(f"  LOT_SIZE: minQty={lot_size.get('minQty')}, stepSize={lot_size.get('stepSize')}")
            if notional: print(f"  {notional.get('filterType', 'NOTIONAL')}: minNotional={notional.get('minNotional')}")
        else: print("Échec de la récupération des infos symbole.")

        print("\n--- Test get_symbol_ticker ---")
        ticker = get_symbol_ticker('BTCUSDT')
        if ticker: print(f"Ticker pour BTCUSDT: {ticker}")
        else: print("Échec de la récupération du ticker.")

        print("\n--- Test place_order (MARKET BUY - SIMULATION SEULEMENT) ---")
        # ATTENTION : NE PAS DÉCOMMENTER L'APPEL place_order SANS ÊTRE SÛR
        test_symbol = 'BTCUSDT'
        test_side = 'BUY'
        # Quantité minimale pour le testnet BTCUSDT (souvent autour de 0.0001 ou 0.00001)
        # Vérifier les filtres LOT_SIZE et NOTIONAL avant de décommenter
        test_quantity = 0.0001 # Exemple, à adapter !

        print(f"Simulation: Placer un ordre {test_side} de {test_quantity} {test_symbol}...")
        # Décommenter pour tester réellement (sur testnet de préférence !)
        # order_result = place_order(test_symbol, test_side, test_quantity, order_type='MARKET')
        # if order_result:
        #     print("Ordre de test MARKET BUY placé (réellement ou simulé) :", order_result)
        # else:
        #     print("Échec du placement de l'ordre de test MARKET BUY.")
        print("Placement d'ordre non exécuté dans cet exemple.")

    else:
        print("Impossible d'initialiser le client Binance.")

