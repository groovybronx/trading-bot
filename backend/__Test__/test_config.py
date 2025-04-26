# /Users/davidmichels/Desktop/trading-bot/backend/__Test__/test_config.py

import unittest
import os
import importlib
from unittest.mock import patch
import logging

# Utiliser l'import absolu basé sur la structure du projet
from backend import config

# Supprimer les logs pendant les tests sauf si nécessaire
logging.disable(logging.CRITICAL)


class TestConfigLoading(unittest.TestCase):

    @patch.dict(
        os.environ, {"TEST_ENV": "1"}, clear=True
    )  # Désactive le chargement de .env
    def test_defaults_when_env_vars_missing(self):
        """Teste les valeurs par défaut quand les variables d'environnement sont absentes."""
        from backend.config import BINANCE_API_KEY, BINANCE_API_SECRET

        self.assertEqual(BINANCE_API_KEY, "YOUR_API_KEY_PLACEHOLDER")
        self.assertEqual(BINANCE_API_SECRET, "YOUR_SECRET_KEY_PLACEHOLDER")
        # La valeur par défaut pour USE_TESTNET est True si ENV_USE_TESTNET est absente ou vide
        # car os.getenv a "True" comme valeur par défaut dans config.py
        self.assertTrue(
            config.USE_TESTNET, "La valeur par défaut de USE_TESTNET devrait être True"
        )

    def test_loading_from_env_vars(self):
        """Teste le chargement correct depuis les variables d'environnement."""
        test_key = "test_api_key_123"
        test_secret = "test_api_secret_456"
        test_env = {
            "ENV_API_KEY": test_key,
            "ENV_API_SECRET": test_secret,
            "ENV_USE_TESTNET": "False",  # Tester une valeur non par défaut
        }
        # clear=True assure que seules nos variables de test sont visibles
        with patch.dict(os.environ, test_env, clear=True):
            importlib.reload(config)
            self.assertEqual(config.BINANCE_API_KEY, test_key)
            self.assertEqual(config.BINANCE_API_SECRET, test_secret)
            self.assertFalse(config.USE_TESTNET)

    def test_use_testnet_conversion(self):
        """Teste la conversion de la chaîne ENV_USE_TESTNET en booléen."""
        # Cas de test: chaîne d'entrée -> booléen attendu
        test_cases = {
            # Valeurs "vraies"
            "true": True,
            "True": True,
            "TRUE": True,
            "1": True,
            "t": True,
            "T": True,
            "yes": True,
            "Yes": True,
            "YES": True,
            "y": True,
            "Y": True,
            # Valeurs "fausses"
            "false": False,
            "False": False,
            "FALSE": False,
            "0": False,
            "f": False,
            "F": False,
            "no": False,
            "No": False,
            "NO": False,
            "n": False,
            "N": False,
            # Autres chaînes devraient être False
            "random string": False,
            " ": False,
            "": False,  # Chaîne vide devrait évaluer à False
            # La valeur par défaut si la variable manque est gérée dans test_defaults_when_env_vars_missing
        }
        for input_str, expected_bool in test_cases.items():
            # Utiliser subTest pour un meilleur rapport si un cas échoue
            with self.subTest(input_str=input_str, expected_bool=expected_bool):
                # Patch seulement ENV_USE_TESTNET, clear=True pour isoler
                with patch.dict(os.environ, {"ENV_USE_TESTNET": input_str}, clear=True):
                    importlib.reload(config)
                    self.assertEqual(
                        config.USE_TESTNET,
                        expected_bool,
                        f"Échec pour l'entrée : '{input_str}'",
                    )

    def test_hardcoded_defaults(self):
        """Teste que les autres valeurs par défaut codées en dur sont correctes."""
        # Recharger au cas où les tests précédents auraient laissé le module dans un état étrange
        # (bien que l'isolation par patch/reload devrait l'empêcher)
        # Utiliser un patch vide avec clear=True pour s'assurer qu'aucun env var n'interfère
        with patch.dict(os.environ, {}, clear=True):
            importlib.reload(config)

            # Général
            self.assertEqual(config.SYMBOL, "BTCUSDT")
            self.assertEqual(config.TIMEFRAME, "1m")
            self.assertEqual(
                config.STRATEGY_TYPE, "SCALPING"
            )  # Vérifier la valeur par défaut dans config.py

            # Risque/Capital Commun (% valeurs dans config.py)
            self.assertEqual(config.RISK_PER_TRADE, 1.0)
            self.assertEqual(config.CAPITAL_ALLOCATION, 20.0)
            self.assertEqual(config.STOP_LOSS_PERCENTAGE, 0.5)
            self.assertEqual(config.TAKE_PROFIT_1_PERCENTAGE, 1.0)
            self.assertEqual(config.TAKE_PROFIT_2_PERCENTAGE, 1.5)
            self.assertEqual(config.TRAILING_STOP_PERCENTAGE, 0.3)
            self.assertEqual(config.TIME_STOP_MINUTES, 15)
            self.assertEqual(config.ORDER_COOLDOWN_MS, 2000)

            # Scalping 1
            self.assertEqual(config.SCALPING_ORDER_TYPE, "LIMIT")
            self.assertEqual(config.SCALPING_LIMIT_TIF, "GTC")
            self.assertEqual(config.SCALPING_LIMIT_ORDER_TIMEOUT_MS, 5000)
            self.assertEqual(config.SCALPING_DEPTH_LEVELS, 5)
            self.assertEqual(config.SCALPING_DEPTH_SPEED, "1000ms")
            self.assertEqual(config.SCALPING_SPREAD_THRESHOLD, 0.0001)
            self.assertEqual(config.SCALPING_IMBALANCE_THRESHOLD, 1.5)
            self.assertEqual(config.SCALPING_EXIT_STRATEGIES, "ImbalanceExit")

            # Scalping 2
            self.assertEqual(config.SUPERTREND_ATR_PERIOD, 3)
            self.assertEqual(config.SUPERTREND_ATR_MULTIPLIER, 1.5)
            self.assertEqual(config.SCALPING_RSI_PERIOD, 7)
            self.assertEqual(config.STOCH_K_PERIOD, 14)
            self.assertEqual(config.STOCH_D_PERIOD, 3)
            self.assertEqual(config.STOCH_SMOOTH, 3)
            self.assertEqual(config.BB_PERIOD, 20)
            self.assertEqual(config.BB_STD, 0.2)
            self.assertEqual(config.VOLUME_MA_PERIOD, 20)
            self.assertEqual(config.SCALPING2_EXIT_STRATEGIES, "")

            # Swing
            self.assertEqual(config.EMA_SHORT_PERIOD, 9)
            self.assertEqual(config.EMA_LONG_PERIOD, 21)
            self.assertEqual(config.EMA_FILTER_PERIOD, 50)
            self.assertEqual(config.RSI_PERIOD, 14)
            self.assertEqual(config.RSI_OVERBOUGHT, 95)
            self.assertEqual(config.RSI_OVERSOLD, 5)
            self.assertEqual(config.VOLUME_AVG_PERIOD, 20)
            self.assertFalse(config.USE_EMA_FILTER)
            self.assertFalse(config.USE_VOLUME_CONFIRMATION)
            self.assertEqual(config.SWING_EXIT_STRATEGIES, "")

    def test_placeholder_key_detection(self):
        """Teste la condition qui vérifie les clés API placeholder (infère le log)."""
        test_env_key = {
            "ENV_API_KEY": "YOUR_API_KEY_PLACEHOLDER",
            "ENV_API_SECRET": "some_secret",  # Mélange placeholder et non-placeholder
        }
        with patch.dict(os.environ, test_env_key, clear=True):
            # On s'attend à ce que le log critique sur les placeholders soit déclenché ici
            # On ne peut pas facilement vérifier le log sans config plus complexe,
            # mais on vérifie que la valeur chargée est bien le placeholder.
            importlib.reload(config)
            self.assertEqual(config.BINANCE_API_KEY, "YOUR_API_KEY_PLACEHOLDER")
            self.assertEqual(config.BINANCE_API_SECRET, "some_secret")

        test_env_secret = {
            "ENV_API_KEY": "some_key",
            "ENV_API_SECRET": "YOUR_SECRET_KEY_PLACEHOLDER",
        }
        with patch.dict(os.environ, test_env_secret, clear=True):
            importlib.reload(config)
            self.assertEqual(config.BINANCE_API_KEY, "some_key")
            self.assertEqual(config.BINANCE_API_SECRET, "YOUR_SECRET_KEY_PLACEHOLDER")

    def test_empty_key_detection(self):
        """Teste la condition qui vérifie les clés API vides (infère le log)."""
        test_env_key = {
            "ENV_API_KEY": "",
            "ENV_API_SECRET": "some_secret",  # Mélange vide et non-vide
        }
        with patch.dict(os.environ, test_env_key, clear=True):
            # On s'attend à ce que le log critique sur les clés vides soit déclenché ici
            importlib.reload(config)
            self.assertEqual(config.BINANCE_API_KEY, "")
            self.assertEqual(config.BINANCE_API_SECRET, "some_secret")

        test_env_secret = {
            "ENV_API_KEY": "some_key",
            "ENV_API_SECRET": "",
        }
        with patch.dict(os.environ, test_env_secret, clear=True):
            importlib.reload(config)
            self.assertEqual(config.BINANCE_API_KEY, "some_key")
            self.assertEqual(config.BINANCE_API_SECRET, "")

        test_env_both_empty = {
            "ENV_API_KEY": "",
            "ENV_API_SECRET": "",
        }
        with patch.dict(os.environ, test_env_both_empty, clear=True):
            importlib.reload(config)
            self.assertEqual(config.BINANCE_API_KEY, "")
            self.assertEqual(config.BINANCE_API_SECRET, "")

    @patch.dict(
        os.environ, {"TEST_ENV": "1"}, clear=True
    )  # Désactive le chargement de .env
    def test_system_env_vars(self):
        """Teste si les variables d'environnement système interfèrent avec celles du fichier .env."""
        with patch.dict(
            os.environ, {}, clear=True
        ):  # Désactive toutes les variables d'environnement
            importlib.reload(config)
            self.assertEqual(config.BINANCE_API_KEY, "YOUR_API_KEY_PLACEHOLDER")
            self.assertEqual(config.BINANCE_API_SECRET, "YOUR_SECRET_KEY_PLACEHOLDER")

        # Ajoutez des variables d'environnement système simulées
        system_env = {
            "ENV_API_KEY": "system_api_key",
            "ENV_API_SECRET": "system_api_secret",
        }
        with patch.dict(os.environ, system_env, clear=True):
            importlib.reload(config)
            self.assertEqual(config.BINANCE_API_KEY, "system_api_key")
            self.assertEqual(config.BINANCE_API_SECRET, "system_api_secret")
            self.assertTrue(config.USE_TESTNET)  # Par défaut, USE_TESTNET est True


if __name__ == "__main__":
    # Réactiver les logs si on exécute le fichier de test directement pour débogage
    # logging.disable(logging.NOTSET)
    unittest.main()
