# /Users/davidmichels/Desktop/trading-bot/backend/logging_config.py
import logging
import queue
import json
from logging.handlers import QueueHandler, QueueListener
import sys

log_queue = queue.Queue(-1)  # Queue de logs

# --- MODIFIÉ: WebSocketLogHandler ---
class WebSocketLogHandler(logging.Handler):
    """Handler qui envoie les logs aux clients WebSocket connectés."""
    def __init__(self, clients_set):
        super().__init__()
        self.clients = clients_set # Utiliser le set passé en argument

    def emit(self, record):
        log_entry = self.format(record)
        # Déterminer le niveau pour le message JSON
        level_name = record.levelname.lower()
        if level_name not in ['debug', 'info', 'warning', 'error', 'critical']:
            level_name = 'log' # Fallback

        message = json.dumps({"type": level_name, "message": log_entry})

        # Copier pour éviter RuntimeError si le set change pendant l'itération
        disconnected_clients = set()
        current_clients = list(self.clients) # Utiliser la référence self.clients

        for ws in current_clients:
            try:
                ws.send(message)
            except Exception:
                # Marquer pour suppression si l'envoi échoue
                disconnected_clients.add(ws)

        # Nettoyer les clients déconnectés du set principal (partagé avec app.py)
        for ws in disconnected_clients:
             if ws in self.clients:
                  self.clients.remove(ws)


def setup_logging(log_queue, ws_log_handler): # Accepter le handler en argument
    """Configure le système de logging."""
    log_format = '%(asctime)s - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s'
    log_level = logging.DEBUG # Mettre à DEBUG pour voir tous les messages
    formatter = logging.Formatter(log_format)

    logging.basicConfig(level=log_level, format=log_format)

    # --- Configuration du logging vers la queue (pour WebSocket) ---
    queue_handler = QueueHandler(log_queue)
    # queue_handler.setLevel(logging.DEBUG) # Niveau pour les websockets

    
    
    # Attacher les handlers au logger root
    root_logger = logging.getLogger()
    root_logger.addHandler(queue_handler)
    if root_logger.hasHandlers():
        # logging.warning("Nettoyage des handlers pré-existants du root logger.")
        for handler in root_logger.handlers[:]: # Itérer sur une copie
            root_logger.removeHandler(handler)
            handler.close() # Fermer le handler proprement
    
     # --- Créer les handlers nécessaires ---
    # Handler Console
    console_handler = logging.StreamHandler(sys.stdout) # Explicitement vers stdout
    console_handler.setFormatter(formatter)
    # console_handler.setLevel(logging.INFO) # Optionnel: Niveau spécifique pour console

    # Handler vers la Queue (pour WebSocket)
    queue_handler = QueueHandler(log_queue)
    # Le niveau effectif sera celui du root logger (DEBUG)

    # --- Créer le Listener UNIQUEMENT pour le WebSocket Handler ---
    # Il consomme la queue et envoie seulement au ws_log_handler
    listener = QueueListener(log_queue, ws_log_handler, respect_handler_level=True)


    # Ne pas ajouter console_handler directement au root si on utilise QueueListener
    # root_logger.addHandler(console_handler)

    # Démarrer le listener
    listener.start()
    logging.info("Logging configuré (Console + WebSocket via Queue).")

    return listener # Retourner le listener pour pouvoir l'arrêter proprement
