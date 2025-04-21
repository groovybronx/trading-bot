# Binance Trading Bot avec Dashboard Web

Ce projet est un bot de trading pour Binance (Spot) écrit en Python, accompagné d'une interface web (Dashboard) construite avec Flask et JavaScript. Il permet de surveiller l'état du bot, de visualiser les ordres, de consulter les logs en temps réel, de démarrer/arrêter le bot et de configurer les paramètres de stratégie via le navigateur.

## Fonctionnalités

*   **Connexion Binance :** Utilise l'API REST et les WebSockets de Binance (Spot).
*   **Support Testnet/Production :** Configurable via le fichier `.env`.
*   **Stratégies Multiples :**
    *   **SWING :** Basée sur les indicateurs EMA et RSI sur les données de Klines (bougies).
    *   **SCALPING :** Basée sur les données temps réel du Book Ticker (carnet d'ordres simplifié).
*   **Dashboard Web :** Interface utilisateur pour :
    *   Visualiser l'état du bot (RUNNING, STOPPED, etc.).
    *   Afficher la balance (Quote Asset), la quantité détenue (Base Asset).
    *   Afficher le prix actuel (Bid/Ask ou Mid-Price).
    *   Indiquer si une position est ouverte et les détails d'entrée.
    *   Contrôler le bot (Démarrer / Arrêter).
    *   Configurer les paramètres de la stratégie sélectionnée.
    *   Afficher l'historique des ordres de la session avec calcul de performance pour les trades complétés (BUY puis SELL).
    *   Afficher les logs du backend en temps réel.
*   **Communication Temps Réel :** Utilise les WebSockets pour pousser les mises à jour d'état, les logs et les données de marché (ticker) vers le frontend sans rechargement de page.
*   **Persistance :** Sauvegarde l'état de base (position, historique) dans `bot_data.json` pour pouvoir reprendre après un redémarrage (dans une certaine mesure).

## Architecture

*   **Backend (`backend/`) :**
    *   **`app.py` :** Serveur Flask gérant les routes API (status, start, stop, parameters) et le serveur WebSocket (`/ws_logs`).
    *   **`bot_core.py` :** Logique principale du bot, gestion du thread principal, connexion aux WebSockets Binance.
    *   **`state_manager.py` :** Gère l'état interne du bot (statut, balance, position, historique, configuration, etc.) et sa persistance.
    *   **`config.py` / `config_manager.py` :** Charge et gère la configuration (depuis `.env` et les mises à jour via l'API).
    *   **`binance_client_wrapper.py` :** Encapsule les interactions avec l'API Binance (REST et WebSockets via `python-binance`).
    *   **`websocket_handlers.py` :** Traite les messages reçus des WebSockets Binance (Klines, BookTicker, User Data).
    *   **`websocket_utils.py` :** Gère la diffusion des messages (logs, état, ticker) du backend vers les clients WebSocket du frontend.
    *   **`strategies/` (implicite) :** Contient la logique spécifique à chaque stratégie (calculs d'indicateurs, signaux d'entrée/sortie).
    *   **`utils/logger.py` :** Configure le logging (console et WebSocket).
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
    python-binance>=1.0.17 # Ou la version que vous utilisez
    websockets>=10.0 # Pour le serveur WS Flask -> Frontend
    python-dotenv>=0.19
    requests>=2.25 # Souvent une dépendance de python-binance
    # Ajoutez d'autres dépendances si utilisées (ex: pandas, numpy, TA-Lib si utilisées dans les stratégies)
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
    ```
    **IMPORTANT :** N'ajoutez jamais vos clés API réelles à Git. Assurez-vous que `.env` est dans votre fichier `.gitignore`.
3.  **Autres configurations :** Les paramètres de stratégie (Symbol, Timeframe, EMA, RSI, SL/TP, etc.) sont principalement gérés via l'interface web. Les valeurs par défaut au premier lancement sont définies dans `config.py`.

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
*   **Historique des Ordres :** Liste les ordres passés pendant la session actuelle du backend. Les lignes BUY/SELL sont colorées, et la performance est calculée pour les trades SELL fermant une position BUY précédente.
*   **Logs :** Affiche les messages de log provenant du backend en temps réel.
*   **Contrôles :**
    *   `Démarrer le Bot` : Lance le processus principal du bot (connexion aux WebSockets Binance, exécution de la stratégie).
    *   `Arrêter le Bot` : Arrête le processus principal et ferme les connexions WebSocket Binance.
*   **Paramètres de Stratégie :**
    *   Sélectionnez le `Type de Stratégie` (SWING ou SCALPING) pour afficher les paramètres pertinents.
    *   Modifiez les valeurs souhaitées.
    *   Cliquez sur `Sauvegarder les Paramètres`. Un message indiquera le succès ou l'échec.
    *   **Note :** Certains changements de paramètres (comme `STRATEGY_TYPE` ou `TIMEFRAME_STR`) peuvent nécessiter un **arrêt** puis un **redémarrage** du bot pour être pleinement pris en compte, car ils affectent les abonnements WebSocket ou la logique de base. Le backend peut afficher un message à ce sujet dans les logs ou via l'API.

## Avertissement

Le trading de cryptomonnaies comporte des risques financiers importants. Ce bot est fourni à titre éducatif et expérimental. Utilisez-le à vos propres risques. L'auteur n'est pas responsable des pertes financières potentielles. Assurez-vous de bien comprendre le code et la stratégie avant de l'utiliser avec de l'argent réel. Il est fortement recommandé de tester intensivement sur le **Testnet** de Binance.


## TODO / Améliorations Futures

*   **Améliorer le Stop-Loss/Take-Profit :** Utiliser des méthodes plus dynamiques (ATR, points pivots, etc.) pour *calculer* les niveaux SL/TP initiaux ou utiliser des SL suiveurs.
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