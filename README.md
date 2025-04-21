# Binance Trading Bot Dashboard

Ce projet est un bot de trading simple pour Binance, écrit en Python, avec un tableau de bord web basique pour le monitoring et le contrôle. Il utilise une stratégie configurable basée sur les croisements de Moyennes Mobiles Exponentielles (EMA) et le Relative Strength Index (RSI), avec des filtres optionnels. Il intègre également les WebSockets de Binance pour les mises à jour de prix, de klines, et des données utilisateur en temps réel.

**AVERTISSEMENT : Le trading de cryptomonnaies comporte des risques substantiels. Ce logiciel est fourni à titre éducatif et expérimental. Utilisez-le à vos propres risques. Il est FORTEMENT recommandé de tester intensivement sur le réseau TESTNET de Binance avant d'envisager une utilisation avec de l'argent réel. L'auteur n'est pas responsable des pertes financières.**

## Fonctionnalités

*   **Connexion Binance :** Se connecte à l'API Binance (réelle ou testnet via `config.py`).
*   **Stratégie Configurable :**
    *   Basée sur le croisement des EMA (courte/longue).
    *   Filtre RSI pour éviter les entrées en conditions extrêmes.
    *   Filtre EMA optionnel (long terme) pour confirmation de tendance.
    *   Confirmation par volume optionnelle.
    *   Calcul de la taille de position basé sur le risque par trade (`RISK_PER_TRADE`) et l'allocation du capital (`CAPITAL_ALLOCATION`).
*   **Données Temps Réel (WebSockets) :**
    *   Utilise `@miniTicker` pour le prix actuel et le déclenchement rapide du Stop-Loss/Take-Profit.
    *   Utilise `@kline_<interval>` pour recevoir les bougies fermées et déclencher l'analyse de stratégie.
    *   Utilise le User Data Stream pour la mise à jour en temps réel des soldes du compte (`outboundAccountPosition`) et le suivi des ordres (`executionReport`).
*   **Gestion des Ordres :** Place des ordres `MARKET` (Achat/Vente).
*   **Gestion d'État :**
    *   Suit si le bot est actuellement en position.
    *   Conserve les détails de l'ordre d'entrée (prix, quantité, timestamp).
    *   Maintient un historique des ordres passés.
