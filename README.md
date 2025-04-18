# Binance Trading Bot Dashboard

Ce projet est un bot de trading simple pour Binance, écrit en Python, avec un tableau de bord web basique pour le monitoring et le contrôle. Il utilise une stratégie configurable basée sur les croisements de Moyennes Mobiles Exponentielles (EMA) et le Relative Strength Index (RSI), avec des filtres optionnels. Il intègre également les WebSockets de Binance pour les mises à jour de prix en temps réel.

**AVERTISSEMENT : Le trading de cryptomonnaies comporte des risques substantiels. Ce logiciel est fourni à titre éducatif et expérimental. Utilisez-le à vos propres risques. Il est FORTEMENT recommandé de tester intensivement sur le réseau TESTNET de Binance avant d'envisager une utilisation avec de l'argent réel. L'auteur n'est pas responsable des pertes financières.**

## Fonctionnalités

*   **Connexion Binance :** Se connecte à l'API Binance (réelle ou testnet via `config.py`).
*   **Stratégie Configurable :**
    *   Basée sur le croisement des EMA (courte/longue).
    *   Filtre RSI pour éviter les entrées en conditions extrêmes.
    *   Filtre EMA optionnel (long terme) pour confirmation de tendance.
    *   Confirmation par volume optionnelle.
    *   Calcul de la taille de position basé sur le risque par trade (`RISK_PER_TRADE`) et l'allocation du capital (`CAPITAL_ALLOCATION`).
*   **Données Temps Réel :** Utilise les WebSockets (`@miniTicker`) pour obtenir les mises à jour de prix en temps réel.
*   **Gestion des Ordres :** Place des ordres `MARKET` (Achat/Vente).
*   **Gestion d'État :**
    *   Suit si le bot est actuellement en position.
    *   Conserve les détails de l'ordre d'entrée.
    *   Maintient un historique des ordres passés.
*   **Persistance :** Sauvegarde l'état de position (`in_position`, `entry_details`) et l'historique des ordres (`order_history`) dans `bot_data.json` pour permettre la reprise après un redémarrage.
*   **Backend Flask :** API simple pour gérer le bot et servir les données.
*   **Dashboard Web :** Interface utilisateur basique (HTML/CSS/JS) pour :
    *   Visualiser le statut du bot (En cours, Arrêté, Erreur...).
    *   Afficher le symbole, le timeframe, le **prix actuel (via WebSocket)**.
    *   Voir la balance (USDT ou autre quote asset) et la quantité de l'asset de base possédée.
    *   Indiquer si une position est ouverte.
    *   Démarrer et arrêter le bot.
    *   Visualiser et modifier les paramètres de la stratégie (périodes EMA/RSI, niveaux RSI, risque, allocation du capital, options de filtre) en temps réel.
    *   Afficher les logs du backend en temps réel (via Server-Sent Events).
    *   Consulter l'historique des ordres passés, incluant la **performance en %** pour les trades clôturés.
*   **Gestion Concurrente :** Utilise `threading` pour gérer la boucle principale du bot, le serveur Flask, et le gestionnaire WebSocket. Utilise `queue.Queue` pour la communication thread-safe du prix temps réel entre le thread WebSocket et les requêtes Flask (`/status`).
*   **Configuration :** Paramètres principaux dans `config.py`, ajustables via l'interface web.
*   **Gestion des Erreurs :** Logging basique et gestion des exceptions API Binance.

## Architecture

*   **`backend/bot.py`:** Fichier principal contenant l'application Flask, la logique de gestion du bot (démarrage/arrêt), le callback WebSocket (`process_ticker_message`), la gestion de l'état global (`bot_state`, `bot_config`) et la communication inter-threads via `latest_price_data_queue`.
*   **`backend/strategy.py`:** Contient la logique de calcul des indicateurs techniques (EMA, RSI, Volume) et la détermination des signaux d'achat/vente basés sur les paramètres configurés. Gère également le formatage des quantités pour les ordres.
*   **`backend/binance_client_wrapper.py`:** Encapsule les interactions avec l'API REST de Binance (initialisation du client, récupération des klines, passage d'ordres, récupération des soldes, etc.).
*   **`config.py`:** (À la racine) Contient les clés API Binance, le flag `USE_TESTNET`, et les valeurs par défaut des paramètres de stratégie.
*   **`bot_data.json`:** (À la racine) Fichier où l'état de position et l'historique des ordres sont sauvegardés.

