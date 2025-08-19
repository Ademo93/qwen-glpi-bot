# app.py — GLPI ↔ Ollama (Qwen 2.5) — mémoire + opt-out + similarité par titre + extraction auto de mots-clés + cache + perfs
# Dépendances: requests, python-dotenv

import os, json, time, argparse, unicodedata, difflib, re
from collections import Counter
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv()

# ===============================
#        CONFIG .ENV
# ===============================
GLPI_URL        = os.getenv("GLPI_URL", "http://localhost/glpi/apirest.php").rstrip("/")
GLPI_APP_TOKEN  = os.getenv("GLPI_APP_TOKEN", "")
GLPI_USER_TOKEN = os.getenv("GLPI_USER_TOKEN", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL_NAME      = os.getenv("MODEL_NAME", "qwen2.5:1.5b-instruct")

POLL_SECONDS    = int(os.getenv("POLL_SECONDS", "60"))
STATE_FILE      = Path(os.getenv("STATE_FILE", "state.json"))
FILTER_ENTITY   = (os.getenv("FILTER_ENTITY_ID") or "").strip()

# Université (facultatif)
ORG   = os.getenv("ORG_NAME", "Université")
PORT  = os.getenv("SUPPORT_PORTAL_URL", "https://support.univ.local")
PHONE = os.getenv("SUPPORT_PHONE", "")
HOURS = os.getenv("SUPPORT_HOURS", "")

# Debug & Forçage
DEBUG            = os.getenv("DEBUG", "0") == "1"
DISABLE_HANDOFF  = os.getenv("DISABLE_HANDOFF", "0") == "1"
FORCE_TICKET_ID  = (os.getenv("FORCE_TICKET_ID") or "").strip()
ADD_STATUS       = (os.getenv("ADD_STATUS") or "").strip()      # ex: "4,5"

# Perfs & débit
MAX_TICKETS_PER_CYCLE = int(os.getenv("MAX_TICKETS_PER_CYCLE", "10"))
MAX_HISTORY           = int(os.getenv("MAX_HISTORY", "8"))

# Polling adaptatif
ADAPTIVE_POLL    = os.getenv("ADAPTIVE_POLL", "0") == "1"
POLL_MIN         = int(os.getenv("POLL_MIN", "5"))
POLL_MAX         = int(os.getenv("POLL_MAX", "120"))
NO_TICKETS_GRACE = int(os.getenv("NO_TICKETS_GRACE", "3"))

# Ollama options
OLLAMA_NUM_THREAD = int(os.getenv("OLLAMA_NUM_THREAD", "0") or 0)  # 0 = auto
OLLAMA_NUM_GPU    = int(os.getenv("OLLAMA_NUM_GPU", "0") or 0)     # 0=CPU
OLLAMA_NUM_CTX    = int(os.getenv("OLLAMA_NUM_CTX", "2048") or 2048)
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "5m")

# Recherche cas similaires (historique complet + pondération titre)
SIMILAR_LOOKBACK_LIMIT = int(os.getenv("SIMILAR_LOOKBACK_LIMIT", "5000"))
SIMILAR_TOP_K          = int(os.getenv("SIMILAR_TOP_K", "5"))

SIMILAR_PAGE_SIZE   = int(os.getenv("SIMILAR_PAGE_SIZE", "200"))
SIMILAR_MAX_PAGES   = int(os.getenv("SIMILAR_MAX_PAGES", "25"))
SIMILAR_FETCH_ORDER = (os.getenv("SIMILAR_FETCH_ORDER", "desc") or "desc").lower()

TITLE_KEYWORD_WEIGHT = float(os.getenv("TITLE_KEYWORD_WEIGHT", "0.65"))
CONTENT_WEIGHT       = float(os.getenv("CONTENT_WEIGHT", "0.35"))
MIN_TITLE_OVERLAP    = int(os.getenv("MIN_TITLE_OVERLAP", "1"))

SIMILAR_INDEX_CACHE  = os.getenv("SIMILAR_INDEX_CACHE", "similar_index.json")
SIMILAR_CACHE_TTL_MIN = int(os.getenv("SIMILAR_CACHE_TTL_MIN", "60"))

# Extraction & réutilisation de mots-clés
KEYWORDS_TOP_K     = int(os.getenv("KEYWORDS_TOP_K", "8"))
KEYWORD_SIM_WEIGHT = float(os.getenv("KEYWORD_SIM_WEIGHT", "0.25"))

