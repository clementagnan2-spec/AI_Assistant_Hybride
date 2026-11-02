import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import llm
import research

# En mode --windowed (.exe sans console), stdout/stderr valent None : le moteur llama.cpp plante sinon.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w"))

APP_DIR = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "AIAssistantHybride")
os.makedirs(APP_DIR, exist_ok=True)
CFG_FILE = os.path.join(APP_DIR, "config.json")
HIST_FILE = os.path.join(APP_DIR, "history.json")

DEFAULT = {
    "mode": "embedded",  # embedded | local (Ollama) | online | auto
    "gguf_path": "",
    "cfg_version": 4,
    "local_url": "http://localhost:11434/api/chat",
    "local_model": "qwen2.5:0.5b",
    "online_url": "https://api.openai.com/v1/chat/completions",
    "online_model": "gpt-4o-mini",
    "api_key": "",
    "system_prompt": "Tu es un assistant utile. Réponds en français, de façon claire et concise.",
    "max_history": 20,
    "timeout": 300,
    "num_ctx": 4096,
    "research_mode": "off",  # off | web | local | auto
    "docs_folder": "",
    "search_key": "",
    "research_rounds": 2,
    "research_queries": 3,
    "ctx_chars": 9000,
}
MODE_LABELS = {
    "embedded": "Intégré (sans installation)",
    "local": "Hors ligne (Ollama)",
    "online": "En ligne (API)",
    "auto": "Auto (intégré, Ollama, API)",
}


