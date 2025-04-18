# /Users/davidmichels/Desktop/trading-bot/backend/logging_config.py
import logging
import queue

# Queue pour envoyer les logs au frontend via SSE
log_queue = queue.Queue()

class QueueHandler(logging.Handler):
    """Envoie les logs (INFO et plus) à une queue pour le streaming SSE."""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        if record.levelno >= logging.INFO:
            log_entry = self.format(record)
            try:
                self.log_queue.put_nowait(log_entry)
            except queue.Full:
                # Gérer le cas où la queue est pleine (rare, mais possible)
                # Option: ignorer, logger une erreur, etc.
                print(f"WARNING: Log queue is full. Log message dropped: {log_entry}")


def setup_logging(log_level=logging.INFO):
    """Configure le logging global."""
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # Handler pour la console
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(log_formatter)

    # Handler pour la queue SSE
    queue_handler = QueueHandler(log_queue)
    queue_handler.setFormatter(log_formatter)

    # Configurer le logger racine
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Vider les handlers existants pour éviter les doublons si setup_logging est appelé plusieurs fois
    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(stream_handler)
    logger.addHandler(queue_handler)

    # Réduire la verbosité de certains loggers tiers si nécessaire
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    logger.info("Configuration du logging terminée.")

# Exporter la queue pour que les autres modules puissent l'utiliser (notamment api_routes)
__all__ = ['log_queue', 'setup_logging']
