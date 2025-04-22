# Binance Trading Bot avec Dashboard Web

Ce projet est un bot de trading pour Binance (Spot) écrit en Python, accompagné d'une interface web (Dashboard) construite avec Flask et JavaScript. Il permet de surveiller l'état du bot, de visualiser les ordres, de consulter les logs en temps réel, de démarrer/arrêter le bot et de configurer les paramètres de stratégie via le navigateur.

## Fonctionnalités

*   **Connexion Binance :** Utilise l'API REST et les WebSockets de Binance (Spot).
*   **Support Testnet/Production :** Configurable via le fichier `.env`.
*   **Stratégies Modulaires :**
    *   **SWING :** Basée sur les indicateurs EMA et RSI sur les données de Klines (bougies).
    *   **SCALPING :** Basée sur les données temps réel du Book Ticker et de la profondeur du marché.
    *   Logique de stratégie séparée dans le dossier `strategies/` pour une meilleure organisation.
*   **Dashboard Web :** Interface utilisateur pour :
    *   Visualiser l'état du bot (RUNNING, STOPPED, STARTING, ERROR, etc.).
    *   Afficher la balance (Quote Asset), la quantité détenue (Base Asset).
    *   Afficher le prix actuel (Mid-Price basé sur Bid/Ask).
    *   Indiquer si une position est ouverte et les détails d'entrée (prix moyen, quantité, timestamp).
    *   Contrôler le bot (Démarrer / Arrêter).
    *   Configurer les paramètres de la stratégie sélectionnée (avec sauvegarde via API).
    *   Afficher l'historique des ordres (récupéré via REST API) avec calcul de performance pour les trades complétés (BUY puis SELL).
    *   Afficher les logs du backend en temps réel via WebSocket.
*   **Communication Temps Réel :** Utilise les WebSockets (`Flask-Sock` ou similaire côté backend, natif côté frontend) pour pousser les mises à jour d'état, les logs et les données de marché (ticker) vers le frontend sans rechargement de page.
*   **Persistance :** Sauvegarde l'état de base (position, historique des ordres) dans `bot_data.json` pour pouvoir reprendre après un redémarrage (dans une certaine mesure).
*   **Gestion des Threads :** Utilise des threads séparés pour le core du bot, le keepalive du listenKey, et les opérations potentiellement bloquantes (placement/annulation d'ordres, refresh historique).

## Architecture

*   **Backend (`backend/`) :**
    *   **`app.py` :** Serveur Flask gérant les routes API (`/api/*`) et le serveur WebSocket (`/ws_logs`).
    *   **`bot_core.py` :** Orchestration principale du bot (démarrage/arrêt des threads et des WebSockets Binance), gestion des ordres manuels/sorties.
    *   **`state_manager.py` :** Gère l'état interne du bot (statut, balance, position, historique, données temps réel, etc.) de manière thread-safe et gère la persistance (`bot_data.json`).
    *   **`config_manager.py` :** Charge et gère la configuration (depuis `.env` et les mises à jour via l'API), inclut la validation de base.
    *   **`binance_client_wrapper.py` :** Encapsule les interactions avec l'API Binance (REST et WebSockets via `python-binance`), gère les clés API et le client.
    *   **`websocket_handlers.py` :** Traite les messages reçus des WebSockets Binance (Klines, BookTicker, Depth, User Data) et déclenche la logique appropriée (stratégie, SL/TP, mise à jour état).
    *   **`websocket_utils.py` :** Gère la diffusion des messages (logs, état, ticker, historique) du backend vers les clients WebSocket du frontend.
    *   **`strategies/` :** Contient la logique spécifique à chaque stratégie (`swing_strategy.py`, `scalping_strategy.py`).
    *   **`utils/` :**
        *   `order_utils.py` : Fonctions utilitaires pour la gestion des ordres (formatage quantité, min_notional).
        *   (Potentiellement `logging_config.py` ou similaire pour la configuration du logging).
*   **Frontend (`frontend/`) :**
    *   **`index.html` :** Structure de la page du dashboard.
    *   **`style.css` :** Mise en forme et styles visuels.
    *   **`script.js` :** Logique côté client, connexion WebSocket au backend, mise à jour dynamique de l'interface, envoi des commandes API (start/stop/save).

## Prérequis

*   Python 3.8+
*   pip (gestionnaire de paquets Python)
*   Un compte Binance (Testnet ou Production)
*   Clé API et Secret API Binance
*   Un navigateur web moderne

## Installation

1.  **Cloner le dépôt :**
    ```bash
    git clone <url-du-depot>
    cd <nom-du-dossier-du-depot>
    ```
2.  **Créer un environnement virtuel :**
    ```bash
    python -m venv venv
    ```
3.  **Activer l'environnement virtuel :**
    *   macOS/Linux : `source venv/bin/activate`
    *   Windows : `venv\Scripts\activate`
4.  **Installer les dépendances :**
    Créez un fichier `requirements.txt` (s'il n'existe pas) avec au moins les dépendances suivantes (ajustez les versions si nécessaire) :
    ```txt
    # requirements.txt
    Flask>=2.0
    # Flask-Sock ou autre pour WebSockets Flask
    python-binance>=1.0.19 # Ou version plus récente
    python-dotenv>=0.19
    requests>=2.25
    pandas>=1.3 # Pour les stratégies (ex: SWING)
    pandas-ta>=0.3 # Pour les indicateurs techniques
    # numpy (souvent requis par pandas)
    ```
    Puis installez :
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

1.  **Créer le fichier `.env` :**
    À la racine du projet, créez un fichier nommé `.env`.
2.  **Ajouter les clés API :**
    ```dotenv
    # .env
    BINANCE_API_KEY="VOTRE_CLE_API_BINANCE"
    BINANCE_API_SECRET="VOTRE_SECRET_API_BINANCE"

    # Utiliser le Testnet (true) ou le réseau de production (false)
    USE_TESTNET="true"

    # Optionnel: Configurer le niveau de log par défaut
    # LOG_LEVEL="INFO" # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
    ```
    **IMPORTANT :** N'ajoutez jamais vos clés API réelles à Git. Assurez-vous que `.env` est dans votre fichier `.gitignore`.
3.  **Autres configurations :** Les paramètres de stratégie (Symbol, Timeframe, EMA, RSI, SL/TP, etc.) sont principalement gérés via l'interface web. Les valeurs par défaut au premier lancement sont définies dans `config_manager.py`.

## Lancement

1.  **Activer l'environnement virtuel** (si ce n'est pas déjà fait) :
    ```bash
    source venv/bin/activate # ou venv\Scripts\activate
    ```
2.  **Démarrer le backend Flask :**
    ```bash
    python backend/app.py
    ```
    Le serveur indiquera l'adresse sur laquelle il écoute (par exemple `http://127.0.0.1:5000`).
3.  **Ouvrir le Dashboard :**
    Ouvrez votre navigateur web et allez à l'adresse indiquée par Flask (généralement `http://127.0.0.1:5000`).

## Utilisation du Dashboard

*   **Statut du Bot :** Affiche l'état actuel, la stratégie, le symbole, les balances, le prix et la position.
*   **Historique des Ordres :** Liste les ordres récents récupérés via l'API REST. Les lignes BUY/SELL peuvent avoir des styles distincts, et la performance est calculée pour les trades SELL fermant une position BUY précédente (basé sur l'historique interne).
*   **Logs :** Affiche les messages de log provenant du backend en temps réel.
*   **Contrôles :**
    *   `Démarrer le Bot` : Lance le processus principal du bot (`bot_core`).
    *   `Arrêter le Bot` : Arrête le processus principal et ferme les connexions.
