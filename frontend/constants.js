// Utiliser 'localhost' si hostname est vide (cas file:///)
const hostname = window.location.hostname || 'localhost';

export const API_BASE_URL = `http://${hostname}:5000`;
export const WS_URL = `ws://${hostname}:5000/ws_logs`;
