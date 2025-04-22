# /Users/davidmichels/Desktop/trading-bot/backend/binance_client_wrapper.py

import logging
import threading
import time
import os
import dotenv

# Ensure List, Dict, Any, Optional, Union are imported from typing
from typing import Optional, List, Dict, Union, Any

from binance.spot import Spot as SpotClient
from binance.error import ClientError, ServerError
from decimal import Decimal, InvalidOperation # Import Decimal

# Import config manager to get settings like USE_TESTNET
from config_manager import config_manager
# Import order utils pour formater/valider si nécessaire (mais idéalement fait avant)
from utils.order_utils import format_quantity, format_price, get_symbol_filter # Importer les fonctions nécessaires

dotenv.load_dotenv()
logger = logging.getLogger(__name__)

# --- Module Globals ---
_client: Optional[SpotClient] = None
_client_lock = threading.Lock()  # Lock for thread-safe client initialization

# --- Client Initialization ---

def get_client() -> Optional[SpotClient]:
    """
    Initializes and returns the Binance Spot client (singleton pattern).
    Uses configuration from ConfigManager (API keys from .env, testnet from config).
    Returns None if initialization fails.
    """
    global _client
    if _client is not None: return _client # Fast check

    with _client_lock:
        if _client is None: # Double check inside lock
            try:
                api_key = os.getenv("ENV_API_KEY")
                api_secret = os.getenv("ENV_API_SECRET")
                use_testnet = config_manager.get_value("USE_TESTNET", True)

                if not api_key or not api_secret or api_key == "YOUR_API_KEY_PLACEHOLDER" or api_secret == "YOUR_SECRET_KEY_PLACEHOLDER":
                    logger.critical("Binance API keys not configured or are placeholders in .env file.")
                    return None

                base_url = "https://testnet.binance.vision" if use_testnet else "https://api.binance.com"
                logger.info(f"Initializing Binance Spot client (Base URL: {base_url})...")

                client_instance = SpotClient(api_key=api_key, api_secret=api_secret, base_url=base_url)
                client_instance.ping()
                logger.info("Connection to Binance Spot API successful (ping OK).")
                _client = client_instance

            except ClientError as e:
                logger.critical(f"Binance Client Error during initialization: Status={e.status_code}, Code={e.error_code}, Msg={e.error_message}")
                _client = None
            except ServerError as e:
                logger.critical(f"Binance Server Error during initialization: Status={e.status_code}, Msg={str(e)}")
                _client = None
            except Exception as e:
                logger.critical(f"Unexpected error during Binance Spot client initialization: {e}", exc_info=True)
                _client = None
        return _client


# --- API Call Wrappers ---

# get_klines, get_account_balance, get_symbol_info, get_symbol_ticker restent inchangés...
# (Le code précédent pour ces fonctions semblait correct)

def get_klines(
    symbol: str,
    interval: str,
    limit: int = 100,
    retries: int = 3,
    delay: int = 5,
) -> Optional[List[List[Any]]]:
    """ Retrieves kline/candlestick data. Handles API errors and retries. """
    client = get_client()
    if not client: return None
    logger.debug(f"Attempting to retrieve {limit} klines for {symbol} ({interval})...")
    for attempt in range(retries):
        try:
            klines = client.klines(symbol=symbol.upper(), interval=interval, limit=limit)
            if isinstance(klines, list):
                if not klines and attempt < retries - 1:
                    logger.warning(f"get_klines({symbol}, {interval}): Received empty list (Attempt {attempt + 1}/{retries}). Retrying...")
                    time.sleep(delay)
                    continue
                if all(isinstance(item, list) for item in klines):
                    logger.info(f"get_klines({symbol}, {interval}): Successfully retrieved {len(klines)} klines.")
                    return klines
                else:
                    logger.error(f"get_klines({symbol}, {interval}): Unexpected format in response list items.")
                    return None
            else:
                logger.error(f"get_klines({symbol}, {interval}): Unexpected response type: {type(klines)}.")
                return None
        except (ClientError, ServerError) as e:
            logger.error(f"get_klines({symbol}, {interval}): API Error (Attempt {attempt + 1}/{retries}). {e}")
            if attempt < retries - 1: time.sleep(delay)
            else: return None
        except Exception as e:
            logger.exception(f"get_klines({symbol}, {interval}): Unexpected error (Attempt {attempt + 1}/{retries}).")
            if attempt < retries - 1: time.sleep(delay)
            else: return None
    return None

