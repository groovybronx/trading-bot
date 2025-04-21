# /Users/davidmichels/Desktop/trading-bot/backend/app.py
import logging
import json
import os
import queue
import time
import threading
from flask import Flask, render_template, jsonify, request # Added request for client IP
from flask_cors import CORS
from flask_sock import Sock, ConnectionClosed # Import ConnectionClosed

# Load .env before other imports that might need it
from dotenv import load_dotenv
load_dotenv()
print(">>> app.py: load_dotenv() executed.")

import config # Loads config based on .env
from logging_config import setup_logging, log_queue, WebSocketLogHandler
from api_routes import api_bp
# Import the instance directly
from state_manager import state_manager
# config_manager is likely used implicitly by state_manager/bot_core, no direct import needed here usually
# import config_manager
# websocket_handlers are used by bot_core, no direct import needed here
# import websocket_handlers
from websocket_utils import (
    connected_clients,
    broadcast_state_update,
    broadcast_order_history_update,
)

# --- Logging Setup ---
# Create the handler instance first
ws_log_handler = WebSocketLogHandler(connected_clients)
# Setup logging, passing the handler and queue
log_listener = setup_logging(log_queue, ws_log_handler)
# Get the root logger
logger = logging.getLogger()

# --- Flask App Setup ---
app = Flask(__name__,
            static_folder="../frontend", # Serve static files from frontend folder
            template_folder="../frontend") # Serve index.html from frontend folder
CORS(app) # Enable Cross-Origin Resource Sharing
sock = Sock(app) # Initialize Flask-Sock
app.register_blueprint(api_bp, url_prefix="/api") # Register API routes

# --- WebSocket Route for Logs & Control ---
@sock.route("/ws_logs")
def handle_websocket(ws):
    """Handles WebSocket connections for log streaming and potentially control."""
    # Use request context to get IP, fallback if not available (e.g., during tests)
    client_ip = request.remote_addr or "Unknown"
    logger.info(f"WebSocket client connected: {client_ip}")
    connected_clients.add(ws)
    ws_log_handler.clients = connected_clients # Update handler's client list

    try:
        # Send initial connection confirmation and current state/history
        ws.send(json.dumps({"type": "info", "message": "Connected to backend WebSocket."}))
        broadcast_state_update()
        broadcast_order_history_update()
    except ConnectionClosed:
         logger.warning(f"WebSocket client {client_ip} disconnected immediately after connect.")
         if ws in connected_clients: connected_clients.remove(ws)
         ws_log_handler.clients = connected_clients
         return # Exit handler for this client
    except Exception as e:
        logger.warning(f"Error sending initial message/state to client {client_ip}: {e}")
        # Attempt to remove client, but continue if possible? Or just exit? Let's exit.
        if ws in connected_clients: connected_clients.remove(ws)
        ws_log_handler.clients = connected_clients
        return

    # Main loop to keep connection alive and potentially receive commands
    try:
        while True:
            # Use receive with a timeout to allow periodic checks/pings
            message = ws.receive(timeout=30) # Check every 30 seconds

            if message is not None:
                # Handle incoming messages if implementing client-side controls later
                logger.debug(f"Received WS message from {client_ip}: {message}")
                # Example: parse message, trigger actions
                # try:
                #     data = json.loads(message)
                #     command = data.get('command')
                #     if command == 'start_bot':
                #         # Call bot_core.start_bot_core() etc.
                # except json.JSONDecodeError:
                #     logger.warning(f"Invalid JSON received from {client_ip}: {message}")
            else:
                # Timeout occurred, send a ping to check connection
                try:
                    # logger.debug(f"Sending ping to client {client_ip}") # Optional: can be noisy
                    ws.send(json.dumps({"type": "ping"}))
                except ConnectionClosed:
                    logger.info(f"WebSocket client {client_ip} disconnected (ping failed).")
                    break # Exit loop if ping fails
                except Exception as e:
                    logger.warning(f"Error sending ping to client {client_ip}: {e}")
                    # Consider breaking if ping error persists
                    break

    except ConnectionClosed as e:
         # Log specific close codes if available using getattr for safety
         # --- FIX 1: Use getattr for code and reason ---
         close_reason = getattr(e, 'reason', 'No reason given')
         close_code = getattr(e, 'code', 'N/A')
         logger.info(f"WebSocket client {client_ip} disconnected: {close_reason} ({close_code})")
         # --- END FIX 1 ---
    except Exception as e:
        # Catch other potential errors during receive/processing
        logger.error(f"WebSocket error for client {client_ip}: {type(e).__name__} - {e}", exc_info=True)
    finally:
        # Ensure client is removed from the set on any exit path
        logger.info(f"Cleaning up WebSocket connection for: {client_ip}.")
        if ws in connected_clients:
            connected_clients.remove(ws)
        ws_log_handler.clients = connected_clients # Update handler list


# --- Basic HTTP Route ---
@app.route("/")
def index():
    """Serves the main frontend page."""
    # Renders index.html from the template_folder
    return render_template("index.html")

# --- Main Execution ---
if __name__ == "__main__":
    logger.info("Starting Flask server...")
    try:
        # Use development server for testing; switch to production server (like gunicorn/waitress) later
        # debug=False and use_reloader=False are important for stability with threads
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        logger.info("Shutdown requested via Ctrl+C.")
        # Add cleanup for bot_core if it was running?
        # bot_core.stop_bot_core() # Maybe call this? Depends on desired shutdown behavior.
    except Exception as e:
         logger.critical(f"Flask server failed to start or run: {e}", exc_info=True)
    finally:
        # Ensure log listener thread stops cleanly
        # --- FIX 2: Remove is_alive() check ---
        if log_listener:
        # --- END FIX 2 ---
            logger.info("Stopping log listener...")
            log_listener.stop() # Uses the method from logging_config
            logger.info("Log listener stopped.")
        logger.info("Flask server shut down.")

