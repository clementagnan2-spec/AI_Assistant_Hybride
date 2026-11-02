# AI Assistant Hybride — projet de démarrage

Ce ZIP fournit une petite interface Windows avec deux modes sélectionnables.

## Mode hors ligne
1. Installe Ollama pour Windows : https://ollama.com/download
2. Dans un terminal, exécute : `ollama pull qwen2.5:0.5b`
3. Laisse Ollama démarré et conserve le mode `local` dans Paramètres.

Avec 4 Go de RAM, ferme les autres applications. Le modèle local sera modeste et pourra répondre lentement.

## Mode en ligne
Dans Paramètres, choisis `online`, puis renseigne l'URL, le nom du modèle et ta clé API auprès d'un fournisseur compatible OpenAI Chat Completions. Internet et une clé valide sont nécessaires. Des frais peuvent s'appliquer selon le fournisseur.

## Compiler en EXE
Prérequis : Python 3.10+ sur Windows.
1. Décompresse le ZIP.
2. Double-clique sur `build_exe.bat`.
3. Le résultat sera `dist\\AI_Assistant_Hybride.exe`.

## Limites de cette première version
Ce n'est pas une IA préinstallée : aucun modèle ni aucune clé API ne sont inclus. Le changement de mode est manuel. Pas encore de recherche web, analyse de documents, chiffrement de l'historique ou fonctions vocales. L'historique est stocké dans `%APPDATA%\\AIAssistantHybride\\history.json` en clair. Ne l'utilise pas pour des données sensibles.
