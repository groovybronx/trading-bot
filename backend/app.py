# /Users/davidmichels/Desktop/trading-bot/backend/app.py
import logging
import json
import os
import queue
import time
import threading
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from flask_sock import Sock, ConnectionClosed

from dotenv import load_dotenv
load_dotenv()
print(">>> app.py: load_dotenv() executed.")

import config  # Importer config pour les variables d'environnement
# Importer connected_clients pour l'utiliser dans la route WS
from utils.websocket_utils import connected_clients # Importer le set partagé
from logging_config import setup_logging, log_queue # Importer setup_logging et log_queue
from api_routes import api_bp
from manager.state_manager import state_manager
from utils.websocket_utils import (
    broadcast_state_update,
    # broadcast_order_history_update, # Déjà inclus dans broadcast_state_update
)
import bot_core # Importer pour arrêt potentiel

# --- Logging Setup ---
# Configurer le logging (ne prend plus connected_clients en argument)
log_listener = setup_logging(log_queue)
logger = logging.getLogger() # Obtenir le logger root configuré

# --- Flask App Setup ---
app = Flask(__name__, static_folder="../frontend", template_folder="../frontend")
CORS(app)
sock = Sock(app)
app.register_blueprint(api_bp, url_prefix="/api")

# --- WebSocket Route ---
@sock.route("/ws_logs")
def handle_websocket(ws):
    """Handles WebSocket connections for log streaming and state updates."""
    client_ip = request.remote_addr or "Unknown"
    logger.info(f"WebSocket client connected: {client_ip}")
    connected_clients.add(ws) # Ajouter au set partagé

    try:
        # Envoyer confirmation et état initial
        ws.send(json.dumps({"type": "info", "message": "Connected to backend WebSocket."}))
        broadcast_state_update() # Envoyer état actuel (inclut config, ticker, historique)
    except ConnectionClosed:
         logger.warning(f"WebSocket client {client_ip} disconnected immediately.")
         if ws in connected_clients: connected_clients.remove(ws)
         return
    except Exception as e:
        logger.warning(f"Error sending initial message/state to {client_ip}: {e}")
        if ws in connected_clients: connected_clients.remove(ws)
        return

    # Boucle pour maintenir la connexion et recevoir potentiellement des commandes
    try:
        while True:
            message = ws.receive(timeout=30) # Timeout pour ping périodique
            if message is not None:
                logger.debug(f"Received WS message from {client_ip}: {message}")
                # Traiter commandes futures ici...
            else:
                # Timeout -> Envoyer ping
                try:
                    ws.send(json.dumps({"type": "ping"}))
                except ConnectionClosed:
                    logger.info(f"WebSocket client {client_ip} disconnected (ping failed).")
                    break
                except Exception as e:
                    logger.warning(f"Error sending ping to {client_ip}: {e}")
                    break # Sortir si erreur ping
    except ConnectionClosed as e:
         close_reason = getattr(e, 'reason', 'No reason')
         close_code = getattr(e, 'code', 'N/A')
         logger.info(f"WebSocket client {client_ip} disconnected: {close_reason} ({close_code})")
    except Exception as e:
        logger.error(f"WebSocket error for client {client_ip}: {e}", exc_info=True)
    finally:
        logger.info(f"Cleaning up WebSocket connection for: {client_ip}.")
        if ws in connected_clients:
            connected_clients.remove(ws) # Assurer suppression du set

# --- Basic HTTP Route ---
@app.route("/")
def index():
    """Serves the main frontend page."""
    return render_template("index.html")

# --- Arrêt Propre ---
def shutdown_server():
    logger.info("Shutdown initiated by signal...")
    # Arrêter le bot core proprement s'il tourne
    if state_manager.get_state("status") not in ["Arrêté", "STOPPED", "ERROR"]:
         logger.info("Attempting to stop bot core...")
         try:
              bot_core.stop_bot_core()
         except Exception as e:
              logger.error(f"Error stopping bot core during shutdown: {e}")

    # Arrêter le listener de logs
    if log_listener:
        logger.info("Stopping log listener...")
        log_listener.stop()
        logger.info("Log listener stopped.")

    # Tenter de fermer les WebSockets restants (peut être difficile)
    logger.info(f"Closing remaining {len(connected_clients)} WebSocket connections...")
    clients_copy = list(connected_clients)
    for ws in clients_copy:
        try:
            ws.close(reason='Server shutting down')
        except: pass # Ignorer erreurs à ce stade
    logger.info("WebSocket connections closed.")

    # Demander l'arrêt de Flask (nécessite un contexte de requête ou une astuce)
    # func = request.environ.get('werkzeug.server.shutdown')
    # if func is None:
    #     logger.warning('Not running with the Werkzeug Server, cannot shutdown programmatically.')
    # else:
    #     func()
    # logger.info("Flask server shutdown requested.") # Ne sera peut-être pas loggué

# --- Main Execution ---
if __name__ == "__main__":
    logger.info("Starting Flask server...")
    try:
        # Utiliser le serveur de développement Flask pour tests
        # Pour la production, utiliser Gunicorn ou Waitress
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        logger.info("Shutdown requested via Ctrl+C.")
    except Exception as e:
         logger.critical(f"Flask server failed to start or run: {e}", exc_info=True)
    finally:
        # Exécuter le nettoyage ici aussi, au cas où la boucle principale se termine autrement
        shutdown_server()
        logger.info("Flask server shut down.")