def get_account_balance(asset: str) -> Optional[Decimal]:
    """ Retrieves the available ('free') balance for a specific asset as Decimal. """
    client = get_client()
    if not client: return None
    try:
        logger.debug(f"Retrieving balance for {asset}...")
        account_info = client.account(recvWindow=10000)
        balances = account_info.get("balances", [])
        balance_info = next((item for item in balances if item.get("asset") == asset.upper()), None)
        if balance_info and "free" in balance_info:
            try:
                available_balance = Decimal(balance_info["free"])
                logger.info(f"Available {asset} balance: {available_balance}")
                return available_balance
            except (InvalidOperation, TypeError):
                logger.error(f"get_account_balance({asset}): Could not convert balance '{balance_info['free']}' to Decimal.")
                return None
        else:
            logger.warning(f"get_account_balance({asset}): Asset not found. Returning Decimal('0').")
            return Decimal("0")
    except (ClientError, ServerError) as e:
        logger.error(f"get_account_balance({asset}): API Error. {e}")
        return None
    except Exception as e:
        logger.exception(f"get_account_balance({asset}): Unexpected error.")
        return None

def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    """ Retrieves exchange information (filters, precision) for a specific symbol. """
    client = get_client()
    if not client: return None
    try:
        logger.debug(f"Retrieving exchange info for {symbol}...")
        all_info = client.exchange_info(symbol=symbol.upper())
        if all_info and "symbols" in all_info and len(all_info["symbols"]) == 1:
            info = all_info["symbols"][0]
            logger.debug(f"Exchange info for {symbol} retrieved successfully.")
            return info
        else:
            logger.error(f"get_symbol_info({symbol}): Symbol info not found or invalid format: {all_info}")
            return None
    except (ClientError, ServerError) as e:
        logger.error(f"get_symbol_info({symbol}): API Error. {e}")
        return None
    except Exception as e:
        logger.exception(f"get_symbol_info({symbol}): Unexpected error.")
        return None

def get_symbol_ticker(symbol: str) -> Optional[Dict[str, str]]:
    """ Retrieves the latest price ticker for a specific symbol. """
    client = get_client()
    if not client: return None
    try:
        logger.debug(f"Retrieving ticker for {symbol}...")
        ticker = client.ticker_price(symbol=symbol.upper())
        if ticker and "price" in ticker:
            logger.debug(f"Ticker for {symbol}: Price={ticker['price']}")
            return ticker
        else:
            logger.error(f"get_symbol_ticker({symbol}): Invalid response format: {ticker}")
            return None
    except (ClientError, ServerError) as e:
        logger.error(f"get_symbol_ticker({symbol}): API Error. {e}")
        return None
    except Exception as e:
        logger.exception(f"get_symbol_ticker({symbol}): Unexpected error.")
        return None


