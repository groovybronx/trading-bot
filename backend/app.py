# /Users/davidmichels/Desktop/trading-bot/backend/app.py
import logging
from flask import Flask
from flask_cors import CORS

# Importer la configuration du logging et la fonction setup
from logging_config import setup_logging
# Importer le Blueprint des routes API
from api_routes import api_bp
# Optionnel: Importer d'autres modules si une initialisation globale est nécessaire au démarrage
# import binance_client_wrapper

# Configurer le logging dès le début
setup_logging(log_level=logging.INFO) # Ou DEBUG
logger = logging.getLogger()

# Créer l'application Flask
app = Flask(__name__)

# Configurer CORS (Cross-Origin Resource Sharing) pour autoriser les requêtes du frontend
CORS(app, resources={r"/*": {"origins": "*"}}) # Ajuster les origines pour la production

# Enregistrer le Blueprint contenant les routes API
app.register_blueprint(api_bp, url_prefix='/') # Ou '/api' si vous préférez préfixer

# Route simple pour vérifier que l'API est en ligne
@app.route('/ping')
def ping():
    return "pong"

# --- Démarrage Application Flask ---
if __name__ == "__main__":
    logger.info("Démarrage de l'API Flask du Bot...")
    # Utiliser 'threaded=True' pour le dev server Flask intégré.
    # Pour la production, utiliser un serveur WSGI comme Gunicorn ou uWSGI.
    # debug=False et use_reloader=False sont importants pour éviter les redémarrages intempestifs
    # qui pourraient interférer avec les threads du bot.
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)

