# ~/.zshrc

# --- Initialisation du système de complétion Zsh ---
# Charger la fonction compinit
autoload -Uz compinit

# --- Configuration des complétions Docker Desktop ---
# Ajouter le chemin des complétions Docker à fpath
fpath=(~/.docker/completions $fpath)

# --- Initialiser le système de complétion ---
# Doit être appelé après toutes les modifications de fpath
compinit

# --- Fin de la configuration Zsh ---
# Vous pouvez ajouter vos alias, exports PATH, etc. ici par la suite
