# /Users/davidmichels/Desktop/trading-bot/backend/config.py

import os
from dotenv import load_dotenv
import logging

# MODIFIÉ: Charger les variables d'environnement au début
load_dotenv()
print("Variables d'environnement chargées.") # Debug print

# --- ATTENTION : Configuration des Clés API ---
# MODIFIÉ: Utilisation de os.getenv pour lire les clés depuis .env ou variables système
# Assurez-vous que votre fichier .env est dans le même répertoire ou un répertoire parent,
# ou que les variables d'environnement sont définies globalement.
BINANCE_API_KEY = os.getenv('ENV_API_KEY', 'YOUR_API_KEY_PLACEHOLDER')
BINANCE_API_SECRET = os.getenv('ENV_API_SECRET', 'YOUR_SECRET_KEY_PLACEHOLDER')

# --- AJOUT DEBUG ---
print(f"DEBUG: Clé lue par os.getenv: '{BINANCE_API_KEY[:5]}...'") # Affiche les 5 premiers caractères
print(f"DEBUG: Secret lu par os.getenv: '{BINANCE_API_SECRET[:5]}...'") # Affiche les 5 premiers caractères

# --- Paramètres Généraux ---
SYMBOL = 'BTCUSDT'
TIMEFRAME = '1m' # Moins pertinent pour le scalping pur, mais gardé pour contexte/UI

# --- Utiliser le Testnet Binance ---
# MODIFIÉ: Lire USE_TESTNET depuis les variables d'environnement si possible
# La valeur par défaut est True si non définie dans .env
USE_TESTNET_STR = os.getenv('ENV_USE_TESTNET', 'True')
USE_TESTNET = USE_TESTNET_STR.lower() in ('true', '1', 't', 'yes', 'y')

print(f"USE_TESTNET: {USE_TESTNET} (lu depuis .env: '{USE_TESTNET_STR}')") # Debug print

# --- Type de Stratégie ---
# Choisir 'SCALPING' ou 'SWING' (ou autre nom pour l'ancienne stratégie EMA/RSI)
STRATEGY_TYPE = 'SCALPING'

# --- Paramètres Scalping (Nouveaux) ---
# Note: Ces valeurs sont des exemples, à ajuster IMPÉRATIVEMENT
SCALPING_ORDER_TYPE = 'MARKET' # 'MARKET' ou 'LIMIT'
SCALPING_LIMIT_TIF = 'GTC'     # Time in Force pour ordres LIMIT ('GTC', 'IOC', 'FOK')
SCALPING_LIMIT_ORDER_TIMEOUT_MS = 5000 # Temps (ms) avant d'annuler un ordre LIMIT non rempli
SCALPING_DEPTH_LEVELS = 5      # Nombre de niveaux du carnet à écouter (ex: 5, 10, 20)
SCALPING_DEPTH_SPEED = '100ms' # Vitesse de MàJ du carnet ('100ms' ou '1000ms')
# --- Paramètres spécifiques à VOTRE stratégie scalping (Exemples) ---
SCALPING_SPREAD_THRESHOLD = 0.0001 # Ex: Seuil d'écart relatif pour entrer
SCALPING_IMBALANCE_THRESHOLD = 1.5 # Ex: Ratio Bid/Ask pour déséquilibre du carnet
SCALPING_MIN_TRADE_VOLUME = 0.1    # Ex: Volume minimum sur aggTrade pour confirmer momentum

# --- Paramètres de Risque (Communs) ---
RISK_PER_TRADE = 1 # Risque par trade (en pourcentage du capital total)
CAPITAL_ALLOCATION = 50 # Utiliser 5% du capital pour ce bot/stratégie

# Niveaux Stop-Loss et Take-Profit (en pourcentage - peuvent être ajustés par la stratégie scalping)
STOP_LOSS_PERCENTAGE = 0.5 # SL très serré pour scalping (0.5%)
TAKE_PROFIT_PERCENTAGE = 0.1 # TP serré pour scalping (1%)

# --- Paramètres Ancienne Stratégie (EMA/RSI - Non utilisés si STRATEGY_TYPE='SCALPING') ---
# NOTE: Gardés pour permettre le changement de stratégie via l'API, mais pourraient être supprimés si non nécessaire.
EMA_SHORT_PERIOD = 3
EMA_LONG_PERIOD = 5
EMA_FILTER_PERIOD = 50
RSI_PERIOD = 14
RSI_OVERBOUGHT = 95
RSI_OVERSOLD = 5
VOLUME_AVG_PERIOD = 20
USE_EMA_FILTER = False
USE_VOLUME_CONFIRMATION = False

# --- Vérification Clés API ---
# MODIFIÉ: Message de log plus clair
if BINANCE_API_KEY == 'YOUR_API_KEY_PLACEHOLDER' or BINANCE_API_SECRET == 'YOUR_SECRET_KEY_PLACEHOLDER':
    print("\n" + "="*60)
    print("ATTENTION : Les clés API Binance ne semblent pas configurées !")
    print("Veuillez les définir dans votre fichier .env (ENV_API_KEY, ENV_API_SECRET)")
    print("ou comme variables d'environnement système.")
    print("Le bot ne pourra pas fonctionner sans clés valides.")
    print("="*60 + "\n")
# NOUVEAU: Vérification supplémentaire si les clés sont vides
elif not BINANCE_API_KEY or not BINANCE_API_SECRET:
    print("\n" + "="*60)
    print("ATTENTION : Une ou les deux clés API Binance sont VIDES !")
    print("Veuillez vérifier votre fichier .env ou vos variables d'environnement.")
    print("Le bot ne pourra pas fonctionner sans clés valides.")
    print("="*60 + "\n")
else:
    # --- AJOUT CONFIRMATION ---
    print("INFO: config.py confirme que les clés API ont été chargées depuis l'environnement (non-placeholder, non-vides).")
    # --- FIN AJOUT CONFIRMATION ---

# NOUVEAU: Log final pour confirmer les paramètres chargés
print(f"Config chargée: SYMBOL={SYMBOL}, TIMEFRAME={TIMEFRAME}, STRATEGY={STRATEGY_TYPE}, TESTNET={USE_TESTNET}")

