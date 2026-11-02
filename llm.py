"""Backend de l'assistant : moteur INTÉGRÉ (llama.cpp), Ollama (optionnel) ou API en ligne.

Modes : "embedded" (intégré, sans installation), "local" (Ollama), "online" (API),
"auto" (intégré -> Ollama -> API en ligne, le premier qui répond).
"""
import json
import os
import sys
import urllib.error
import urllib.request

MODEL_FILE = "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"
MODEL_URL = ("https://huggingface.co/bartowski/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/"
             + MODEL_FILE)
LABELS = {"embedded": "Moteur intégré", "local": "Ollama", "online": "API en ligne"}


class LLMError(Exception):
    """Erreur lisible à afficher à l'utilisateur."""


# ---------- emplacement du modèle intégré ----------
def app_dir():
    return os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "AIAssistantHybride")


def model_dirs():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return [os.path.join(base, "models"), os.path.join(app_dir(), "models")]


def find_model(cfg):
    """Chemin du fichier .gguf à utiliser, ou None."""
    p = (cfg.get("gguf_path") or "").strip()
    if p and os.path.isfile(p):
        return p
    for d in model_dirs():
        if not os.path.isdir(d):
            continue
        if os.path.isfile(os.path.join(d, MODEL_FILE)):
            return os.path.join(d, MODEL_FILE)
        files = sorted(f for f in os.listdir(d) if f.lower().endswith(".gguf"))
        if files:
            return os.path.join(d, files[0])
    return None


def download_model(cfg, progress=None, stop=None):
    """Télécharge le modèle (une seule fois, ~400 Mo) dans %APPDATA%\\AIAssistantHybride\\models."""
    dest_dir = os.path.join(app_dir(), "models")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, MODEL_FILE)
    part = dest + ".part"
    req = urllib.request.Request(cfg.get("model_url") or MODEL_URL,
                                 headers={"User-Agent": "AIAssistantHybride"})
    try:
        with urllib.request.urlopen(req, timeout=60) as res, open(part, "wb") as out:
            total = int(res.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if stop is not None and stop.is_set():
                    raise LLMError("Téléchargement annulé.")
                block = res.read(1024 * 1024)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if progress:
                    progress(done, total)
        if total and done < total:
            raise LLMError("Téléchargement incomplet : relance-le.")
        os.replace(part, dest)
        return dest
    except LLMError:
        _silent_remove(part)
        raise
    except (urllib.error.URLError, OSError) as e:
        _silent_remove(part)
        raise LLMError(f"Téléchargement impossible ({getattr(e, 'reason', e)}). "
                       f"Tu peux aussi placer un fichier .gguf dans : {dest_dir}")


def _silent_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ---------- moteur intégré ----------
_cache = {"key": None, "llm": None}


def _embedded(cfg, messages, stop):
    try:
        from llama_cpp import Llama
    except Exception as e:
        raise LLMError("Cet .exe a été compilé sans le moteur intégré (" + str(e) + "). Recompile avec la dernière version du projet, ou utilise le mode « online » / Ollama.")
    path = find_model(cfg)
    if not path:
        raise LLMError("Modèle intégré non installé : Paramètres → « Télécharger le modèle intégré » "
                       "(~400 Mo, une seule fois), ou place un fichier .gguf dans le dossier models.")
    n_ctx = int(cfg.get("num_ctx", 4096))
    key = (path, n_ctx)
    if _cache["key"] != key:
        _cache.update(key=None, llm=None)
        try:
            _cache["llm"] = Llama(model_path=path, n_ctx=n_ctx,
                                  n_threads=max(2, (os.cpu_count() or 4) // 2), verbose=False)
        except Exception as e:
            raise LLMError(f"Chargement du modèle impossible : {e}")
        _cache["key"] = key
    stream = None
    try:
        stream = _cache["llm"].create_chat_completion(messages=messages, stream=True)
        for part in stream:
            if stop is not None and stop.is_set():
                return
            text = (part["choices"][0].get("delta") or {}).get("content")
            if text:
                yield text
    except ValueError as e:
        raise LLMError("Texte trop long pour le contexte du modèle (" + str(e) + "). "
                       "Augmente « Contexte » dans Paramètres ou réduis les messages gardés.")
    finally:
        if stream is not None and hasattr(stream, "close"):
            stream.close()


# ---------- Ollama et API en ligne ----------
def _open(url, payload, headers, timeout):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
            detail = json.loads(body)
            if isinstance(detail.get("error"), dict):
                detail = detail["error"].get("message", body)
            else:
                detail = detail.get("error", body)
        except Exception:
            detail = e.reason
        raise LLMError(f"Erreur HTTP {e.code} : {detail}")
    except (urllib.error.URLError, OSError) as e:
        raise LLMError(f"Connexion impossible à {url} ({getattr(e, 'reason', e)})")


def _local(cfg, messages, stop):
    payload = {"model": cfg["local_model"], "messages": messages, "stream": True,
               "options": {"num_ctx": int(cfg.get("num_ctx", 4096))}}
    headers = {"Content-Type": "application/json"}
    with _open(cfg["local_url"], payload, headers, cfg.get("timeout", 300)) as res:
        for raw in res:
            if stop is not None and stop.is_set():
                return
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("error"):
                raise LLMError(str(obj["error"]))
            text = obj.get("message", {}).get("content", "")
            if text:
                yield text
            if obj.get("done"):
                return


def _online(cfg, messages, stop):
    if not cfg.get("api_key", "").strip():
        raise LLMError("Aucune clé API : renseigne-la dans Paramètres.")
    payload = {"model": cfg["online_model"], "messages": messages, "stream": True}
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + cfg["api_key"].strip(),
    }
    with _open(cfg["online_url"], payload, headers, cfg.get("timeout", 300)) as res:
        for raw in res:
            if stop is not None and stop.is_set():
                return
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            obj = json.loads(data)
            choices = obj.get("choices") or []
            if choices:
                text = (choices[0].get("delta") or {}).get("content")
                if text:
                    yield text


ENGINES = {"embedded": _embedded, "local": _local, "online": _online}


def chat_stream(cfg, messages, stop=None, notice=None):
    """Générateur de morceaux de texte.

    En mode "auto", essaie dans l'ordre : moteur intégré, Ollama, API en ligne.
    """
    mode = cfg.get("mode", "embedded")
    if mode in ENGINES:
        yield from ENGINES[mode](cfg, messages, stop)
        return
    errors = []
    for name in ("embedded", "local", "online"):
        started = False
        try:
            for chunk in ENGINES[name](cfg, messages, stop):
                started = True
                yield chunk
            return
        except LLMError as err:
            if started:
                raise
            errors.append(f"{LABELS[name]} : {err}")
            if notice:
                notice(f"[{LABELS[name]} indisponible : {err}]\n")
    raise LLMError("Aucun moteur disponible.\n" + "\n".join(errors))


def complete(cfg, messages, stop=None):
    """Version non progressive : renvoie la réponse complète."""
    return "".join(chat_stream(cfg, messages, stop)).strip()
