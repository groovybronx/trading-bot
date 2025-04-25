// Utiliser 'localhost' si hostname est vide (cas file:///)
const hostname = 'localhost'; // Forcer localhost temporairement pour éviter les problèmes

export const API_BASE_URL = `http://${hostname}:5000`;
export const WS_URL = `ws://${hostname}:5000/ws_logs`;