def dprint(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

# Statuts cibles (par défaut 1,2,3). Ajoutez d'autres via ADD_STATUS="4,5"
TARGET_STATUSES = {"1", "2", "3"}
if ADD_STATUS:
    TARGET_STATUSES |= {s.strip() for s in ADD_STATUS.split(",") if s.strip()}

# ===============================
#        CONSTANTES PROMPT
# ===============================
HEADERS_JSON = {"Content-Type": "application/json"}
BOT_SIGNATURE = "— Réponse générée par Qwen (brouillon)"

# Règles système spécialisées "université" + sortie étendue (audience/public_reply)
SYSTEM_RULES = (
    "Tu es l’assistant du support informatique de " + ORG + ".\n"
    "Public: étudiants, enseignants, chercheurs, personnels.\n\n"
    "Utilise l'historique du ticket ET la liste de 'CAS SIMILAIRES RÉSOLUS' fournie pour proposer une solution.\n"
    "Si l’utilisateur peut résoudre seul (procédure sûre, simple, sans droits élevés) => audience=user, public_reply=true.\n"
    "Sinon => audience=technician, public_reply=false, et détaille précisément la démarche côté technicien.\n\n"
    "Principes:\n"
    "- Réponds poliment et clairement en FR (ou en EN si le ticket est en anglais).\n"
    "- Ne répète jamais une question déjà posée dans ce ticket.\n"
    "- Limite-toi à 2 questions max par réponse et 4–6 étapes de diagnostic numérotées.\n"
    "- Si l’utilisateur n’a rien à l’écran, privilégie d’abord écran/alimentation/câbles/source avant tout test logiciel.\n"
    "- Jamais d’action destructive. Respecte la confidentialité/RGPD.\n"
    "- Si l’utilisateur demande un technicien/humain, l’orchestrateur arrêtera le bot pour ce ticket.\n\n"
    f"Raccourcis utiles:\n- Portail d’assistance : {PORT}\n- Standard support : {PHONE} (horaires : {HOURS})\n\n"
    "Sortie JSON STRICT :\n"
    "{\n"
    '  "reply": str,\n'
    '  "confidence": int,\n'
    '  "tags": [str],\n'
    '  "close_candidate": bool,\n'
    '  "audience": "user" | "technician",\n'
    '  "public_reply": bool\n'
    "}\n"
)

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "confidence": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "close_candidate": {"type": "boolean"},
        "audience": {"type": "string", "enum": ["user", "technician"]},
        "public_reply": {"type": "boolean"}
    },
    "required": ["reply", "confidence", "tags", "close_candidate", "audience", "public_reply"],
    "additionalProperties": False
}

# ===============================
#            STATE
# ===============================
def normalize_state(s: dict) -> dict:
    if not isinstance(s, dict):
        s = {}
    if "last_seen_public" not in s or not isinstance(s["last_seen_public"], dict):
        s["last_seen_public"] = {}
    if "opt_out" not in s or not isinstance(s["opt_out"], dict):
        s["opt_out"] = {}
    if "keywords" not in s or not isinstance(s["keywords"], dict):
        s["keywords"] = {}
    return s

