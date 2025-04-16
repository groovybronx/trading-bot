# --- ATTENTION : Configuration des Clés API ---
# Ce fichier est destiné à contenir vos clés API Binance.
# NE COMMETTEZ JAMAIS CE FICHIER DANS UN REPOSITORY GIT PUBLIC OU PRIVÉ SI VOS VRAIES CLÉS SONT ICI.
# La méthode la plus sûre est d'utiliser des variables d'environnement.
# Exemple :
import os
BINANCE_API_KEY = os.getenv('API_KEY', '3Zumf1xFdfiHXKuUgLufCfO6VU77DSHEGkSFTJonid3F0WUTVLlfBF5NY6M9GUNQ')
BINANCE_API_SECRET = os.getenv('API_SECRET','zOTf6xuhYl0ZCSPXYoxydPAbpQCOLK8Cz6uWp4Os80E8Ilv5ryCtUj33NSFUXDkG')

# --- Remplacer par vos vraies clés UNIQUEMENT pour un usage local et sécurisé ---
# --- Ou mieux, commenter ces lignes et utiliser les variables d'environnement ---
#BINANCE_API_KEY = "3Zumf1xFdfiHXKuUgLufCfO6VU77DSHEGkSFTJonid3F0WUTVLlfBF5NY6M9GUNQ"  # REMPLACEZ CECI ou  utilisez les variables d'environnement
#BINANCE_API_SECRET = "zOTf6xuhYl0ZCSPXYoxydPAbpQCOLK8Cz6uWp4Os80E8Ilv5ryCtUj33NSFUXDkG" # REMPLACEZ CECI ou utilisez les variables d'environnement

# --- Autres paramètres de configuration (peuvent être déplacés ici depuis bot.py) ---
# SYMBOL = 'BTCUSDT'
# TIMEFRAME = '5m' # Utiliser la chaîne de caractères ici peut être plus simple pour certaines fonctions
# RISK_PER_TRADE = 0.01
# CAPITAL_ALLOCATION = 0.1
# EMA_SHORT_PERIOD = 9
# EMA_LONG_PERIOD = 21
# EMA_FILTER_PERIOD = 50
# RSI_PERIOD = 14
# RSI_OVERBOUGHT = 75
# RSI_OVERSOLD = 25
# TAKE_PROFIT_PERCENT = 0.005 # 0.5%
# STOP_LOSS_PERCENT = 0.003 # 0.3%

# --- Utiliser le Testnet Binance (True/False) ---
USE_TESTNET = True # Mettre à False pour utiliser l'API réelle
