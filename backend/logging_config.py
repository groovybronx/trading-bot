# /Users/davidmichels/Desktop/trading-bot/backend/logging_config.py
import logging
import queue
import json
from logging.handlers import QueueHandler, QueueListener
import sys

# from typing import Set # Plus nécessaire

# Import broadcast_message depuis websocket_utils
from utils.websocket_utils import (
    broadcast_message,
)  # connected_clients n'est plus nécessaire ici

log_queue = queue.Queue(-1)  # Queue de logs partagée


class WebSocketLogHandler(logging.Handler):
    """Handler qui envoie les logs formatés via websocket_utils.broadcast_message."""

    def emit(self, record):
        try:
            log_entry = self.format(record)
            level_name = record.levelname.lower()
            # Assurer un type valide pour le frontend
            if level_name not in ["debug", "info", "warning", "error", "critical"]:
                level_name = "log"

            # Créer le dictionnaire du message
            message_dict = {"type": level_name, "message": log_entry}

            # Utiliser broadcast_message pour envoyer à tous les clients
            # broadcast_message gère la sérialisation JSON et les déconnexions
            broadcast_message(message_dict)

        except Exception:
            # Gérer les erreurs potentielles lors du formatage ou de l'appel broadcast
            self.handleError(record)


def setup_logging(log_queue: queue.Queue):  # Ne prend plus ws_clients_set
    """Configure le système de logging."""
    log_format = "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s"  # Format plus détaillé
    log_level = logging.WARNING  # Niveau global (était INFO)
    formatter = logging.Formatter(log_format)

    # Configurer le logger root
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        logger = logging.getLogger(__name__)
        # logger.warning("Nettoyage des handlers pré-existants du root logger.")
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            handler.close()
    root_logger.setLevel(log_level)

    # --- Handlers ---
    # 1. Handler Console (toujours utile pour le debug serveur)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    # console_handler.setLevel(logging.INFO) # Niveau spécifique pour console si souhaité
    root_logger.addHandler(console_handler)  # Ajouter directement au root

    # 2. Handler vers la Queue (pour découplage)
    queue_handler = QueueHandler(log_queue)
    # Pas besoin de setLevel ici, le root logger filtre déjà
    root_logger.addHandler(queue_handler)

    # --- Listener ---
    # Le listener écoute la queue et utilise le WebSocketLogHandler
    # WebSocketLogHandler utilise maintenant broadcast_message directement
    websocket_handler_instance = WebSocketLogHandler()  # Plus besoin de passer le set
    websocket_handler_instance.setFormatter(
        formatter
    )  # Appliquer le formateur au handler WS

    # Créer le listener avec SEULEMENT le handler WebSocket
    listener = QueueListener(
        log_queue, websocket_handler_instance, respect_handler_level=True
    )

    # --- Configurer niveaux spécifiques pour certains modules ---
    # (Optionnel, car le root logger filtre déjà à INFO)
    # logging.getLogger('db').setLevel(logging.INFO)
    # logging.getLogger('websocket_handlers').setLevel(logging.INFO)
    # logging.getLogger('bot_core').setLevel(logging.INFO)
    # logging.getLogger('manager').setLevel(logging.INFO) # Pour state_manager, config_manager, order_manager
    # logging.getLogger('binance_client_wrapper').setLevel(logging.INFO)
    logging.getLogger('werkzeug').setLevel(logging.WARNING) # Réduire verbosité Flask/Werkzeug

    # Démarrer le listener
    listener.start()
    logger = logging.getLogger(__name__)
    logger.info("Logging configuré (Root Level: INFO, Console + WebSocket via Queue).")

    return listener  # Retourner le listener pour pouvoir l'arrêter proprement