def load_state():
    if STATE_FILE.exists():
        try:
            return normalize_state(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return {"last_seen_public": {}, "opt_out": {}, "keywords": {}}

def save_state(state):
    STATE_FILE.write_text(json.dumps(normalize_state(state), ensure_ascii=False, indent=2), encoding="utf-8")

# ===============================
#             GLPI
# ===============================
def glpi_init_session():
    r = requests.post(
        f"{GLPI_URL}/initSession",
        headers={"App-Token": GLPI_APP_TOKEN, "Authorization": f"user_token {GLPI_USER_TOKEN}"},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json().get("session_token")
    if not token:
        raise RuntimeError("initSession: pas de session_token (URL/tokens/API ?)")
    return token

def glpi_headers(session_token):
    return {"App-Token": GLPI_APP_TOKEN, "Session-Token": session_token, "Content-Type": "application/json"}

def ensure_ticket_dict(session_token, t):
    """Normalise un ticket: si 't' est un id brut, récupère l'objet complet."""
    if isinstance(t, dict):
        return t
    if isinstance(t, (int, str)) and str(t).isdigit():
        tid = int(t)
        r = requests.get(f"{GLPI_URL}/Ticket/{tid}", headers=glpi_headers(session_token), timeout=30)
        r.raise_for_status()
        return r.json()
    return None

def glpi_list_active_tickets(session_token, limit=200):
    """Liste /Ticket/ puis filtre status∈TARGET_STATUSES (+ entité optionnelle)."""
    r = requests.get(f"{GLPI_URL}/Ticket/", headers=glpi_headers(session_token),
                     params={"range": f"0-{limit-1}"}, timeout=30)
    r.raise_for_status()
    items = r.json() or []
    if isinstance(items, dict) and "data" in items:
        items = items["data"] or []
    results = []
    for t in items:
        t = ensure_ticket_dict(session_token, t)
        if not t: continue
        if str(t.get("status")) not in TARGET_STATUSES: continue
        if FILTER_ENTITY and str(t.get("entities_id")) != FILTER_ENTITY: continue
        results.append({
            "id": int(t.get("id")), "status": int(t.get("status", 0) or 0),
            "name": t.get("name","") or "", "urgency": t.get("urgency"),
            "content": t.get("content") or t.get("description","") or "",
            "users_id_recipient": t.get("users_id_recipient"),
            "entities_id": t.get("entities_id"),
            "itilcategories_id": t.get("itilcategories_id"),
        })
    return results

def glpi_get_followups(session_token, ticket_id):
    r = requests.get(f"{GLPI_URL}/Ticket/{ticket_id}/ITILFollowup", headers=glpi_headers(session_token), timeout=30)
    if r.status_code != 200: return []
    data = r.json()
    if isinstance(data, dict) and "data" in data: data = data["data"] or []
    return data if isinstance(data, list) else []

def glpi_get_solution(session_token, ticket_id):
    """Essaye de récupérer l'objet ITILSolution si exposé."""
    try:
        r = requests.get(f"{GLPI_URL}/Ticket/{ticket_id}/ITILSolution", headers=glpi_headers(session_token), timeout=30)
        if r.status_code != 200: return None
        data = r.json()
        if isinstance(data, dict) and "data" in data: data = data["data"] or []
        if not data: return None
        data = sorted(data, key=lambda x: int(x.get("id",0)), reverse=True)
        return (data[0].get("content") or "").strip() or None
    except Exception:
        return None

def glpi_post_followup(session_token, ticket_id, content, is_private=True):
    body = {"input": {"content": content + f"\n\n{BOT_SIGNATURE}",
                      "is_private": 1 if is_private else 0,
                      "items_id": ticket_id, "itemtype": "Ticket"}}
    r = requests.post(f"{GLPI_URL}/Ticket/{ticket_id}/ITILFollowup",
                      headers=glpi_headers(session_token), json=body, timeout=30)
    r.raise_for_status()
    return r.json()

def latest_public_followup_id_and_content(session_token, ticket_id):
    flw = glpi_get_followups(session_token, ticket_id) or []
    publics = [f for f in flw if str(f.get("is_private","0")) == "0"]
    if not publics: return 0, None
    def sid(x):
        try: return int(x.get("id",0))
        except: return 0
    last = max(publics, key=sid)
    return sid(last), last.get("content")

# ===============================
#  SIMILAR CASES (historique & cache)
# ===============================
_word_re = re.compile(r"[a-z0-9]+", re.IGNORECASE)

FR_STOPWORDS = {
    "a","à","ai","aie","ait","au","aux","avec","car","ce","cela","ces","cet","cette","ceci","de","des","du",
    "d","dans","en","et","est","été","être","il","ils","elle","elles","je","j","la","le","les","leur","leurs",
    "l","ma","mes","mon","mais","me","moi","ne","nos","notre","nous","ou","où","par","pas","pour","qu","que",
    "qui","sa","se","ses","son","sur","ta","te","tes","toi","ton","tu","un","une","vos","votre","vous","y"
}

ALIASES = {
    # réseaux / wifi
    "wi-fi":"wifi","wifi":"wifi","eduroam":"wifi","wpa":"wifi",
    # vpn
    "vpn":"vpn","anyconnect":"vpn","openvpn":"vpn",
    # messagerie
    "outlook":"outlook","exchange":"outlook","boite":"outlook","mail":"outlook","courriel":"outlook",
    # pédagogie
    "moodle":"moodle","teams":"visioconf","zoom":"visioconf",
    # affichage / matériel
    "ecran":"ecran","écran":"ecran","noir":"noir","ecran noir":"ecran_noir","écran noir":"ecran_noir",
    # comptes
    "mot":"mot","passe":"passe","mot de passe":"mdp","password":"mdp","ent":"ent","sso":"sso",
    # impression
    "imprimante":"imprimante","impression":"imprimante",
}

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))