*   **Paramètres de Stratégie :**
    *   Sélectionnez le `Type de Stratégie` (SWING ou SCALPING) pour afficher/masquer les paramètres pertinents.
    *   Modifiez les valeurs souhaitées.
    *   Cliquez sur `Sauvegarder les Paramètres`. Un message indiquera le succès ou l'échec.
    *   **Note :** Certains changements (ex: `STRATEGY_TYPE`, `SYMBOL`, `TIMEFRAME_STR`) nécessitent un **arrêt** puis un **redémarrage** du bot pour être pris en compte. L'interface ou les logs peuvent l'indiquer.

## TODO / Améliorations Futures

*   **Gestion des Risques :**
    *   Centraliser la gestion des risques (calcul taille de position) dans une classe ou un module dédié.
    *   Implémenter des SL/TP plus dynamiques (ATR, points pivots, suiveurs).
*   **Gestion des Erreurs & Robustesse :**
    *   Gestion plus fine des erreurs API Binance (rate limits, fonds insuffisants, erreurs spécifiques d'ordre).
    *   Gestion robuste des déconnexions/erreurs WebSocket (reconnexion, resynchronisation état).
    *   Afficher les erreurs critiques dans l'UI.
    *   Améliorer la gestion des inconsistances d'état (ex: balance vs état `in_position`).
*   **Structure & Refactoring Backend :**
    *   Réduire l'utilisation de variables globales/état partagé direct dans `bot_core.py` (potentiellement via une classe `Bot`).
    *   Simplifier les fonctions `start_bot_core`, `stop_bot_core`, `execute_exit`.
    *   Centraliser la validation de la configuration.
    *   Utiliser un pool de threads pour la gestion des tâches asynchrones (ordres, refresh).
*   **Persistance :** Utiliser une base de données (SQLite, etc.) pour une persistance plus robuste de l'état et de l'historique.
*   **Stratégies & Backtesting :**
    *   Ajouter la possibilité d'implémenter et de sélectionner facilement d'autres stratégies.
    *   Intégrer un framework de backtesting (ex: `backtesting.py`, `vectorbt`) pour tester les stratégies sur des données historiques.
*   **Gestion des Ordres :**
    *   Améliorer la gestion des ordres LIMIT (suivi plus précis, modification/annulation plus flexible).
    *   Explorer d'autres types d'ordres (Stop-Limit, OCO).
*   **Interface Utilisateur (Frontend) :**
    *   Ajouter des graphiques de prix (ex: via Lightweight Charts, Chart.js).
    *   Améliorer l'affichage des indicateurs de chargement et des erreurs.
    *   Ajouter validation des champs de formulaire côté client.
    *   Améliorer l'accessibilité et la structure sémantique du HTML/CSS.
    *   Simplifier/organiser le code JavaScript (`script.js`).
*   **Sécurité :**
    *   Ajouter une authentification basique pour protéger l'accès à l'API et au dashboard.
    *   Sécuriser davantage le stockage/gestion des clés API.
*   **Tests Automatisés :** Ajouter des tests unitaires et d'intégration (`pytest`).
*   **Déploiement :** Documenter/configurer pour un déploiement en production (Gunicorn/uWSGI + Nginx, Docker).
*   **Documentation :** Ajouter des docstrings et commentaires plus détaillés dans le code.

## Avertissement Important

*   **CECI N'EST PAS UN CONSEIL FINANCIER.**
*   Utilisez ce logiciel à vos propres risques.
*   Le trading automatisé est complexe et risqué. Des bugs peuvent exister et entraîner des pertes financières.
*   Assurez-vous de bien comprendre le code, la stratégie et les risques avant d'utiliser de l'argent réel.
*   **Commencez impérativement par le TESTNET de Binance.**
