# --- ATTENTION : Configuration des Clés API ---
# Ce fichier est destiné à contenir vos clés API Binance.
# NE COMMETTEZ JAMAIS CE FICHIER DANS UN REPOSITORY GIT PUBLIC OU PRIVÉ SI VOS VRAIES CLÉS SONT ICI.
# La méthode la plus sûre est d'utiliser des variables d'environnement.

import os
from dotenv import load_dotenv

# Charger les variables d'environnement depuis un fichier .env (s'il existe)
# Créez un fichier .env à la racine avec :
# ENV_API_KEY=VOTRE_CLE_API
# ENV_API_SECRET=VOTRE_SECRET_API
load_dotenv()

# Récupérer les clés API depuis les variables d'environnement
BINANCE_API_KEY = os.getenv('ENV_API_KEY', 'YOUR_API_KEY_PLACEHOLDER') # Fournir une valeur par défaut claire
BINANCE_API_SECRET = os.getenv('ENV_API_SECRET', 'YOUR_SECRET_KEY_PLACEHOLDER') # Fournir une valeur par défaut claire

# --- Paramètres Généraux (peuvent être surchargés par bot.py/UI) ---
SYMBOL = 'BTCUSDT'
TIMEFRAME = '1m' # ex: '1s', '1m', '5m', '15m', '1h', '4h'

# --- Utiliser le Testnet Binance (True/False) ---
# IMPORTANT: Mettre à True pour les tests ! Mettre à False pour l'API réelle.
USE_TESTNET = True

# --- Paramètres de Stratégie par Défaut (peuvent être surchargés par bot.py/UI) ---
RISK_PER_TRADE = 0.01  # Risque 1% du capital alloué par trade
CAPITAL_ALLOCATION = 0.05 # Utiliser 100% (1.0) du capital disponible pour calculer la taille

# Niveaux Stop-Loss et Take-Profit (en pourcentage)
STOP_LOSS_PERCENTAGE = 0.02 # Exemple: 2%
TAKE_PROFIT_PERCENTAGE = 0.05 # Exemple: 5%

# Périodes des indicateurs
EMA_SHORT_PERIOD = 3
EMA_LONG_PERIOD = 5
EMA_FILTER_PERIOD = 50
RSI_PERIOD = 14
RSI_OVERBOUGHT = 95
RSI_OVERSOLD = 5
VOLUME_AVG_PERIOD = 20

# Flags pour activer/désactiver des parties de la stratégie
USE_EMA_FILTER = False
USE_VOLUME_CONFIRMATION = False

# Vérification rapide si les clés API semblent être des placeholders
if BINANCE_API_KEY == 'YOUR_API_KEY_PLACEHOLDER' or BINANCE_API_SECRET == 'YOUR_SECRET_KEY_PLACEHOLDER':
    print("ATTENTION : Les clés API Binance ne semblent pas configurées dans config.py ou via le fichier .env.")
    print("Veuillez les configurer avant de lancer le bot.")
    # Optionnel: exit() ici si vous voulez forcer l'arrêt
