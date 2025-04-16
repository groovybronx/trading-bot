# Binance Trading Bot Dashboard

Ce projet est un bot de trading simple pour Binance, écrit en Python, avec un tableau de bord web basique pour le monitoring et le contrôle. Il utilise une stratégie configurable basée sur les croisements de Moyennes Mobiles Exponentielles (EMA) et le Relative Strength Index (RSI), avec des filtres optionnels.

**AVERTISSEMENT : Le trading de cryptomonnaies comporte des risques substantiels. Ce logiciel est fourni à titre éducatif et expérimental. Utilisez-le à vos propres risques. Il est FORTEMENT recommandé de tester intensivement sur le réseau TESTNET de Binance avant d'envisager une utilisation avec de l'argent réel. L'auteur n'est pas responsable des pertes financières.**

## Fonctionnalités

*   **Connexion Binance :** Se connecte à l'API Binance (réelle ou testnet via `config.py`).
*   **Stratégie Configurable :**
    *   Basée sur le croisement des EMA (courte/longue).
    *   Filtre RSI pour éviter les entrées en conditions extrêmes.
    *   Filtre EMA optionnel (long terme) pour confirmation de tendance.
    *   Confirmation par volume optionnelle.
    *   Calcul de la taille de position basé sur le risque par trade.
*   **Backend Flask :** API simple pour gérer le bot et servir les données.
*   **Dashboard Web :** Interface utilisateur basique (HTML/CSS/JS) pour :
    *   Visualiser le statut du bot (En cours, Arrêté, Erreur...).
    *   Afficher le symbole, le timeframe, le prix actuel.
    *   Voir la balance (USDT ou autre quote asset) et la quantité de l'asset de base possédée.
    *   Indiquer si une position est ouverte.
    *   Démarrer et arrêter le bot.
    *   Visualiser et modifier les paramètres de la stratégie en temps réel.
    *   Afficher les logs du backend en temps réel (via Server-Sent Events).
    *   Consulter l'historique des ordres passés pendant la session actuelle.
*   **Configuration :** Paramètres principaux dans `config.py`, ajustables via l'interface web.
*   **Gestion des Erreurs :** Logging basique et gestion des exceptions API Binance.

## Tech Stack

*   **Backend :** Python 3, Flask, python-binance, pandas, pandas-ta
*   **Frontend :** HTML, CSS, Vanilla JavaScript
*   **API :** Binance API

## Installation

1.  **Prérequis :**
    *   Python 3.7+
    *   pip

2.  **Cloner le dépôt :**
    ```bash
    git clone <URL_DU_DEPOT> # Remplace par l'URL de ton dépôt Git si tu en as un
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
    Crée un fichier `requirements.txt` à la racine du projet avec le contenu suivant :
    ```txt
    Flask
    Flask-Cors
    python-binance
    pandas
    pandas-ta
    # Ajoute d'autres dépendances si nécessaire (ex: numpy si pandas-ta le requiert explicitement)
    ```
    Puis installe les dépendances :
    ```bash
    pip install -r requirements.txt
    ```

5.  **Configuration :**
    *   Va dans le dossier `backend`.
    *   Renomme `config.py.example` en `config.py` (si tu as un fichier d'exemple) ou crée `config.py`.
    *   Modifie `config.py` pour y mettre tes **clés API Binance**.
        ```python
        # config.py
        BINANCE_API_KEY = "VOTRE_CLE_API"
        BINANCE_API_SECRET = "VOTRE_SECRET_API"

        # Mettre à True pour utiliser le réseau de test Binance
        USE_TESTNET = True # IMPORTANT: Mettre à True pour les tests !

        # Paramètres par défaut de la stratégie (peuvent être modifiés via l'UI)
        SYMBOL = 'BTCUSDT'
        TIMEFRAME = '5m' # ex: '1m', '5m', '15m', '1h', '4h'
        RISK_PER_TRADE = 0.01  # Risque 1% du capital par trade
        CAPITAL_ALLOCATION = 1.0 # Utiliser 100% du capital disponible pour calculer la taille (ajuster si besoin)

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
    Ouvre un terminal, navigue jusqu'au dossier `backend` et active ton environnement virtuel si ce n'est pas déjà fait.
    ```bash
    cd backend
    # source ../venv/bin/activate # Si tu étais à la racine
    python bot.py
    ```
    Le backend devrait démarrer et écouter sur `http://127.0.0.1:5000`. Tu verras les logs dans ce terminal.

2.  **Lancer le Serveur Frontend :**
    Ouvre un **autre** terminal, navigue jusqu'au dossier `frontend`.
    ```bash
    cd frontend
    python -m http.server 8000
    ```
    Ce serveur très simple servira les fichiers HTML/CSS/JS. Tu peux utiliser un autre port si 8000 est occupé. Note que ce serveur affichera des logs de requêtes HTTP, tu peux les ignorer ou les rediriger (voir réponses précédentes).

3.  **Accéder au Dashboard :**
    Ouvre ton navigateur web et va à l'adresse `http://127.0.0.1:8000` (ou le port que tu as utilisé pour le serveur frontend).

4.  **Interagir avec le Dashboard :**
    *   Le statut, les balances, le prix, etc., devraient se charger et se mettre à jour automatiquement.
    *   Les logs du backend apparaissent dans la section "Logs".
    *   L'historique des ordres de la session s'affiche dans la table dédiée.
    *   Utilise les boutons "Démarrer le Bot" / "Arrêter le Bot" pour contrôler le processus de trading.
    *   Modifie les paramètres dans la section "Paramètres de Stratégie" et clique sur "Sauvegarder". Certains changements (comme le timeframe) peuvent nécessiter un redémarrage manuel du bot via les boutons Start/Stop pour être pleinement appliqués.

## Stratégie Implémentée (Base)

*   **Signal d'Achat (Long) :**
    1.  L'EMA courte croise au-dessus de l'EMA longue.
    2.  Le RSI n'est pas en zone de surachat extrême (`< RSI_OVERBOUGHT`).
    3.  *Optionnel (si `USE_EMA_FILTER` est `True`)* : Le prix de clôture est au-dessus de l'EMA de filtre (long terme).
    4.  *Optionnel (si `USE_VOLUME_CONFIRMATION` est `True`)* : Le volume actuel est supérieur à sa moyenne mobile.
*   **Signal de Vente (Sortie de Long) :**
    1.  L'EMA courte croise en dessous de l'EMA longue.
    2.  Le RSI n'est pas en zone de survente extrême (`> RSI_OVERSOLD`).
    *(Note : La logique de sortie (`check_exit_conditions`) est présente mais peut nécessiter d'être appelée explicitement dans la boucle principale de `bot.py` lorsque le bot est en position).*
*   **Gestion du Risque :**
    *   La taille de la position est calculée pour risquer un pourcentage défini (`RISK_PER_TRADE`) du capital alloué (`CAPITAL_ALLOCATION` * balance) sur la base d'un stop-loss (actuellement défini comme un pourcentage fixe sous le prix d'entrée dans `strategy.py` - **ceci est un exemple simple et pourrait être amélioré**).
    *   La quantité est ajustée pour respecter les règles `LOT_SIZE` et `MIN_NOTIONAL` de Binance.

## Avertissement Important

*   **CECI N'EST PAS UN CONSEIL FINANCIER.**
*   Utilisez ce logiciel à vos propres risques.
*   Le trading automatisé est complexe et risqué. Des bugs peuvent exister.
*   Assurez-vous de bien comprendre le code, la stratégie et les risques avant d'utiliser de l'argent réel.
*   **Commencez impérativement par le TESTNET.**

