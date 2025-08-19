# 🧠 GLPI ↔ Qwen Bot (Ollama)

[![CI](https://github.com/<OWNER>/<REPO>/actions/workflows/ci.yml/badge.svg)](https://github.com/<OWNER>/<REPO>/actions/workflows/ci.yml)
[![E2E (live)](https://github.com/<OWNER>/<REPO>/actions/workflows/e2e-live.yml/badge.svg)](https://github.com/<OWNER>/<REPO>/actions/workflows/e2e-live.yml)
[![Publish (GHCR)](https://github.com/<OWNER>/<REPO>/actions/workflows/publish.yml/badge.svg)](https://github.com/<OWNER>/<REPO>/actions/workflows/publish.yml)

Assistant qui **lit** les tickets GLPI et **propose des réponses** concrètes : diagnostic pas‑à‑pas, questions ciblées, procédures et conseils.
Le bot **s’arrête automatiquement pour CE ticket** si un **technicien** répond ou si l’utilisateur **demande un humain**, et peut **reprendre** via `#resume-bot`.

- **Modèle** : Qwen 2.5 (via **Ollama**)
- **RAG léger** : recherche de **cas similaires** (tickets résolus/clos) + **extraction automatique de mots‑clés** (alias: `wifi`, `vpn`, `ecran_noir`, …)
- **Sécurité** : réponses non destructives, respect de la confidentialité (RGPD), garde‑fous

---

## ✨ Ce que ça apporte
- **Gain de temps** : incidents fréquents (eduroam/Wi‑Fi, VPN, Outlook, imprimantes, ENT/Moodle…)
- **Qualité constante** : FR (ou EN si ticket en anglais), 4–6 étapes max, ton clair et courtois
- **Self‑service** : si l’utilisateur peut résoudre seul → **réponse publique** ; sinon → **brouillon privé** au technicien
- **Zéro spam** : anti‑doublon (n’envoie pas 2× la même réponse), **opt‑out par ticket**

---

## 🏗️ Conception
- **GLPI API**
  - Liste des tickets actifs (statuts 1/2/3, paramétrable), lecture des suivis, création de suivis **public/privé**
  - Détection : « je veux parler à un humain » → opt‑out du ticket ; réponse **technicien** → opt‑out du ticket ; suivi privé `#resume-bot` → **reprise**
- **RAG / Similarité**
  - Index des tickets **résolus/clos** (pagination GLPI, cache disque)
  - Score pondéré : **mots‑clés du titre** (bigrams + alias), contenu, + **keywords extraits**
  - Le modèle voit des **résumés** de résolutions proches dans son prompt
- **Génération (Ollama)**
  - `/api/chat` (JSON schema) → fallback `/api/generate`
  - Sortie JSON stricte :
    ```json
    { "reply":"...", "confidence":0, "tags":["..."], "close_candidate":false, "audience":"user|technician", "public_reply":true|false }
    ```
- **Ops / perfs**
  - Polling adaptatif, limitation du nombre de tickets par cycle, cache d’index similaire
  - Docker Compose + image GHCR via GitHub Actions

---

## 🚀 Démarrage rapide

### Option A — Docker Compose (recommandé)
1. Copier l’exemple d’environnement :
   ```bash
   cp .env.example .env
   # Éditer .env et renseigner GLPI_URL / GLPI_APP_TOKEN / GLPI_USER_TOKEN
   ```
2. Lancer :
   ```bash
   docker compose up -d --build
   ```
3. Exécuter une passe unique :
   ```bash
   docker compose run --rm bot python app.py --once
   ```
> Le service `ollama` écoute sur `11434`. Le bot persiste `state.json` et `similar_index.json` dans le volume `bot_data` (`/data`).

### Option B — Image publiée (GHCR)
Après passage du workflow **Publish**, tirer l’image :
```bash
docker pull ghcr.io/<OWNER>/<REPO>:latest
```
Exemple `docker-compose.yml` (image GHCR) :
```yaml
services:
  ollama:
    image: ollama/ollama:latest
    ports: [ "11434:11434" ]
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:11434/api/tags"]
      interval: 5s
      timeout: 3s
      retries: 20
    volumes:
      - ollama_data:/root/.ollama

  bot:
    image: ghcr.io/<OWNER>/<REPO>:latest
    depends_on:
      ollama:
        condition: service_healthy
    env_file:
      - .env
    environment:
      OLLAMA_BASE_URL: ${OLLAMA_BASE_URL-http://ollama:11434}
      MODEL_NAME: ${MODEL_NAME-qwen2.5:1.5b-instruct}
      STATE_FILE: /data/state.json
      SIMILAR_INDEX_CACHE: /data/similar_index.json
    volumes:
      - bot_data:/data
    restart: unless-stopped

volumes:
  ollama_data: {}
  bot_data: {}
```

---

## 🔧 Configuration (.env)
Variables principales (voir `.env.example`) :
```
GLPI_URL=https://votre.glpi.tld/apirest.php
GLPI_APP_TOKEN=...
GLPI_USER_TOKEN=...

# Ollama
OLLAMA_BASE_URL=http://ollama:11434
MODEL_NAME=qwen2.5:1.5b-instruct

# Perf
POLL_SECONDS=20
ADAPTIVE_POLL=1
MAX_HISTORY=8
MAX_TICKETS_PER_CYCLE=10
OLLAMA_KEEP_ALIVE=5m

# Similarité (historique + poids titre)
SIMILAR_LOOKBACK_LIMIT=5000
SIMILAR_PAGE_SIZE=200
SIMILAR_MAX_PAGES=25
SIMILAR_FETCH_ORDER=desc
TITLE_KEYWORD_WEIGHT=0.65
CONTENT_WEIGHT=0.35
MIN_TITLE_OVERLAP=1
SIMILAR_INDEX_CACHE=/data/similar_index.json
SIMILAR_CACHE_TTL_MIN=60

# Keywords
KEYWORDS_TOP_K=8
KEYWORD_SIM_WEIGHT=0.25

# State (persistés)
STATE_FILE=/data/state.json
```

---

## ✅ Tests
- **Unitaires (sans GLPI/Ollama)** :
  ```bash
  pip install -r requirements.txt
  pytest -q
  ```
- **E2E (live)** : onglet **Actions** → workflow **E2E (live)** → *Run workflow*  
  *(secrets requis : `GLPI_URL`, `GLPI_APP_TOKEN`, `GLPI_USER_TOKEN` et éventuellement `GLPI_USER_TOKEN_TECH` / `GLPI_USER_TOKEN_USER`)*

---

## 🛠️ Workflows GitHub Actions
- **CI** : `.github/workflows/ci.yml` — tests unitaires mock  
- **E2E (live)** : `.github/workflows/e2e-live.yml` — passe unique avec service Ollama dans le runner  
- **Publish (GHCR)** : `.github/workflows/publish.yml` — build multi‑arch & push sur `ghcr.io/<OWNER>/<REPO>`

---

## 🆘 Dépannage
- Le bot ne répond pas → vérifier `.env` (URL/API GLPI, tokens), l’accès réseau depuis le conteneur, logs `bot`
- Ollama indisponible → `docker logs ollama` ; s’il manque un modèle, il sera **pull** au démarrage
- GHCR privé → login : `echo $PAT | docker login ghcr.io -u <USER> --password-stdin` (PAT `read:packages`)

---

