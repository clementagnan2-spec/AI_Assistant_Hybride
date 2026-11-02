"""Recherche approfondie, en ligne (web) ou hors ligne (documents locaux).

Principe : le modèle planifie des requêtes -> on collecte des sources (web ou dossier local)
-> éventuel 2e tour sur ce qui manque -> le modèle rédige une synthèse citant [1], [2]...
"""
import html
import json
import math
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from html.parser import HTMLParser

import llm

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
EXT = (".txt", ".md", ".csv", ".log", ".json", ".docx", ".pdf")
STOP = set("""le la les un une des du de et en au aux ce ces cet cette que qui quoi dont ou pour par sur
sous dans avec sans est sont ete etre ont plus moins comment quel quelle quels quelles son sa ses leur
the and for with that this from are was were what how which who about into""".split())

SYSTEM = ("Tu es un analyste de recherche rigoureux. Réponds en français en t'appuyant UNIQUEMENT sur les "
          "sources fournies. Cite les sources avec [1], [2]… après chaque affirmation. Si les sources ne "
          "suffisent pas ou se contredisent, dis-le clairement. Structure : 1) Synthèse, 2) Points clés, "
          "3) Limites et incertitudes. N'invente aucun fait ni aucune source.")


class ResearchError(llm.LLMError):
    pass