Le système utilise plusieurs threads :
1.  **Thread Principal Flask:** Gère les requêtes HTTP pour l'API.
2.  **Thread `run_bot`:** Exécute la boucle principale de la stratégie (récupération klines via REST, calcul indicateurs, décision d'entrée/sortie basée sur les indicateurs).
3.  **Threads `ThreadedWebsocketManager`:** Gérés par `python-binance` pour écouter les messages WebSocket (`@miniTicker`) et appeler `process_ticker_message`.
4.  **Thread `process_ticker_message`:** (Exécuté par le Manager WS) Reçoit le prix temps réel, le met dans `latest_price_data_queue`. (Pourrait aussi gérer SL/TP ici à l'avenir).
5.  **Threads `execute_exit` (potentiels):** Lancés pour exécuter les ordres de sortie sans bloquer le thread appelant.

La communication du prix temps réel du thread WebSocket vers l'API `/status` se fait via `latest_price_data_queue`. La protection des autres parties de l'état partagé (`bot_state`, `bot_config`) utilise `config_lock`.

## Tech Stack

*   **Backend :** Python 3, Flask, Flask-CORS, python-binance, pandas, pandas-ta
*   **Frontend :** HTML, CSS, Vanilla JavaScript
*   **API :** Binance API

## Installation

1.  **Prérequis :**
    *   Python 3.7+
    *   pip

2.  **Cloner le dépôt :**
    ```bash
    git clone <URL_DU_DEPOT> # Remplace par l'URL de ton dépôt Git
    cd trading-bot
    ```

3.  **Créer un environnement virtuel (recommandé) :**
    ```bash
    python -m venv venv
    # Sur Linux/macOS:
    source venv/bin/activate
    # Sur Windows:
    .\venv\Scripts\activate
    ```

4.  **Installer les dépendances Python :**
    Crée un fichier `requirements.txt` à la racine du projet avec le contenu suivant (ou adapte si tu en as déjà un) :
    ```txt
    Flask
    Flask-Cors
    python-binance
    pandas
    pandas-ta
    requests # Dépendance implicite mais bonne à lister
    numpy # Dépendance implicite mais bonne à lister
    python-dateutil # Dépendance de python-binance
    pytz # Dépendance de python-binance
    # Ajoute d'autres dépendances si nécessaire
    ```
    Puis installe les dépendances :
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: L'installation de `pandas-ta` peut parfois nécessiter `numpy` ou d'autres dépendances système selon votre OS).*

5.  **Configuration :**
    *   Crée un fichier `config.py` à la racine du projet.
    *   Modifie `config.py` pour y mettre tes **clés API Binance**.
        ```python
        # config.py
        BINANCE_API_KEY = "VOTRE_CLE_API"
        BINANCE_API_SECRET = "VOTRE_SECRET_API"

        # Mettre à True pour utiliser le réseau de test Binance
        USE_TESTNET = True # IMPORTANT: Mettre à True pour les tests !

        # Paramètres par défaut de la stratégie (peuvent être modifiés via l'UI)
        SYMBOL = 'BTCUSDT'
        TIMEFRAME = '1m' # Assure-toi que ça correspond à ce que tu veux par défaut
        RISK_PER_TRADE = 0.01
        CAPITAL_ALLOCATION = 1.0

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
        ```
    *   **IMPORTANT :** Commence TOUJOURS avec `USE_TESTNET = True` pour tester sans risque financier.

## Utilisation

1.  **Lancer le Backend (API Flask) :**
    Ouvre un terminal, navigue jusqu'à la racine du projet (`trading-bot`) et active ton environnement virtuel.
    ```bash
    # Assure-toi d'être dans le dossier trading-bot
    # source venv/bin/activate # ou .\venv\Scripts\activate
    python backend/bot.py
    ```
    Le backend devrait démarrer et écouter sur `http://0.0.0.0:5000`. Tu verras les logs dans ce terminal.

2.  **Lancer le Serveur Frontend :**
    Ouvre un **autre** terminal, navigue jusqu'à la racine du projet (`trading-bot`).
    ```bash
    # Assure-toi d'être dans le dossier trading-bot
    python -m http.server 8000
    ```
    Ce serveur servira les fichiers statiques (HTML/CSS/JS) qui se trouvent à la racine.

3.  **Accéder au Dashboard :**
    Ouvre ton navigateur web et va à l'adresse `http://127.0.0.1:8000`.

4.  **Interagir avec le Dashboard :**
    *   Le statut, les balances, le prix (qui doit maintenant se mettre à jour rapidement), etc., devraient se charger.
    *   Les logs du backend apparaissent dans la section "Logs".
    *   L'historique des ordres s'affiche et se met à jour.
    *   Utilise les boutons "Démarrer le Bot" / "Arrêter le Bot".
    *   Modifie les paramètres et clique sur "Sauvegarder".

## Stratégie Implémentée (Base)

*   **Signal d'Achat (Long) :**
    1.  L'EMA courte croise au-dessus de l'EMA longue.
    2.  Le RSI n'est pas en zone de surachat extrême (`< RSI_OVERBOUGHT`).
    3.  *Optionnel (si `USE_EMA_FILTER` est `True`)* : Le prix de clôture est au-dessus de l'EMA de filtre.
    4.  *Optionnel (si `USE_VOLUME_CONFIRMATION` est `True`)* : Le volume actuel est supérieur à sa moyenne mobile.
*   **Signal de Vente (Sortie de Long) :**
    1.  L'EMA courte croise en dessous de l'EMA longue.
    2.  Le RSI n'est pas en zone de survente extrême (`> RSI_OVERSOLD`).
    *(Note : La logique de sortie (`check_exit_conditions`) est appelée dans la boucle principale `run_bot` lorsque le bot est en position).*
*   **Gestion du Risque :**
    *   La taille de la position est calculée pour risquer un pourcentage défini (`RISK_PER_TRADE`) d'une portion du solde (`CAPITAL_ALLOCATION`).
    *   La quantité est ajustée pour respecter les règles `LOT_SIZE` et `MIN_NOTIONAL` de Binance.
*   **Stop-Loss / Take-Profit (via WebSocket) :**
    *   La fonction `process_ticker_message` pourrait être étendue pour vérifier le prix reçu via WebSocket par rapport aux niveaux SL/TP calculés lors de l'entrée en position (stockés dans `entry_details`) et déclencher `execute_exit` immédiatement si un niveau est atteint. *(Actuellement non implémenté dans la version fournie)*.

## TODO / Améliorations Futures

*   **Implémenter SL/TP via WebSocket :** Ajouter la logique dans `process_ticker_message` pour une réaction rapide aux niveaux Stop-Loss et Take-Profit.
*   **Améliorer le Stop-Loss :** Utiliser une méthode plus dynamique (ATR, etc.) pour *calculer* le niveau SL initial.
*   **Optimiser `run_bot` :** Envisager d'utiliser le stream WebSocket `@kline_<interval>` dans `run_bot` au lieu de `get_klines` via REST pour les décisions de stratégie, surtout pour les timeframes courts.
*   **Optimiser les appels API :** Réduire la fréquence des appels `get_account_balance` (peut-être via WebSockets User Data Stream ?).
*   **Sécurité des Clés API :** Utiliser des variables d'environnement ou un gestionnaire de secrets.
*   **Gestion des Erreurs :** Affiner la gestion des erreurs (rate limits, déconnexions, fonds insuffisants...).
*   **Tests Automatisés :** Ajouter des tests unitaires (`pytest`).
*   **Déploiement :** Utiliser Gunicorn/uWSGI + Nginx.
*   **Interface Utilisateur :** Améliorer l'UI (graphiques ?, indicateurs de chargement).
*   **Stratégies Multiples / Backtesting.**

## Avertissement Important

*   **CECI N'EST PAS UN CONSEIL FINANCIER.**
*   Utilisez ce logiciel à vos propres risques.
*   Le trading automatisé est complexe et risqué. Des bugs peuvent exister.
*   Assurez-vous de bien comprendre le code, la stratégie et les risques avant d'utiliser de l'argent réel.
*   **Commencez impérativement par le TESTNET.**