def place_order(
    symbol: str,
    side: str,
    order_type: str,
    quantity: Optional[Union[float, Decimal, str]] = None,
    quoteOrderQty: Optional[Union[float, Decimal, str]] = None,
    price: Optional[Union[float, Decimal, str]] = None,
    time_in_force: Optional[str] = None,
    newClientOrderId: Optional[str] = None, # Permet d'ajouter un ID client
    recvWindow: int = 5000 # Fenêtre de réception par défaut
) -> Optional[Dict[str, Any]]:
    """
    Places an order on Binance. Uses provided parameters directly.
    The calling function is responsible for ensuring parameters meet exchange requirements
    (e.g., formatting quantity/price, checking minNotional).
    Returns the order details dict from Binance API, or None on failure.
    """
    client = get_client()
    if not client:
        return None

    try:
        # Prepare base parameters, converting Decimals to strings
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": order_type.upper(),
            "recvWindow": recvWindow
        }
        log_details = ""

        # Add parameters based on order type, ensuring they are strings
        if params["type"] == "MARKET":
            if params["side"] == "BUY" and quoteOrderQty is not None:
                params["quoteOrderQty"] = str(quoteOrderQty)
                log_details += f" QuoteQty={params['quoteOrderQty']}"
            elif quantity is not None: # For MARKET SELL or MARKET BUY by base quantity
                params["quantity"] = str(quantity)
                log_details += f" Qty={params['quantity']}"
            else:
                 raise ValueError("MARKET order requires 'quantity' (for SELL) or 'quoteOrderQty'/'quantity' (for BUY).")
            log_details += " @ market"

        elif params["type"] == "LIMIT":
            if quantity is None or price is None:
                raise ValueError("LIMIT order requires 'quantity' and 'price'.")
            params["quantity"] = str(quantity)
            params["price"] = str(price)
            params["timeInForce"] = (time_in_force or "GTC").upper()
            log_details += f" Qty={params['quantity']} @ {params['price']} ({params['timeInForce']})"

        # Add other order types (STOP_LOSS_LIMIT etc.) here if needed
        # Example:
        # elif params["type"] == "STOP_LOSS_LIMIT":
        #     if quantity is None or price is None or stopPrice is None:
        #         raise ValueError("STOP_LOSS_LIMIT requires quantity, price, and stopPrice.")
        #     params["quantity"] = str(quantity)
        #     params["price"] = str(price)
        #     params["stopPrice"] = str(stopPrice)
        #     params["timeInForce"] = (time_in_force or "GTC").upper()
        #     log_details += f" Qty={params['quantity']} @ {params['price']} (Stop: {params['stopPrice']}, TIF: {params['timeInForce']})"

        else:
            raise ValueError(f"Unsupported order_type for place_order wrapper: {order_type}")

        # Add optional client order ID
        if newClientOrderId:
            params["newClientOrderId"] = str(newClientOrderId)
            log_details += f" ClientID={params['newClientOrderId']}"

        # Log the attempt
        logger.info(f"Placing Order: {params['side']} {params['type']} {symbol}{log_details}...")

        # Make the API call
        order_response = client.new_order(**params)

        # Log the result
        order_id = order_response.get("orderId", "N/A")
        status = order_response.get("status", "N/A")
        log_level = logging.INFO
        if status in ["REJECTED", "EXPIRED", "CANCELED"]: log_level = logging.WARNING
        elif status not in ["NEW", "FILLED", "PARTIALLY_FILLED"]: log_level = logging.ERROR

        logger.log(
            log_level,
            f"Order Placement Result ID {order_id}: Status={status}, Type={order_response.get('type')}, Side={order_response.get('side')}, "
            f"OrigQty={order_response.get('origQty')}, ExecQty={order_response.get('executedQty', 'N/A')}, "
            f"CummQuoteQty={order_response.get('cummulativeQuoteQty', 'N/A')}, Price={order_response.get('price')}"
        )

        return order_response

    except (ClientError, ValueError) as e:
        error_code = getattr(e, "error_code", None) if isinstance(e, ClientError) else None
        error_msg = getattr(e, "error_message", str(e)) if isinstance(e, ClientError) else str(e)
        logger.error(
            f"place_order({symbol}, {side}, {order_type}): Client/Validation Error. Status={getattr(e, 'status_code', 'N/A')}, Code={error_code}, Msg={error_msg}"
        )
        if error_code == -1013: logger.error(" -> Hint: Check order filters (minNotional, lotSize, priceFilter) or quantity/price precision.")
        if error_code == -2010: logger.error(" -> Hint: Insufficient balance.")
        if error_code == -1111: logger.error(" -> Hint: Precision issue with quantity or price.")
        return None
    except ServerError as e:
        logger.error(f"place_order({symbol}, {side}, {order_type}): Server Error. Status={e.status_code}, Msg={str(e)}")
        return None
    except Exception as e:
        logger.exception(f"place_order({symbol}, {side}, {order_type}): Unexpected error.")
        return None


# cancel_order, get_all_orders, create_listen_key, renew_listen_key, close_listen_key restent inchangés...
# (Le code précédent pour ces fonctions semblait correct)

def cancel_order(symbol: str, orderId: int) -> Optional[Dict[str, Any]]:
    """ Cancels an open order. """
    client = get_client()
    if not client: return None
    try:
        logger.info(f"Attempting to cancel order {orderId} for {symbol}...")
        result = client.cancel_order(symbol=symbol.upper(), orderId=orderId)
        status = result.get("status")
        logger.info(f"Cancel Order Result {orderId}: Status={status}")
        return result
    except ClientError as e:
        if e.error_code == -2011:
            logger.warning(f"cancel_order({symbol}, {orderId}): Failed (Code: {e.error_code}). Order unknown or already filled/cancelled.")
            return {"symbol": symbol, "orderId": orderId, "status": "UNKNOWN_OR_ALREADY_COMPLETED"}
        else:
            logger.error(f"cancel_order({symbol}, {orderId}): Client Error. {e}")
            return None
    except ServerError as e:
        logger.error(f"cancel_order({symbol}, {orderId}): Server Error. {e}")
        return None
    except Exception as e:
        logger.exception(f"cancel_order({symbol}, {orderId}): Unexpected error.")
        return None