*   **Persistance :** Sauvegarde l'état de position (`in_position`, `entry_details`) et l'historique des ordres (`order_history`) dans `bot_data.json` pour permettre la reprise après un redémarrage.
*   **Backend Flask :** API simple pour gérer le bot et servir les données.
*   **Dashboard Web :** Interface utilisateur basique (HTML/CSS/JS) pour :
    *   Visualiser le statut du bot (En cours, Arrêté, Erreur...).
    *   Afficher le symbole, le timeframe.
    *   Voir la balance (Quote Asset) et la quantité de l'Asset de Base possédée (mises à jour via User Data Stream).
    *   Afficher le prix actuel (via WebSocket Ticker).
    *   Indiquer si une position est ouverte (avec détails d'entrée).
    *   Démarrer et arrêter le bot.
    *   Visualiser et modifier les paramètres de la stratégie en temps réel.
    *   Afficher les logs du backend et recevoir les notifications de mise à jour de l'historique (via Server-Sent Events).
    *   Consulter l'historique des ordres passés (trié, plus récent en premier), incluant la performance en % pour les trades clôturés, avec rafraîchissement automatique.
*   **Gestion Concurrente :** Utilise `threading` pour gérer le serveur Flask, la boucle principale simplifiée du bot (`run_bot`), le thread de keepalive du User Data Stream (`run_keepalive`), et le gestionnaire WebSocket. Utilise `queue.Queue` pour la communication thread-safe (logs SSE, prix ticker).
*   **Configuration :** Paramètres principaux dans `config.py`, ajustables via l'interface web.
*   **Gestion des Erreurs :** Logging basique et gestion des exceptions API Binance.

## Architecture (Refactorisée)

Le code backend est maintenant structuré en plusieurs modules pour une meilleure organisation :

*   **`backend/app.py`:** Point d'entrée principal. Initialise l'application Flask, configure CORS, enregistre le Blueprint API et lance le serveur.
*   **`backend/logging_config.py`:** Configure le système de logging (console et queue pour SSE). Exporte `log_queue`.
*   **`backend/config_manager.py`:** Charge la configuration depuis `config.py`, définit les constantes (`VALID_TIMEFRAMES`, `TIMEFRAME_CONSTANT_MAP`), et maintient le dictionnaire `bot_config` modifiable.
*   **`backend/state_manager.py`:** Définit et gère l'état global du bot (`bot_state`), l'historique des klines (`kline_history`), la queue de prix (`latest_price_queue`), les verrous (`config_lock`, `kline_history_lock`), et les fonctions de persistance (`save_data`, `load_data`).
*   **`backend/websocket_handlers.py`:** Contient les fonctions de callback pour les messages des différents WebSockets :
    *   `process_ticker_message`: Traite les messages `@miniTicker`, met à jour `latest_price_queue`, et vérifie/déclenche le Stop-Loss et le Take-Profit.
    *   `process_kline_message`: Traite les messages `@kline_<interval>`, met à jour `kline_history`, et déclenche l'analyse de stratégie (`calculate_indicators_and_signals`, `check_entry_conditions`, `check_exit_conditions`) sur les bougies fermées.
    *   `process_user_data_message`: Traite les messages du User Data Stream, notamment `outboundAccountPosition` pour mettre à jour les soldes dans `bot_state` et `executionReport` pour logger les événements d'ordre.
*   **`backend/bot_core.py`:** Contient la logique métier principale :
    *   `start_bot_core`, `stop_bot_core`: Fonctions appelées par l'API pour gérer le cycle de vie complet du bot (nettoyage, initialisation, démarrage/arrêt des threads et WebSockets, fermeture du listen key).
    *   `run_bot`: Boucle principale simplifiée du thread du bot (attend principalement l'ordre d'arrêt).
    *   `run_keepalive`: Thread qui envoie périodiquement des keepalives pour le User Data Stream.
    *   `execute_exit`: Fonction centralisée pour placer l'ordre de vente de sortie de position.
*   **`backend/api_routes.py`:** Définit un Flask Blueprint contenant toutes les routes de l'API REST (`/status`, `/parameters`, `/start`, `/stop`, `/order_history`, `/stream_logs`). Interagit avec `state_manager` et `bot_core`.
*   **`backend/strategy.py`:** (Inchangé) Contient la logique de calcul des indicateurs techniques (EMA, RSI, Volume) et la détermination des signaux d'achat/vente. Gère également le formatage des quantités.
*   **`backend/binance_client_wrapper.py`:** (Inchangé) Encapsule les interactions avec l'API REST de Binance (initialisation, klines, ordres, soldes, gestion User Data Stream).
*   **`config.py`:** (Racine) Contient les clés API, `USE_TESTNET`, et les valeurs par défaut des paramètres.
*   **`bot_data.json`:** (Racine) Fichier de persistance pour l'état et l'historique.

**Threads principaux :**
1.  **Thread Principal Flask:** Gère les requêtes HTTP API.
2.  **Thread `run_bot`:** Boucle de vie principale du bot, maintenant très légère (attend l'arrêt).
3.  **Thread `run_keepalive`:** Maintient la connexion User Data Stream active.
4.  **Threads `ThreadedWebsocketManager`:** Gérés par `python-binance` pour écouter les 3 flux WebSocket (Ticker, Kline, User) et appeler les callbacks respectifs dans `websocket_handlers.py`.
5.  **Threads `execute_exit` (potentiels):** Lancés pour exécuter les ordres de sortie sans bloquer.

**Communication :**
*   **API REST:** Pour le contrôle (start/stop), la configuration (get/set params), et la récupération d'état (status, history).
*   **Server-Sent Events (SSE):** Pour streamer les logs et les événements (`EVENT:ORDER_HISTORY_UPDATED`) vers le frontend.
*   **Verrous (`threading.Lock`):** Pour protéger l'accès concurrent aux données partagées (`bot_state`, `bot_config`, `kline_history`).
*   **Queues (`queue.Queue`):** Pour la communication inter-thread (logs SSE, prix ticker).

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
    Assurez-vous d'avoir un fichier `requirements.txt` à la racine avec au moins :
    ```txt
    Flask
    Flask-Cors
    python-binance
    pandas
    pandas-ta
    requests
    numpy
    # Ajoutez d'autres dépendances si nécessaire (ex: python-dateutil, pytz si non inclus par python-binance)
    ```
    Puis installez :
    ```bash
    pip install -r requirements.txt
    ```

5.  **Configuration :**
    *   Créez un fichier `config.py` à la racine du projet (s'il n'existe pas).
    *   Modifiez `config.py` pour y mettre vos **clés API Binance**.
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
        STOP_LOSS_PERCENTAGE = 0.02 # SL initial en %
        TAKE_PROFIT_PERCENTAGE = 0.05 # TP initial en %

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
    *   **IMPORTANT :** Commencez TOUJOURS avec `USE_TESTNET = True` pour tester sans risque financier.

## Utilisation

1.  **Lancer le Backend (API Flask) :**
    Ouvre un terminal, navigue jusqu'au dossier `backend` (`trading-bot/backend`) et active ton environnement virtuel.
    ```bash
    # Assure-toi d'être dans le dossier trading-bot/backend
    # source ../venv/bin/activate # ou ..\venv\Scripts\activate si lancé depuis backend/
    python app.py
    ```
    Le backend devrait démarrer et écouter sur `http://0.0.0.0:5000`. Tu verras les logs dans ce terminal.

2.  **Lancer le Serveur Frontend :**
    Ouvre un **autre** terminal, navigue jusqu'au dossier `frontend` (`trading-bot/frontend`).
    ```bash
    # Assure-toi d'être dans le dossier trading-bot/frontend
    python -m http.server 8000
    ```
    Ce serveur servira les fichiers statiques (HTML/CSS/JS) qui se trouvent dans le dossier `frontend`.

3.  **Accéder au Dashboard :**
    Ouvre ton navigateur web et va à l'adresse `http://127.0.0.1:8000`.

4.  **Interagir avec le Dashboard :**
    *   Le statut, les balances, le prix, etc., devraient se charger et se mettre à jour.
    *   Les logs du backend apparaissent dans la section "Logs".
    *   L'historique des ordres s'affiche et se met à jour automatiquement lorsqu'un ordre est ajouté.
    *   Utilise les boutons "Démarrer le Bot" / "Arrêter le Bot".
    *   Modifie les paramètres et clique sur "Sauvegarder".

## Stratégie Implémentée (Base)

*   **Signal d'Achat (Long) :** (Déclenché par `process_kline_message`)
    1.  L'EMA courte croise au-dessus de l'EMA longue sur une bougie fermée.
    2.  Le RSI n'est pas en zone de surachat extrême (`< RSI_OVERBOUGHT`).
    3.  *Optionnel (si `USE_EMA_FILTER` est `True`)* : Le prix de clôture est au-dessus de l'EMA de filtre.
    4.  *Optionnel (si `USE_VOLUME_CONFIRMATION` est `True`)* : Le volume de la bougie est supérieur à sa moyenne mobile.
*   **Signal de Vente (Sortie de Long - Indicateur) :** (Déclenché par `process_kline_message`)
    1.  L'EMA courte croise en dessous de l'EMA longue sur une bougie fermée.
    2.  Le RSI n'est pas en zone de survente extrême (`> RSI_OVERSOLD`).
*   **Sortie Stop-Loss / Take-Profit :** (Déclenché par `process_ticker_message`)
    1.  Le prix reçu via le WebSocket `@miniTicker` atteint ou dépasse le niveau Stop-Loss calculé lors de l'entrée (`entry_price * (1 - STOP_LOSS_PERCENTAGE)`).
    2.  Le prix reçu via le WebSocket `@miniTicker` atteint ou dépasse le niveau Take-Profit calculé lors de l'entrée (`entry_price * (1 + TAKE_PROFIT_PERCENTAGE)`).
*   **Gestion du Risque :**
    *   La taille de la position est calculée pour risquer un pourcentage défini (`RISK_PER_TRADE`) d'une portion du solde (`CAPITAL_ALLOCATION`).
    *   La quantité est ajustée pour respecter les règles `LOT_SIZE` et `MIN_NOTIONAL` de Binance.

## TODO / Améliorations Futures

*   **Améliorer le Stop-Loss/Take-Profit :** Utiliser des méthodes plus dynamiques (ATR, points pivots, etc.) pour *calculer* les niveaux SL/TP initiaux ou utiliser des SL suiveurs.
*   **Sécurité des Clés API :** Utiliser des variables d'environnement ou un gestionnaire de secrets (ex: `python-dotenv`).
*   **Gestion des Erreurs :** Affiner la gestion des erreurs (rate limits, déconnexions WebSocket, fonds insuffisants, erreurs d'ordre spécifiques). Afficher les erreurs importantes dans l'UI.
*   **Tests Automatisés :** Ajouter des tests unitaires (`pytest`) pour la stratégie, les handlers, le core.
*   **Déploiement :** Utiliser Gunicorn/uWSGI + Nginx pour la production.
*   **Interface Utilisateur :** Améliorer l'UI (graphiques ?, indicateurs de chargement plus clairs, meilleure présentation des erreurs).
*   **Stratégies Multiples / Backtesting.**
*   **Gestion des Ordres LIMIT :** Ajouter la possibilité d'utiliser des ordres LIMIT au lieu de MARKET.

## Avertissement Important

*   **CECI N'EST PAS UN CONSEIL FINANCIER.**
*   Utilisez ce logiciel à vos propres risques.
*   Le trading automatisé est complexe et risqué. Des bugs peuvent exister.
*   Assurez-vous de bien comprendre le code, la stratégie et les risques avant d'utiliser de l'argent réel.
*   **Commencez impérativement par le TESTNET.**


Analyse du projet trading-bot terminée. Voici un résumé détaillé des étapes et corrections à venir, basé sur l'analyse des fichiers backend et frontend :

Backend :

Général :
Réduire l'utilisation des variables globales en utilisant des classes pour encapsuler l'état et la configuration.
Améliorer la gestion des erreurs avec des messages de journalisation plus informatifs et une gestion plus fine des exceptions.
Améliorer la documentation en ajoutant des commentaires pour expliquer le code.
Centraliser la validation de la configuration en créant une fonction pour valider tous les paramètres de configuration.
Améliorer la sécurité en ajoutant une authentification pour protéger les routes API.
Améliorer la robustesse en ajoutant une logique pour gérer les erreurs de connexion à la base de données.
bot_core.py :
Simplifier la fonction execute_exit en la divisant en sous-fonctions.
Vérifier la gestion du User Data Stream et s'assurer que la logique de démarrage et d'arrêt est correcte et robuste.
Simplifier les fonctions start_bot_core et stop_bot_core en les divisant en sous-fonctions et en utilisant des classes pour encapsuler la logique de démarrage et d'arrêt.
binance_client_wrapper.py :
Améliorer la gestion des clés API en utilisant des variables d'environnement ou un fichier de configuration plus sécurisé.
config.py :
S'assurer que les clés API sont stockées de manière sécurisée et ajouter une validation pour vérifier si les clés API sont valides.
Supprimer les paramètres inutilisés.
logging_config.py :
Gérer la queue pleine en ajoutant une stratégie de gestion de la queue pleine plus robuste.
state_manager.py :
Centraliser la gestion de l'état en créant des fonctions pour accéder et modifier l'état du bot de manière centralisée.
Améliorer la persistance de l'état en utilisant une base de données ou un autre mécanisme de persistance plus robuste.
strategy.py :
Implémenter la stratégie de scalping en remplaçant les fonctions placeholder par une logique de trading réelle.
Centraliser la gestion des risques en créant une classe pour gérer les paramètres de risque et les calculs de taille de position.
websocket_handlers.py :
Centraliser la gestion des threads en utilisant un pool de threads pour gérer les threads de manière plus efficace.
Améliorer la robustesse en ajoutant une logique pour gérer les erreurs de connexion aux websockets.
api_routes.py :
Utiliser une fonction de validation centralisée pour valider tous les paramètres de configuration.
Frontend :

Général :
Améliorer l'accessibilité en ajoutant des attributs alt aux images, en utilisant des labels pour tous les champs de formulaire et en s'assurant que le code est compatible avec les lecteurs d'écran.
Améliorer la structure en utilisant des classes CSS pour organiser le code et des commentaires pour expliquer le code.
Améliorer la robustesse en ajoutant une logique pour gérer les erreurs de connexion à l'API et au WebSocket.
Améliorer l'expérience utilisateur en ajoutant des animations et des transitions et en ajoutant une validation des champs de formulaire.
script.js :
Simplifier le code en supprimant le code inutilisé ou dupliqué et en utilisant des fonctions et des classes pour organiser le code.
Ces étapes sont priorisées en fonction de leur impact sur la stabilité, la sécurité et la maintenabilité du bot. La simplification du code et l'amélioration de la documentation sont également importantes pour faciliter la collaboration et la compréhension du code.