def _alias(s: str) -> str:
    s = strip_accents(s.lower())
    return ALIASES.get(s, s)

def tokenize(text: str):
    return set(_word_re.findall((text or "").lower()))

def keyword_tokens_title(title: str) -> set:
    toks = [_alias(t) for t in _word_re.findall(title or "")]
    toks = [t for t in toks if len(t) >= 2 and t not in FR_STOPWORDS]
    bigrams = []
    for i in range(len(toks)-1):
        bg = _alias(toks[i] + " " + toks[i+1])
        if " " not in bg:
            bigrams.append(bg)
    return set(toks) | set(bigrams)

def jaccard(a: set, b: set):
    if not a or not b: return 0.0
    inter = len(a & b); union = len(a | b)
    return inter / union if union else 0.0

def text_for_ticket_base(t):
    return (t.get("name","") + "\n" + (t.get("content") or "")).strip()

# --- Pagination GLPI pour tout l'historique des tickets résolus/fermés ---
def glpi_fetch_solved_tickets_paginated(session_token, page_size=200, max_pages=25, max_total=None):
    results = []
    for page in range(max_pages):
        start = page * page_size
        end   = start + page_size - 1
        r = requests.get(
            f"{GLPI_URL}/Ticket/",
            headers=glpi_headers(session_token),
            params={"range": f"{start}-{end}"},
            timeout=30
        )
        r.raise_for_status()
        items = r.json() or []
        if isinstance(items, dict) and "data" in items:
            items = items["data"] or []
        if not items:
            break
        for t in items:
            t = ensure_ticket_dict(session_token, t)
            if not t: continue
            if str(t.get("status")) not in {"5","6"}: continue  # solved/closed
            if FILTER_ENTITY and str(t.get("entities_id")) != FILTER_ENTITY: continue
            results.append({
                "id": int(t.get("id")),
                "name": t.get("name","") or "",
                "content": t.get("content") or t.get("description","") or "",
                "itilcategories_id": t.get("itilcategories_id"),
            })
            if max_total and len(results) >= max_total:
                break
        if max_total and len(results) >= max_total:
            break
        if len(items) < page_size:
            break
    results.sort(key=lambda x: int(x["id"]), reverse=(SIMILAR_FETCH_ORDER == "desc"))
    return results

# --- Cache d'index des tickets résolus (pour accélérer) ---
def _load_similar_index_cache():
    p = Path(SIMILAR_INDEX_CACHE)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    ts = float(data.get("created_at", 0))
    if (time.time() - ts) > SIMILAR_CACHE_TTL_MIN * 60:
        return None
    return data

