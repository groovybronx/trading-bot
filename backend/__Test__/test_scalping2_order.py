# test_scalping2_order.py
import requests
import json
import logging
import os
from dotenv import load_dotenv
from decimal import Decimal, InvalidOperation

load_dotenv()

BASE_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:5000")
PARAMS_URL = f"{BASE_URL}/api/parameters"
PLACE_ORDER_URL = f"{BASE_URL}/api/place_order"
STATUS_URL = f"{BASE_URL}/api/status" # Ajouté pour récupérer le solde
REQUEST_TIMEOUT = 20

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# 1. Définir les paramètres SCALPING2 (ajuster si nécessaire)
params = {
    "STRATEGY_TYPE": "SCALPING2",
    "SYMBOL": "BTCUSDT",
    "TIMEFRAME": "1m",
    "CAPITAL_ALLOCATION": 10.0, # 50% du capital total
    "RISK_PER_TRADE": 1.0, # 1% du capital alloué
    "STOP_LOSS_PERCENTAGE": 0.5,  # 0.5%
    "TAKE_PROFIT_1_PERCENTAGE": 1.0,  # 1%
    "TAKE_PROFIT_2_PERCENTAGE": 1.5,  # 1.5%
    "TRAILING_STOP_PERCENTAGE": 0.3,  # 0.3%
    "TIME_STOP_MINUTES": 15,
    # Indicateurs SCALPING2 (valeurs par défaut de config.py)
    "SUPERTREND_ATR_PERIOD": 3,
    "SUPERTREND_ATR_MULTIPLIER": 1.5,
    "SCALPING_RSI_PERIOD": 7,
    "STOCH_K_PERIOD": 14,
    "STOCH_D_PERIOD": 3,
    "STOCH_SMOOTH": 3,
    "BB_PERIOD": 20,
    "BB_STD": 2.0,
    "VOLUME_MA_PERIOD": 20,
}
logging.info("Activation de la stratégie SCALPING2 et définition des paramètres...")
resp = requests.post(PARAMS_URL, json=params, timeout=REQUEST_TIMEOUT)
logging.info(f"Réponse paramètres: {resp.status_code} {resp.text}")
if resp.status_code >= 400:
     logging.error("Échec de la définition des paramètres. Arrêt du test.")
     exit()

# 2. Récupère le solde disponible (quote asset)
try:
    logging.info("Récupération de l'état actuel (solde)...")
    status_resp = requests.get(STATUS_URL, timeout=REQUEST_TIMEOUT)
    status_resp.raise_for_status()
    status_data = status_resp.json()
    # Utiliser Decimal pour le solde
    available_balance = Decimal(str(status_data.get("available_balance", "0")))
    quote_asset = status_data.get("quote_asset", "USDT")
    logging.info(f"Solde disponible: {available_balance:.4f} {quote_asset}")
except Exception as e:
    logging.error(f"Impossible de récupérer le solde disponible: {e}")
    available_balance = Decimal("0")
    quote_asset = "USDT"

# 3. Calcule le montant à investir selon CAPITAL_ALLOCATION (en utilisant Decimal)
try:
    capital_allocation_pct = Decimal(str(params["CAPITAL_ALLOCATION"])) / Decimal(100)
    capital_to_use = available_balance * capital_allocation_pct
    logging.info(
        f"Montant à investir (CAPITAL_ALLOCATION): {capital_to_use:.4f} {quote_asset}"
    )
except (KeyError, InvalidOperation, TypeError) as e:
     logging.error(f"Erreur calcul capital à utiliser: {e}")
     capital_to_use = Decimal("0")

# 4. Envoie un ordre MARKET BUY avec le montant calculé (quoteOrderQty)
if capital_to_use > 0:
    # S'assurer que le montant n'est pas trop petit (ex: > 1 USDT pour être sûr)
    # Une vérification MIN_NOTIONAL plus précise serait mieux mais nécessite le prix actuel
    if capital_to_use < Decimal("1.0"):
         logging.warning(f"Capital à utiliser ({capital_to_use:.4f}) est très faible. L'ordre pourrait échouer.")

    order_data = {
        "symbol": params["SYMBOL"],
        "side": "BUY",
        "order_type": "MARKET",
        "quoteOrderQty": str(capital_to_use.quantize(Decimal("0.0001"))), # CORRECT: Utiliser quoteOrderQty, convertir Decimal en str
    }
    logging.info(f"Envoi d'un ordre MARKET BUY SCALPING2: {json.dumps(order_data)}")
    try:
        resp = requests.post(PLACE_ORDER_URL, json=order_data, timeout=REQUEST_TIMEOUT)
        logging.info(f"Réponse ordre: {resp.status_code}")
        try:
            print(json.dumps(resp.json(), indent=2))
        except json.JSONDecodeError:
            print(resp.text)
    except Exception as e:
        logging.error(f"Erreur lors de l'envoi de l'ordre: {e}")
else:
    logging.warning("Capital à utiliser est nul ou négatif. Aucun ordre envoyé.")

logging.info("--- Test SCALPING2 terminé ---")

