# AI Assistant Hybride v4 — moteur IA intégré

Le moteur d'IA (llama.cpp) est **dans l'application** : plus besoin d'installer Ollama.

## Modes du modèle (Paramètres)
- **Intégré** (par défaut) : 100 % hors ligne, rien à installer. Modèle Qwen2.5-0.5B (~400 Mo).
- **Ollama** : optionnel, si tu préfères un modèle plus gros déjà installé.
- **En ligne** : API compatible OpenAI (clé API requise).
- **Auto** : essaie intégré → Ollama → en ligne, le premier qui répond.

## Le modèle IA
- Compilation via **GitHub Actions** : l'artefact `AI_Assistant_Hybride_complet` contient l'EXE **et** le dossier `models` avec le modèle. Garde-les ensemble : tout marche sans Internet.
- Compilation locale (`build_exe.bat`) : le modèle est téléchargé au 1er lancement (bouton « Télécharger le modèle intégré »), ou place un fichier `.gguf` dans `models` à côté de l'EXE.
- Tu peux utiliser un autre modèle `.gguf` (champ « Fichier modèle .gguf »).

## Recherche approfondie
Menu sous la zone de discussion : **En ligne** (web : DuckDuckGo ou Tavily), **Hors ligne** (tes documents .txt .md .csv .docx .pdf), **Auto** (web, sinon documents). Synthèse avec sources [1], [2]…
Un petit modèle donne des synthèses modestes : pour de meilleurs résultats, utilise un modèle `.gguf` plus gros (ex. Qwen2.5-3B, si ta RAM le permet) ou le mode En ligne.

## Compiler
- **Sur ton PC** : Python **3.10 à 3.12** (pas 3.13+), double-clique `build_exe.bat` → `dist\AI_Assistant_Hybride.exe`.
- **Via GitHub** : pousse le dossier, onglet Actions → « Build EXE » → télécharge l'artefact.

## Processeur ancien (erreur 0xc000001d)
Le workflow GitHub compile le moteur **sans** instructions AVX/AVX2 : il tourne sur tous les PC, mais plus lentement. `build_exe.bat` (moteur précompilé, qui exige AVX2) convient seulement aux PC récents ; en cas d'erreur 0xc000001d, utilise GitHub Actions.

## Limites
Historique et clés API stockés en clair dans `%APPDATA%\AIAssistantHybride\`. L'EXE est volumineux (le moteur est embarqué).