def _save_similar_index_cache(data: dict):
    data = dict(data)
    data["created_at"] = time.time()
    Path(SIMILAR_INDEX_CACHE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

def build_solved_index(session_token, max_total=5000):
    solved = glpi_fetch_solved_tickets_paginated(session_token,
                                                 page_size=SIMILAR_PAGE_SIZE,
                                                 max_pages=SIMILAR_MAX_PAGES,
                                                 max_total=max_total)
    idx = []
    for t in solved:
        title = (t.get("name") or "").strip()
        base_text = text_for_ticket_base(t)
        idx.append({
            "id": int(t["id"]),
            "title": title,
            "title_kw": sorted(list(keyword_tokens_title(title))),
            "content_kw": sorted(list(tokenize(base_text))),
            "itilcategories_id": t.get("itilcategories_id"),
        })
    return {"tickets": idx}

def last_public_followup_text(session_token, ticket_id):
    flw = glpi_get_followups(session_token, ticket_id) or []
    pubs = [f for f in flw if str(f.get("is_private","0")) == "0"]
    if not pubs: return ""
    pubs.sort(key=lambda x: int(x.get("id",0)))
    return (pubs[-1].get("content") or "").strip()

def build_case_summary(session_token, t_stub):
    """Retourne (title, problem_snippet, solution_snippet). Complète description si absente."""
    tid = int(t_stub["id"])
    full = ensure_ticket_dict(session_token, tid)
    title = (full.get("name") or t_stub.get("name") or "").strip()
    base = (full.get("content") or t_stub.get("content") or "").strip()
    sol = glpi_get_solution(session_token, tid) or last_public_followup_text(session_token, tid)
    return title, base[:500], (sol or "")[:800]

# ===============================
#      EXTRACTION MOTS-CLÉS
# ===============================
def extract_keywords(title: str, content: str, top_k: int = 8) -> list[str]:
    """
    Extraction légère:
    - tokens normalisés + alias (wifi, ecran_noir, vpn…)
    - boost des tokens du TITRE (y compris bigrams aliasés)
    - filtre stopwords + longueur minimale
    """
    title = title or ""
    content = content or ""

    toks = [_alias(t) for t in _word_re.findall(strip_accents((title + "\n" + content)).lower())]
    toks = [t for t in toks if len(t) >= 3 and t not in FR_STOPWORDS]

    title_kw = keyword_tokens_title(title)

    freq = Counter(toks)
    for kw in title_kw:
        freq[kw] += 3  # bonus titre

    scored = freq.most_common(64)
    keywords, seen = [], set()
    for term, _ in scored:
        if term in seen: continue
        seen.add(term)
        keywords.append(term)
        if len(keywords) >= top_k: break

    if not keywords and title_kw:
        keywords = list(title_kw)[:top_k]

    return keywords

# ===============================
#  SIMILARITÉ (avec mots-clés)
# ===============================
def find_similar_cases(session_token, current_text, current_cat, current_title,
                       limit_back=5000, top_k=5, cur_keywords: list[str] | None = None):
    cache = _load_similar_index_cache()
    if not cache:
        cache = build_solved_index(session_token, max_total=limit_back)
        _save_similar_index_cache(cache)

    idx = cache.get("tickets", [])
    cur_title_kw   = keyword_tokens_title(current_title or "")
    cur_content_kw = tokenize(current_text or "")
    cur_kw_set     = set(cur_keywords or [])

    ranked = []
    for it in idx:
        title_kw   = set(it.get("title_kw", []))
        content_kw = set(it.get("content_kw", []))

        # Filtre rapide: au moins MIN_TITLE_OVERLAP mots-clés de titre en commun
        if MIN_TITLE_OVERLAP > 0 and len(cur_title_kw & title_kw) < MIN_TITLE_OVERLAP:
            continue

        title_jac   = jaccard(cur_title_kw, title_kw)
        content_jac = jaccard(cur_content_kw, content_kw)

        kw_overlap = 0.0
        if cur_kw_set:
            kw_overlap = len(cur_kw_set & (title_kw | content_kw)) / max(len(cur_kw_set), 1)

        bonus = 0.1 if current_cat and it.get("itilcategories_id") == current_cat else 0.0

        score = (TITLE_KEYWORD_WEIGHT * title_jac +
                 CONTENT_WEIGHT * content_jac +
                 KEYWORD_SIM_WEIGHT * kw_overlap +
                 bonus)

        ranked.append((score, it))

    ranked.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, it in ranked[:top_k]:
        t_stub = {"id": it["id"], "name": it["title"], "content": ""}
        title, prob, sol = build_case_summary(session_token, t_stub)
        out.append({"id": it["id"], "title": title, "score": round(float(score), 3),
                    "problem": prob, "solution": sol})
    return out

def similar_cases_block(cases, current_title=""):
    if not cases:
        return "Aucun cas similaire trouvé."
    cur_kw = keyword_tokens_title(current_title or "")
    lines = []
    for i, c in enumerate(cases, 1):
        title_kw = keyword_tokens_title(c["title"])
        overlap = ", ".join(sorted(cur_kw & title_kw)) or "—"
        sol = c["solution"] or "(solution non retrouvée)"
        lines.append(
            f"{i}) #{c['id']} — {c['title']} (score={c['score']}, mots-clés communs: {overlap})\n"
            f"   Symptômes: {c['problem']}\n"
            f"   Résolution: {sol}"
        )
    return "\n".join(lines)

# ===============================
#     MÉMOIRE / CONTEXTE
# ===============================
def build_thread_messages(session_token, ticket, max_history=8, similar_text=""):
    tid = ticket["id"]
    msgs = []
    intro = (
        f"Titre: {ticket.get('name','')}\n"
        f"Urgence: {ticket.get('urgency')}\n"
        f"Demandeur (id): {ticket.get('users_id_recipient')}\n"
        f"Catégorie (id): {ticket.get('itilcategories_id')}\n\n"
        f"Description:\n{ticket.get('content','')}\n"
    )
    if similar_text:
        intro += "\nCAS SIMILAIRES RÉSOLUS (résumés):\n" + similar_text + "\n"
    msgs.append({"role": "user", "content": intro})

    flw = glpi_get_followups(session_token, tid) or []
    def sid(x):
        try: return int(x.get("id",0))
        except: return 0
    flw = sorted(flw, key=sid)
    for f in flw:
        content = (f.get("content") or "").strip()
        if not content: continue
        is_private = str(f.get("is_private","0")) == "1"
        if BOT_SIGNATURE in content:
            msgs.append({"role": "assistant", "content": content.replace(f"\n\n{BOT_SIGNATURE}","")})
        elif not is_private:
            msgs.append({"role": "user", "content": content})
    if len(msgs) > max_history: msgs = msgs[-max_history:]
    return msgs

# ===============================
#   HANDOFF, TECHNICIEN & DÉDOUBLON
# ===============================
def detect_handoff_request(text: str) -> bool:
    if not text: return False
    t = strip_accents(text.lower())
    verbs  = ["parler","discuter","echanger","appeler","rappeler","contacter","mettre en relation","transferer"]
    nouns  = ["technicien","agent","humain","operateur","support","service it","service informatique","conseiller"]
    v_hit = any(v in t for v in verbs) or any(v in t for v in ["talk","speak","chat","call","contact","transfer"])
    n_hit = any(n in t for n in nouns) or any(n in t for n in ["human","agent","operator","technician","support"])
    pref  = any(p in t for p in ["je veux","j aimerais","j'aimerais","pouvez vous","peux tu","svp","stp"])
    return (v_hit and n_hit) or (pref and n_hit)

def detect_resume_marker(session_token, ticket_id) -> bool:
    flw = glpi_get_followups(session_token, ticket_id) or []
    privs = [f for f in flw if str(f.get("is_private","0")) == "1"]
    for f in privs[::-1]:
        txt = strip_accents((f.get("content") or "").lower())
        if "#resume-bot" in txt or "reprendre bot" in txt:
            return True
    return False

def _norm(s): return " ".join((s or "").lower().split())

def last_bot_reply(session_token, ticket_id):
    flw = glpi_get_followups(session_token, ticket_id) or []
    for f in reversed(flw):
        content = f.get("content") or ""
        if BOT_SIGNATURE in content:
            return content.replace(f"\n\n{BOT_SIGNATURE}", "").strip()
    return None

def too_similar(a, b, thr=0.90):
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio() >= thr

def technician_replied(session_token, ticket_obj) -> bool:
    tid = int(ticket_obj["id"])
    requester_id = str(ticket_obj.get("users_id_recipient") or "")
    flw = glpi_get_followups(session_token, tid) or []
    if not flw: return False
    def sid(x):
        try: return int(x.get("id",0))
        except: return 0
    for f in sorted(flw, key=sid, reverse=True):
        content = f.get("content") or ""
        if BOT_SIGNATURE in content:
            continue
        is_private = str(f.get("is_private","0")) == "1"
        uid = str(f.get("users_id") or f.get("users_id_editor") or "")
        if is_private: return True
        if requester_id and uid and uid != requester_id: return True
        return False
    return False

# ===============================
#            OLLAMA
# ===============================
def messages_to_prompt(messages):
    parts = []
    for m in messages:
        role = m.get("role"); content = m.get("content","")
        parts.append(("System:" if role=="system" else "Assistant:" if role=="assistant" else "User:") + "\n" + content)
    parts.append("Assistant:")
    return "\n\n".join(parts)

def ask_ollama(messages):
    base_opts = {
        "temperature": 0.2, "repeat_penalty": 1.2, "repeat_last_n": 256,
        "num_thread": OLLAMA_NUM_THREAD if OLLAMA_NUM_THREAD > 0 else None,
        "num_gpu": OLLAMA_NUM_GPU, "num_ctx": OLLAMA_NUM_CTX,
    }
    base_opts = {k:v for k,v in base_opts.items() if v is not None}

    # 1) /api/chat
    try:
        payload = {"model": MODEL_NAME, "messages": messages, "stream": False,
                   "format": JSON_SCHEMA, "options": base_opts, "keep_alive": OLLAMA_KEEP_ALIVE}
        r = requests.post(f"{OLLAMA_BASE_URL}/api/chat", headers=HEADERS_JSON, json=payload, timeout=120)
        if r.status_code == 200:
            data = r.json() or {}
            content = data.get("message", {}).get("content", "")
            if isinstance(content, dict): return content
            if isinstance(content, str):
                s = content.strip()
                try: return json.loads(s)
                except Exception: return {"reply": s, "confidence": 60, "tags": [], "close_candidate": False,
                                         "audience": "technician", "public_reply": False}
        if r.status_code not in (400,404,405): r.raise_for_status()
    except requests.RequestException:
        pass

    # 2) /api/generate
    prompt = messages_to_prompt(messages) + "\n\nRéponds uniquement en JSON valide."
    for fmt in (JSON_SCHEMA, "json", None):
        try:
            payload = {"model": MODEL_NAME, "prompt": prompt, "stream": False,
                       "options": base_opts, "keep_alive": OLLAMA_KEEP_ALIVE}
            if fmt is not None: payload["format"] = fmt
            r = requests.post(f"{OLLAMA_BASE_URL}/api/generate", headers=HEADERS_JSON, json=payload, timeout=120)
            r.raise_for_status()
            data = r.json() or {}; text = (data.get("response") or "").strip()
            if not text: continue
            try: return json.loads(text)
            except Exception: return {"reply": text, "confidence": 60, "tags": [], "close_candidate": False,
                                     "audience": "technician", "public_reply": False}
        except requests.RequestException:
            continue

    return {"reply": "Message pris en compte.", "confidence": 50, "tags": [], "close_candidate": False,
            "audience": "technician", "public_reply": False}

# ===============================
#         TRAITEMENT
# ===============================
def process_once(state):
    session_token = glpi_init_session()
    state = normalize_state(state)
    tickets = glpi_list_active_tickets(session_token, limit=200)[:MAX_TICKETS_PER_CYCLE]
    changed = False

    dprint(f"[SCAN] actifs={len(tickets)} ids={[t.get('id') for t in tickets]} statuses={sorted(TARGET_STATUSES)}")

    for raw in tickets:
        t = ensure_ticket_dict(session_token, raw)
        if not t or "id" not in t:
            dprint("[WARN] ticket inattendu ->", type(raw), raw); continue

        tid = int(t["id"]); tid_key = str(tid)
        force = FORCE_TICKET_ID and tid_key == FORCE_TICKET_ID

        latest_id, latest_content = latest_public_followup_id_and_content(session_token, tid)
        last_seen = state["last_seen_public"].get(tid_key, -1)
        opt_out = state["opt_out"].get(tid_key, False)

        dprint(f"[T{tid}] status={t.get('status')} opt_out={opt_out} last_seen={last_seen} latest_id={latest_id} force={bool(force)}")

        # Reprise manuelle
        if opt_out and detect_resume_marker(session_token, tid):
            state["opt_out"].pop(tid_key, None)
            glpi_post_followup(session_token, tid, "Reprise automatique du bot (#resume-bot).", True)
            dprint(f"[T{tid}] reprise via #resume-bot"); changed = True; opt_out = False

        # Stop si un technicien a répondu
        if not opt_out and technician_replied(session_token, t):
            state["opt_out"][tid_key] = True
            glpi_post_followup(session_token, tid,
                "Intervention d’un **technicien** détectée. Arrêt des réponses automatiques pour CE ticket. "
                "Pour reprendre: suivi privé avec #resume-bot.", True)
            dprint(f"[T{tid}] Technicien détecté -> opt-out CE ticket"); changed = True; continue

        if opt_out and not force:
            dprint(f"[T{tid}] SKIP: opt-out actif"); continue

        # Handoff (parler à un humain)
        if latest_content and not DISABLE_HANDOFF and not force:
            try:
                if detect_handoff_request(latest_content):
                    state["opt_out"][tid_key] = True
                    glpi_post_followup(session_token, tid,
                        "Demande d'échange avec un **technicien/humain** détectée. "
                        "Arrêt des réponses automatiques pour CE ticket. "
                        "Pour reprendre: suivi privé avec #resume-bot.", True)
                    dprint(f"[T{tid}] Handoff détecté -> opt-out CE ticket"); changed = True; continue
            except Exception:
                pass

        if latest_id == last_seen and not force:
            dprint(f"[T{tid}] SKIP: aucun nouveau message public"); continue

        # ---------- Extraction auto de mots-clés ----------
        current_title = t.get("name","") or ""
        current_desc  = t.get("content","") or ""
        current_text  = current_title + "\n" + current_desc

        kw = extract_keywords(current_title, current_desc, top_k=KEYWORDS_TOP_K)
        state["keywords"][tid_key] = kw  # mémoire locale (optionnel)
        dprint(f"[T{tid}] keywords={kw}")

        # ---------- Recherche de cas similaires ----------
        sims = find_similar_cases(
            session_token,
            current_text,
            t.get("itilcategories_id"),
            current_title,
            limit_back=SIMILAR_LOOKBACK_LIMIT,
            top_k=SIMILAR_TOP_K,
            cur_keywords=kw,
        )
        sims_block = similar_cases_block(sims, current_title=current_title)

        # ---------- Contexte + génération ----------
        ticket_ctx = {
            "id": tid, "name": t.get("name",""), "urgency": t.get("urgency"),
            "users_id_recipient": t.get("users_id_recipient"),
            "itilcategories_id": t.get("itilcategories_id"),
            "content": t.get("content",""),
        }
        conv = build_thread_messages(
            session_token,
            ticket_ctx,
            max_history=MAX_HISTORY,
            similar_text=(sims_block + ("\n\nMOTS-CLÉS EXTR: " + ", ".join(kw) if kw else ""))
        )
        messages = [{"role": "system", "content": SYSTEM_RULES}] + conv

        dprint(f"[T{tid}] -> génération…")
        resp = ask_ollama(messages)
        reply = resp.get("reply") or "Message pris en compte."
        audience = resp.get("audience") or "technician"
        public_reply = bool(resp.get("public_reply"))

        # Anti-doublon
        prev = last_bot_reply(session_token, tid)
        if prev and too_similar(prev, reply):
            dprint(f"[T{tid}] SKIP: réponse trop similaire à la précédente")
            state["last_seen_public"][tid_key] = latest_id
            changed = True
            continue

        # Envoi (public si self-service, sinon privé technicien)
        is_private = not public_reply or (audience != "user")
        glpi_post_followup(session_token, tid, reply, is_private=is_private)
        state["last_seen_public"][tid_key] = latest_id
        dprint(f"[T{tid}] OK: suivi {'privé' if is_private else 'public'} déposé")
        changed = True

    return changed

# ===============================
#             MAIN
# ===============================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Un seul cycle puis sortie")
    args = parser.parse_args()

    if not GLPI_APP_TOKEN or not GLPI_USER_TOKEN:
        print("[ERREUR] Renseignez GLPI_APP_TOKEN / GLPI_USER_TOKEN dans .env")
        return

    state = load_state()

    if args.once:
        try:
            if process_once(state): save_state(state)
        except Exception as e:
            print("[ERREUR]", e)
        return

    next_poll = POLL_SECONDS; no_new_counter = 0
    while True:
        start = time.time()
        try:
            changed = process_once(state)
            if changed: save_state(state)
            no_new_counter = 0 if changed else (no_new_counter + 1)
            if ADAPTIVE_POLL:
                if changed:
                    next_poll = max(POLL_MIN, next_poll // 2 if next_poll > POLL_MIN else next_poll)
                else:
                    if no_new_counter >= NO_TICKETS_GRACE:
                        next_poll = min(POLL_MAX, max(next_poll + POLL_MIN, next_poll * 2))
                        no_new_counter = 0
        except Exception as e:
            print("[ERREUR]", e)
            next_poll = min(max(POLL_MIN, next_poll), 30)

        elapsed = time.time() - start
        sleep_for = max(1, int(next_poll - elapsed))
        if DEBUG: print(f"[POLL] prochain passage dans {sleep_for}s (fenêtre={next_poll}s)")
        time.sleep(sleep_for)

if __name__ == "__main__":
    main()