def get_all_orders(
    symbol: str, limit: int = 50, retries: int = 3, delay: int = 2
) -> Optional[List[Dict[str, Any]]]:
    """ Retrieves recent order history for a symbol via REST API. """
    client = get_client()
    if not client: return None
    logger.debug(f"Attempting to retrieve last {limit} orders for {symbol} via REST...")
    params = {"symbol": symbol.upper(), "limit": limit}
    for attempt in range(retries):
        try:
            orders = client.get_orders(**params) # Utilise get_orders (ou all_orders selon la version de la lib)
            if isinstance(orders, list):
                logger.info(f"get_all_orders({symbol}): Successfully retrieved {len(orders)} orders via REST.")
                return orders
            else:
                logger.error(f"get_all_orders({symbol}): Unexpected response type: {type(orders)}.")
                return None
        except (ClientError, ServerError) as e:
            logger.error(f"get_all_orders({symbol}): API Error (Attempt {attempt + 1}/{retries}). {e}")
            if attempt < retries - 1: time.sleep(delay)
            else: return None
        except Exception as e:
            logger.exception(f"get_all_orders({symbol}): Unexpected error (Attempt {attempt + 1}/{retries}).")
            if attempt < retries - 1: time.sleep(delay)
            else: return None
    return None

def create_listen_key() -> Optional[str]:
    """ Creates a new listenKey for the User Data Stream via REST API. """
    client = get_client()
    if not client: return None
    try:
        logger.info("Creating new ListenKey via REST API...")
        response = client.new_listen_key()
        key = response.get("listenKey")
        if key:
            logger.info(f"New ListenKey created successfully: {key[:5]}...")
            return key
        else:
            logger.error(f"Failed to create ListenKey, invalid API response: {response}")
            return None
    except (ClientError, ServerError) as e:
        logger.error(f"API error creating ListenKey: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.exception("Unexpected error creating ListenKey.")
        return None

def renew_listen_key(listen_key: str) -> bool:
    """ Renews (keepalive) an existing ListenKey via REST API. """
    client = get_client()
    if not client or not listen_key:
        logger.error("Cannot renew listen key: client not available or key missing.")
        return False
    try:
        logger.debug(f"Renewing ListenKey {listen_key[:5]}... via REST API...")
        client.renew_listen_key(listenKey=listen_key)
        logger.info(f"ListenKey {listen_key[:5]}... renewed successfully.")
        return True
    except ClientError as e:
        if e.error_code == -1125: # Invalid listen key
            logger.warning(f"Failed to renew ListenKey {listen_key[:5]} (Code {e.error_code}): Key likely expired or invalid.")
            return False
        else:
            logger.error(f"API Client Error renewing ListenKey {listen_key[:5]}: {e}")
            return False
    except ServerError as e:
        logger.error(f"API Server Error renewing ListenKey {listen_key[:5]}: {str(e)}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error renewing ListenKey {listen_key[:5]}.")
        return False

def close_listen_key(listen_key: str) -> bool:
    """ Closes an existing ListenKey via REST API. """
    client = get_client()
    if not client or not listen_key:
        logger.debug("No client or listen key provided for closing.")
        return True
    try:
        logger.info(f"Closing ListenKey {listen_key[:5]}... via REST API...")
        client.close_listen_key(listenKey=listen_key)
        logger.info(f"ListenKey {listen_key[:5]}... closed successfully.")
        return True
    except ClientError as e:
        if e.error_code == -1125: # Invalid listen key
            logger.warning(f"Attempted to close ListenKey {listen_key[:5]} but it was already invalid/expired (Code {e.error_code}).")
            return True
        else:
            logger.error(f"API Client Error closing ListenKey {listen_key[:5]}: {e}")
            return False
    except ServerError as e:
        logger.error(f"API Server Error closing ListenKey {listen_key[:5]}: {str(e)}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error closing ListenKey {listen_key[:5]}.")
        return False


# --- Example Usage / Test Block ---
if __name__ == "__main__":
    # (Le bloc de test reste inchangé, il est utile pour vérifier le wrapper)
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - [%(name)s] - %(message)s")
    logger.info("--- Testing Binance Client Wrapper ---")
    # ... (reste du code de test) ...
    logger.info("\n--- Wrapper Tests Finished ---")