RESEARCH_LABELS = {
    "off": "Désactivée (discussion simple)",
    "web": "En ligne (recherche web)",
    "local": "Hors ligne (mes documents)",
    "auto": "Auto (web, sinon documents)",
}


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class App:
    def __init__(self, root):
        self.root = root
        root.title("AI Assistant Hybride")
        root.geometry("900x650")
        cfg = load_json(CFG_FILE, {})
        self.cfg = {**DEFAULT, **(cfg if isinstance(cfg, dict) else {})}
        if self.cfg.get("cfg_version", 0) < 4:  # anciennes versions : Ollama seul -> mode auto
            if self.cfg.get("mode") == "local":
                self.cfg["mode"] = "auto"
            self.cfg["cfg_version"] = 4
            save_json(CFG_FILE, self.cfg)
        hist = load_json(HIST_FILE, [])
        self.history = hist if isinstance(hist, list) else []
        self.q = queue.Queue()
        self.stop = threading.Event()
        self.busy = False
        self.reply = ""

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="AI Assistant Hybride", font=("Segoe UI", 16, "bold")).pack(side="left")
        self.mode_label = ttk.Label(top)
        self.mode_label.pack(side="right", padx=8)
        ttk.Button(top, text="Paramètres", command=self.open_settings).pack(side="right")
        ttk.Button(top, text="Nouvelle conversation", command=self.new_chat).pack(side="right", padx=6)

        frame = ttk.Frame(root)
        frame.pack(fill="both", expand=True, padx=10, pady=6)
        self.out = tk.Text(frame, wrap="word", state="disabled", font=("Segoe UI", 11), padx=8, pady=8)
        scroll = ttk.Scrollbar(frame, command=self.out.yview)
        self.out.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.out.pack(side="left", fill="both", expand=True)
        self.out.tag_configure("who_user", font=("Segoe UI", 10, "bold"), foreground="#1a5fb4")
        self.out.tag_configure("who_ai", font=("Segoe UI", 10, "bold"), foreground="#26a269")
        self.out.tag_configure("notice", foreground="#a51d2d")

        rbar = ttk.Frame(root, padding=(10, 0))
        rbar.pack(fill="x")
        ttk.Label(rbar, text="Recherche approfondie :").pack(side="left")
        self.research_var = tk.StringVar(value=RESEARCH_LABELS.get(self.cfg["research_mode"], RESEARCH_LABELS["off"]))
        box = ttk.Combobox(rbar, textvariable=self.research_var, values=list(RESEARCH_LABELS.values()),
                           state="readonly", width=34)
        box.pack(side="left", padx=6)
        box.bind("<<ComboboxSelected>>", self.on_research_change)

        bottom = ttk.Frame(root, padding=10)
        bottom.pack(fill="x")
        self.entry = tk.Text(bottom, height=3, font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self.on_enter)
        btns = ttk.Frame(bottom)
        btns.pack(side="left", padx=8)
        self.send_btn = ttk.Button(btns, text="Envoyer", command=self.send)
        self.send_btn.pack(fill="x")
        self.stop_btn = ttk.Button(btns, text="Arrêter", command=self.stop.set, state="disabled")
        self.stop_btn.pack(fill="x", pady=(4, 0))

        self.status = ttk.Label(root, text="Prêt (Entrée = envoyer, Maj+Entrée = retour à la ligne)")
        self.status.pack(anchor="w", padx=12, pady=5)

        for m in self.history:
            self.show("Vous" if m["role"] == "user" else "IA", m["content"])
        self.update_mode()
        self.root.after(40, self.poll)

    # ---------- affichage ----------
    def update_mode(self):
        self.mode_label.config(text="Mode : " + MODE_LABELS.get(self.cfg["mode"], self.cfg["mode"]))

    def append(self, text, tag=None):
        self.out.config(state="normal")
        self.out.insert("end", text, tag)
        self.out.see("end")
        self.out.config(state="disabled")

    def show(self, who, msg):
        self.append(who + "\n", "who_user" if who == "Vous" else "who_ai")
        self.append(msg + "\n\n")

    def on_research_change(self, _event=None):
        for key, label in RESEARCH_LABELS.items():
            if label == self.research_var.get():
                self.cfg["research_mode"] = key
        save_json(CFG_FILE, self.cfg)

    # ---------- envoi ----------
    def on_enter(self, event):
        if event.state & 0x1:  # Maj+Entrée : saut de ligne
            return None
        self.send()
        return "break"

    def ensure_model(self):
        """Mode intégré : propose de télécharger le modèle s'il manque."""
        if self.cfg["mode"] != "embedded" or llm.find_model(self.cfg):
            return True
        if messagebox.askyesno(
                "Modèle intégré",
                "Le modèle d'IA intégré n'est pas encore installé.\n\n"
                "Téléchargement unique d'environ 400 Mo (Internet requis). Le télécharger maintenant ?"):
            self.start_download()
        return False

    def start_download(self):
        if self.busy:
            return
        self.set_busy(True)
        self.stop.clear()

        def run():
            try:
                def prog(done, total):
                    pct = f" {done * 100 // total} %" if total else f" {done // 1048576} Mo"
                    self.q.put(("status", "Téléchargement du modèle…" + pct))
                llm.download_model(self.cfg, prog, self.stop)
                self.q.put(("dl_done", "Modèle installé. Tu peux poser tes questions."))
            except Exception as e:
                self.q.put(("error", str(e)))
        threading.Thread(target=run, daemon=True).start()

    def send(self):
        if self.busy or not self.ensure_model():
            return
        text = self.entry.get("1.0", "end").strip()
        if not text:
            return
        self.entry.delete("1.0", "end")
        self.history.append({"role": "user", "content": text})
        save_json(HIST_FILE, self.history)
        self.show("Vous", text)
        self.append("IA\n", "who_ai")
        self.set_busy(True)
        self.reply = ""
        self.stop.clear()
        sys_prompt = self.cfg.get("system_prompt", "").strip()
        msgs = ([{"role": "system", "content": sys_prompt}] if sys_prompt else []) + \
            self.history[-int(self.cfg.get("max_history", 20)):]
        threading.Thread(target=self.worker, args=(dict(self.cfg), msgs, text), daemon=True).start()

    def worker(self, cfg, msgs, question):
        try:
            notice = lambda t: self.q.put(("notice", t))
            if cfg.get("research_mode", "off") != "off":
                gen = research.deep_research(cfg, question, self.stop,
                                             lambda t: self.q.put(("status", t)), notice)
            else:
                gen = llm.chat_stream(cfg, msgs, self.stop, notice)
            for chunk in gen:
                self.q.put(("chunk", chunk))
            self.q.put(("done", None))
        except Exception as e:
            self.q.put(("error", str(e)))

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "chunk":
                    self.reply += val
                    self.append(val)
                elif kind == "dl_done":
                    self.set_busy(False)
                    messagebox.showinfo("Modèle intégré", val)
                elif kind == "status":
                    self.status.config(text=val)
                elif kind == "notice":
                    self.append(val, "notice")
                elif kind == "done":
                    self.finish()
                elif kind == "error":
                    self.append("Erreur : " + val, "notice")
                    self.finish()
        except queue.Empty:
            pass
        self.root.after(40, self.poll)

    def finish(self):
        self.append("\n\n")
        if self.reply.strip():
            self.history.append({"role": "assistant", "content": self.reply})
            save_json(HIST_FILE, self.history)
        self.set_busy(False)

    def set_busy(self, busy):
        self.busy = busy
        self.send_btn.config(state="disabled" if busy else "normal")
        self.stop_btn.config(state="normal" if busy else "disabled")
        self.status.config(text="Réponse en cours…" if busy else "Prêt")

    def new_chat(self):
        if self.busy:
            return
        if self.history and not messagebox.askyesno("Nouvelle conversation", "Effacer l'historique actuel ?"):
            return
        self.history = []
        save_json(HIST_FILE, self.history)
        self.out.config(state="normal")
        self.out.delete("1.0", "end")
        self.out.config(state="disabled")

    # ---------- paramètres ----------
    def open_settings(self):
        w = tk.Toplevel(self.root)
        w.title("Paramètres")
        w.geometry("800x790")
        f = ttk.Frame(w, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        vars_ = {}

        ttk.Label(f, text="Mode du modèle").grid(row=0, column=0, sticky="w", pady=5)
        vars_["mode"] = tk.StringVar(value=self.cfg["mode"])
        ttk.Combobox(f, textvariable=vars_["mode"], values=list(MODE_LABELS), state="readonly").grid(
            row=0, column=1, sticky="w")

        fields = [
            ("gguf_path", "Fichier modèle .gguf (optionnel)"),
            ("local_url", "URL Ollama (optionnel)"), ("local_model", "Modèle Ollama"),
            ("online_url", "URL API en ligne"), ("online_model", "Modèle en ligne"),
            ("api_key", "Clé API du modèle"),
            ("docs_folder", "Dossier de documents (recherche hors ligne)"),
            ("search_key", "Clé Tavily (optionnel, sinon DuckDuckGo)"),
            ("research_rounds", "Tours de recherche (1 à 3)"),
            ("research_queries", "Requêtes par tour (1 à 6)"),
            ("num_ctx", "Contexte Ollama (tokens)"),
            ("max_history", "Messages gardés en contexte"),
        ]
        for i, (k, label) in enumerate(fields, start=1):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=5)
            vars_[k] = tk.StringVar(value=str(self.cfg.get(k, "")))
            ttk.Entry(f, textvariable=vars_[k], width=50,
                      show="*" if k in ("api_key", "search_key") else "").grid(row=i, column=1, sticky="ew")
            if k == "gguf_path":
                def browse_model(var=vars_[k]):
                    p = filedialog.askopenfilename(parent=w, title="Modèle .gguf",
                                                   filetypes=[("Modèle GGUF", "*.gguf")])
                    if p:
                        var.set(p)
                ttk.Button(f, text="Parcourir…", command=browse_model).grid(row=i, column=2, padx=6)
            if k == "docs_folder":
                def browse(var=vars_[k]):
                    d = filedialog.askdirectory(parent=w, title="Dossier de documents")
                    if d:
                        var.set(d)
                ttk.Button(f, text="Parcourir…", command=browse).grid(row=i, column=2, padx=6)

        r = len(fields) + 1
        ttk.Label(f, text="Consigne système").grid(row=r, column=0, sticky="nw", pady=5)
        sys_box = tk.Text(f, height=4, wrap="word")
        sys_box.insert("1.0", self.cfg.get("system_prompt", ""))
        sys_box.grid(row=r, column=1, sticky="ew")

        ttk.Button(f, text="Télécharger le modèle intégré (~400 Mo)", command=self.start_download).grid(
            row=r + 3, column=1, sticky="w")
        ttk.Label(
            f, wraplength=720, justify="left",
            text="Mode intégré : aucun logiciel à installer, le moteur est dans l'appli. "
                 "Recherche en ligne : DuckDuckGo sans clé (parfois limité) ou Tavily avec clé. "
                 "Recherche hors ligne : indexe les .txt .md .csv .docx .pdf du dossier choisi. "
                 "Pour un fonctionnement 100 % hors ligne : mode du modèle « local » + recherche « Hors ligne ».",
        ).grid(row=r + 1, column=0, columnspan=3, pady=12, sticky="w")

        def store():
            ints = {"research_rounds": (1, 3), "research_queries": (1, 6),
                    "num_ctx": (1024, 131072), "max_history": (1, 200)}
            vals = {}
            for k, (lo, hi) in ints.items():
                try:
                    vals[k] = min(hi, max(lo, int(vars_[k].get())))
                except ValueError:
                    messagebox.showerror("Erreur", "Valeur numérique invalide : " + k)
                    return
            for k in ("mode", "gguf_path", "local_url", "local_model", "online_url", "online_model",
                      "api_key", "docs_folder", "search_key"):
                self.cfg[k] = vars_[k].get().strip()
            self.cfg.update(vals)
            self.cfg["system_prompt"] = sys_box.get("1.0", "end").strip()
            save_json(CFG_FILE, self.cfg)
            self.update_mode()
            w.destroy()

        ttk.Button(f, text="Enregistrer", command=store).grid(row=r + 2, column=1, sticky="e")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
