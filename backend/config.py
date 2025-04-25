# /Users/davidmichels/Desktop/trading-bot/backend/config.py

import os
from dotenv import load_dotenv
import logging

from regex import F

# Charger les variables d'environnement au début
load_dotenv()
# Remplacer les prints par des logs pour une meilleure gestion en production
logger = logging.getLogger(__name__)
logger.debug("Variables d'environnement chargées via dotenv.")

# --- ATTENTION : Configuration des Clés API ---
# Utilisation de os.getenv pour lire les clés depuis .env ou variables système
BINANCE_API_KEY = os.getenv("ENV_API_KEY", "YOUR_API_KEY_PLACEHOLDER")
BINANCE_API_SECRET = os.getenv("ENV_API_SECRET", "YOUR_SECRET_KEY_PLACEHOLDER")

# Log de débogage (optionnel, plus propre que print)
# logger.debug(f"Clé API chargée (début): '{BINANCE_API_KEY[:5]}...'")
# logger.debug(f"Secret API chargé (début): '{BINANCE_API_SECRET[:5]}...'")

# --- Paramètres Généraux ---
SYMBOL = "BTCUSDT"
TIMEFRAME = "1m"  # Pertinent pour stratégies basées sur klines (SWING, SCALPING2)

# --- Utiliser le Testnet Binance ---
# Lire USE_TESTNET depuis les variables d'environnement si possible
USE_TESTNET_STR = os.getenv("ENV_USE_TESTNET", "True")
USE_TESTNET = USE_TESTNET_STR.lower() in ("true", "1", "t", "yes", "y")
logger.debug(
    f"USE_TESTNET configuré à: {USE_TESTNET} (valeur lue: '{USE_TESTNET_STR}')"
)

# --- Type de Stratégie ---
# Choisir 'SCALPING', 'SCALPING2' ou 'SWING'
STRATEGY_TYPE = "SCALPING"  # Valeur par défaut, sera gérée par ConfigManager

# --- Paramètres Communs (Gestion du Risque/Capital) ---
# Ces valeurs sont souvent fournies en % par l'utilisateur via l'UI
# ConfigManager les convertira en fractions décimales pour l'usage interne
RISK_PER_TRADE = (
    1.0  # Risque par trade en POURCENTAGE du capital alloué (ex: 1.0 pour 1%)
)
CAPITAL_ALLOCATION = 20.0  # POURCENTAGE du capital total à allouer (ex: 50.0 pour 50%)
STOP_LOSS_PERCENTAGE = 0.5  # POURCENTAGE de perte max par trade (ex: 0.5 pour 0.5%)
TAKE_PROFIT_1_PERCENTAGE = 1.0  # POURCENTAGE de gain pour TP1 (ex: 1.0 pour 1%)
TAKE_PROFIT_2_PERCENTAGE = 1.5  # POURCENTAGE de gain pour TP2 (ex: 1.5 pour 1.5%)
TRAILING_STOP_PERCENTAGE = 0.3  # POURCENTAGE pour le trailing stop (ex: 0.3 pour 0.3%)
TIME_STOP_MINUTES = 15  # Durée maximale (minutes) d'une position avant sortie forcée
ORDER_COOLDOWN_MS = 2000  # Délai minimal (ms) entre deux ordres (anti-spam/scalping)

# --- Paramètres Scalping (Stratégie 1: Basée sur Order Book) ---
SCALPING_ORDER_TYPE = "LIMIT"  # 'MARKET' ou 'LIMIT'
SCALPING_LIMIT_TIF = "GTC"  # Time in Force pour ordres LIMIT ('GTC', 'IOC', 'FOK')
SCALPING_LIMIT_ORDER_TIMEOUT_MS = (
    5000  # Temps (ms) avant d'annuler un ordre LIMIT non rempli
)
SCALPING_DEPTH_LEVELS = 5  # Nombre de niveaux du carnet (5, 10, 20)
SCALPING_DEPTH_SPEED = "1000ms"  # Vitesse MàJ carnet ('100ms' ou '1000ms')
SCALPING_SPREAD_THRESHOLD = (
    0.0001  # Écart relatif max pour entrer (fraction, ex: 0.0001 = 0.01%)
)
SCALPING_IMBALANCE_THRESHOLD = 1.5  # Ratio Bid/Ask minimum pour entrer

# --- Paramètres Scalping 2 (Stratégie 2: Basée sur Indicateurs Techniques) ---
# Périodes indicateurs
SUPERTREND_ATR_PERIOD = 3
SUPERTREND_ATR_MULTIPLIER = 1.5
SCALPING_RSI_PERIOD = 7
STOCH_K_PERIOD = 14
STOCH_D_PERIOD = 3
STOCH_SMOOTH = 3
BB_PERIOD = 20
BB_STD = 2.0
VOLUME_MA_PERIOD = 20
# Note: SL/TP/Trailing/TimeStop sont partagés via les paramètres communs

# --- Paramètres SWING (Stratégie 3: EMA/RSI/Volume) ---
EMA_SHORT_PERIOD = 9
EMA_LONG_PERIOD = 21
EMA_FILTER_PERIOD = 50
RSI_PERIOD = 14
RSI_OVERBOUGHT = 95
RSI_OVERSOLD = 5
VOLUME_AVG_PERIOD = 20
USE_EMA_FILTER = False  # Utiliser EMA comme filtre (True/False)
USE_VOLUME_CONFIRMATION = False
# Note: SL/TP/Trailing/TimeStop sont partagés via les paramètres communs

# --- Vérification Clés API ---
# Message de log plus clair
if (
    BINANCE_API_KEY == "YOUR_API_KEY_PLACEHOLDER"
    or BINANCE_API_SECRET == "YOUR_SECRET_KEY_PLACEHOLDER"
):
    logger.critical("\n" + "=" * 60)
    logger.critical("ATTENTION : Les clés API Binance ne semblent pas configurées !")
    logger.critical(
        "Veuillez les définir dans votre fichier .env (ENV_API_KEY, ENV_API_SECRET)"
    )
    logger.critical("ou comme variables d'environnement système.")
    logger.critical("Le bot ne pourra pas fonctionner sans clés valides.")
    logger.critical("=" * 60 + "\n")
elif not BINANCE_API_KEY or not BINANCE_API_SECRET:
    logger.critical("\n" + "=" * 60)
    logger.critical("ATTENTION : Une ou les deux clés API Binance sont VIDES !")
    logger.critical(
        "Veuillez vérifier votre fichier .env ou vos variables d'environnement."
    )
    logger.critical("Le bot ne pourra pas fonctionner sans clés valides.")
    logger.critical("=" * 60 + "\n")
else:
    logger.info(
        "config.py: Clés API chargées depuis l'environnement (non-placeholder, non-vides)."
    )

# Log final pour confirmer les paramètres par défaut chargés (avant ConfigManager)
logger.debug(
    f"Config Defaults: SYMBOL={SYMBOL}, TIMEFRAME={TIMEFRAME}, STRATEGY={STRATEGY_TYPE}, TESTNET={USE_TESTNET}"
)