# ---------- utilitaires texte ----------
def _words(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return [w for w in re.findall(r"[a-z0-9]{3,}", s) if w not in STOP]


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def _chunks(text, size=900):
    out, cur = [], ""
    for p in re.split(r"\n", text):
        p = re.sub(r"[ \t]+", " ", p).strip()
        for i in range(0, len(p), size):
            piece = p[i:i + size]
            if cur and len(cur) + len(piece) > size:
                out.append(cur.strip())
                cur = ""
            cur += piece + "\n"
    if cur.strip():
        out.append(cur.strip())
    return out


def _select(text, query, cap):
    """Garde les passages les plus proches de la question, dans l'ordre d'origine."""
    if len(text) <= cap:
        return text
    qt = set(_words(query))
    parts = _chunks(text, 700)
    ranked = sorted(range(len(parts)), key=lambda i: -len(qt & set(_words(parts[i]))))
    picked, total = [], 0
    for i in ranked:
        if picked and total + len(parts[i]) > cap:
            break
        picked.append(i)
        total += len(parts[i])
    return "\n".join(parts[i] for i in sorted(picked))[:cap]


# ---------- web ----------
def _http(url, data=None, headers=None, timeout=20, limit=700_000):
    h = {"User-Agent": UA, "Accept-Language": "fr,en;q=0.8"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read(limit)
            ctype = res.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raise ResearchError(f"HTTP {e.code} sur {url}")
    except (urllib.error.URLError, OSError) as e:
        raise ResearchError(f"accès Internet impossible ({getattr(e, 'reason', e)})")
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    try:
        text = raw.decode(m.group(1) if m else "utf-8", "replace")
    except LookupError:
        text = raw.decode("utf-8", "replace")
    return text, ctype


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(page):
    p = _Text()
    try:
        p.feed(page)
    except Exception:
        pass
    lines = [re.sub(r"\s+", " ", l).strip() for l in "".join(p.parts).splitlines()]
    return "\n".join(l for l in lines if len(l) > 25)


def fetch_page(url):
    text, ctype = _http(url)
    if "html" in ctype.lower() or "<html" in text[:500].lower():
        return html_to_text(text)
    return text if ctype.lower().startswith("text/") else ""


def _parse_ddg(page, n):
    snippets = [_clean(m) for m in re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S)]
    out = []
    for i, m in enumerate(re.finditer(r'<a\s([^>]*class="[^"]*result__a[^"]*"[^>]*)>(.*?)</a>', page, re.S)):
        href = re.search(r'href="([^"]+)"', m.group(1))
        if not href:
            continue
        url = html.unescape(href.group(1))
        if url.startswith("//"):
            url = "https:" + url
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if "uddg" in q:
            url = q["uddg"][0]
        if not url.startswith("http") or "duckduckgo.com/y.js" in url:
            continue
        out.append({"title": _clean(m.group(2)), "url": url,
                    "snippet": snippets[i] if i < len(snippets) else ""})
        if len(out) >= n:
            break
    return out


def web_search(cfg, query, n=5):
    key = cfg.get("search_key", "").strip()
    if key:  # Tavily (clé optionnelle, plus fiable)
        payload = json.dumps({"api_key": key, "query": query, "max_results": n}).encode()
        text, _ = _http("https://api.tavily.com/search", data=payload,
                        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        try:
            data = json.loads(text)
        except ValueError:
            raise ResearchError("réponse Tavily illisible")
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
                for r in data.get("results", [])][:n]
    body = urllib.parse.urlencode({"q": query, "kl": "fr-fr"}).encode()
    page, _ = _http("https://html.duckduckgo.com/html/", data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    res = _parse_ddg(page, n)
    if not res:
        raise ResearchError("aucun résultat (DuckDuckGo limite parfois les requêtes : essaie une clé Tavily)")
    return res


def _web_round(cfg, query, question, seen, pages, say):
    out = []
    for r in web_search(cfg, query, 5):
        if len(out) >= pages:
            break
        if not r["url"] or r["url"] in seen:
            continue
        seen.add(r["url"])
        text = ""
        try:
            text = _select(fetch_page(r["url"]), question + " " + query, 1800)
        except ResearchError as e:
            say(f"Page ignorée ({e})")
        if len(text) < 200:
            text = r["snippet"]
        if text:
            out.append({"title": r["title"] or r["url"], "url": r["url"], "text": text})
    return out


# ---------- documents locaux ----------
def read_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        xml = xml.replace("</w:p>", "\n").replace("<w:tab/>", "\t")
        return html.unescape(re.sub(r"<[^>]+>", "", xml))
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return ""
        return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages[:300])
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


class LocalIndex:
    def __init__(self, folder, max_files=500):
        self.items = []  # (titre, chemin, n°, texte, compteur de mots)
        n = 0
        for root, _, files in os.walk(folder):
            for name in sorted(files):
                if not name.lower().endswith(EXT) or n >= max_files:
                    continue
                path = os.path.join(root, name)
                try:
                    if os.path.getsize(path) > 8_000_000:
                        continue
                    text = read_file(path)
                except Exception:
                    continue
                n += 1
                for i, c in enumerate(_chunks(text)):
                    self.items.append((name, path, i, c, Counter(_words(c))))
        self.df = Counter()
        for it in self.items:
            self.df.update(it[4].keys())

    def search(self, query, k, seen):
        qt = set(_words(query))
        total = len(self.items)
        scored = []
        for name, path, i, text, cnt in self.items:
            if (path, i) in seen:
                continue
            s = sum(math.log(1 + total / self.df[t]) * (1 + math.log(cnt[t])) for t in qt if t in cnt)
            if s > 0:
                scored.append((s, name, path, i, text))
        scored.sort(key=lambda x: -x[0])
        out = []
        for _, name, path, i, text in scored[:k]:
            seen.add((path, i))
            out.append({"title": name, "url": path, "text": text})
        return out


# ---------- orchestration ----------
def _ask_lines(cfg, prompt, stop, n):
    out = llm.complete(cfg, [{"role": "user", "content": prompt}], stop)
    res = []
    for line in out.splitlines():
        line = re.sub(r"^[\s\-\*\d\.\)\(]+", "", line).strip(" \"'«»*")
        if 3 < len(line) < 150 and not line.endswith(":") and line.lower() not in ("aucune", "aucun"):
            res.append(line)
    return res[:n]


def _dedupe(items):
    seen, out = set(), []
    for x in items:
        if x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out


def _context(sources, budget):
    per = max(500, budget // max(1, len(sources)))
    return "\n\n".join(f"[{i}] {s['title']} ({s['url']})\n{s['text'][:per]}"
                       for i, s in enumerate(sources, 1))


def _docs_ok(cfg):
    folder = cfg.get("docs_folder", "").strip()
    return bool(folder) and os.path.isdir(folder)


def deep_research(cfg, question, stop=None, progress=None, notice=None):
    """Générateur de texte : la synthèse, puis la liste des sources."""
    say = progress or (lambda s: None)
    warn = notice or (lambda s: None)
    mode = cfg.get("research_mode", "web")  # web | local | auto
    kind = "local" if mode == "local" else "web"
    rounds = min(3, max(1, int(cfg.get("research_rounds", 2))))
    nq = min(6, max(1, int(cfg.get("research_queries", 3))))
    max_src = 8
    stopped = lambda: stop is not None and stop.is_set()
    sources, seen, used = [], set(), []
    index = None

    def get_index():
        nonlocal index
        if index is None:
            if not _docs_ok(cfg):
                raise ResearchError("dossier de documents introuvable : choisis-le dans Paramètres")
            say("Indexation des documents…")
            index = LocalIndex(cfg["docs_folder"].strip())
            if not index.items:
                raise ResearchError("aucun document lisible (.txt .md .docx .pdf…) dans ce dossier")
        return index

    def run(q):
        if kind == "web":
            return _web_round(cfg, q, question, seen, 2, say)
        return get_index().search(q + " " + question, 4, seen)

    say("Planification des recherches…")
    extra = _ask_lines(cfg, f"Question : {question}\n\nPropose {nq - 1} requêtes de recherche courtes et "
                       "complémentaires pour y répondre. Une par ligne, sans commentaire.", stop, nq - 1) \
        if nq > 1 else []
    queries = _dedupe([question] + extra)

    for rnd in range(rounds):
        for q in queries:
            if stopped():
                return
            used.append(q)
            say(f"Tour {rnd + 1}/{rounds} — {q}")
            try:
                new = run(q)
            except ResearchError as e:
                if mode == "auto" and kind == "web" and not sources and _docs_ok(cfg):
                    warn(f"[Recherche en ligne indisponible : {e}\nBascule sur les documents locaux.]\n")
                    kind = "local"
                    new = run(q)
                elif sources:
                    warn(f"[Requête « {q} » ignorée : {e}]\n")
                    continue
                else:
                    raise
            sources.extend(new)
        if len(sources) >= max_src or rnd + 1 >= rounds:
            break
        say("Recherche des informations manquantes…")
        titles = "\n".join("- " + s["title"] for s in sources)
        queries = [x for x in _ask_lines(
            cfg, f"Question : {question}\n\nSources déjà trouvées :\n{titles}\n\nPropose au maximum 2 "
                 "requêtes de recherche pour couvrir ce qui manque encore. Une par ligne, sans commentaire.",
            stop, 2) if x.lower() not in {u.lower() for u in used}]
        if not queries:
            break

    if stopped():
        return
    if not sources:
        raise ResearchError("aucune source trouvée pour cette question")
    sources = sources[:max_src]
    say(f"Rédaction de la synthèse ({len(sources)} sources)…")
    ctx = _context(sources, int(cfg.get("ctx_chars", 9000)))
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Question : {question}\n\nSOURCES :\n{ctx}\n\nRédige la synthèse."}]
    for chunk in llm.chat_stream(cfg, msgs, stop, notice):
        yield chunk
    if not stopped():
        yield "\n\nSources :\n" + "\n".join(
            f"[{i}] {s['title']} — {s['url']}" for i, s in enumerate(sources, 1))
