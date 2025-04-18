# --- ATTENTION : Configuration des Clés API ---
# Ce fichier est destiné à contenir vos clés API Binance.
# NE COMMETTEZ JAMAIS CE FICHIER DANS UN REPOSITORY GIT PUBLIC OU PRIVÉ SI VOS VRAIES CLÉS SONT ICI.
# La méthode la plus sûre est d'utiliser des variables d'environnement.

import os
from dotenv import load_dotenv

# Charger les variables d'environnement depuis un fichier .env (s'il existe)
load_dotenv()

# Récupérer les clés API depuis les variables d'environnement
BINANCE_API_KEY = os.getenv('ENV_API_KEY', 'YOUR_API_KEY') # Fournir une valeur par défaut claire
BINANCE_API_SECRET = os.getenv('ENV_API_SECRET', 'YOUR_SECRET_KEY') # Fournir une valeur par défaut claire

# --- Paramètres Généraux (peuvent être surchargés par bot.py/UI) ---
SYMBOL = 'BTCUSDT'
TIMEFRAME = '5m' # ex: '1s', '1m', '5m', '15m', '1h', '4h'

# --- Utiliser le Testnet Binance (True/False) ---
# IMPORTANT: Mettre à True pour les tests ! Mettre à False pour l'API réelle.
USE_TESTNET = True

# --- Paramètres de Stratégie par Défaut (peuvent être surchargés par bot.py/UI) ---
# Ces valeurs sont utilisées si elles ne sont pas définies dans bot.py -> bot_config
RISK_PER_TRADE = 0.01  # Risque 1% du capital alloué par trade
CAPITAL_ALLOCATION = 1.0 # Utiliser 100% (1.0) du capital disponible pour calculer la taille
STOP_LOSS_PERCENTAGE = 0.02 # Exemple: 2% (Utilisé dans strategy.py)

# Périodes des indicateurs
EMA_SHORT_PERIOD = 9
EMA_LONG_PERIOD = 21
EMA_FILTER_PERIOD = 50
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75
RSI_OVERSOLD = 25
VOLUME_AVG_PERIOD = 20

# Flags pour activer/désactiver des parties de la stratégie
USE_EMA_FILTER = True
USE_VOLUME_CONFIRMATION = False

# Note: Les valeurs ci-dessus sont des *défauts*. Le bot utilisera principalement
# les valeurs dans bot_config (qui sont initialisées depuis ici mais modifiables via l'UI).
