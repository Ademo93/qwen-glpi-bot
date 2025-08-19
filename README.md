# 🧠 GLPI ↔ Qwen Bot (Ollama)

[![CI](https://github.com/<OWNER>/<REPO>/actions/workflows/ci.yml/badge.svg)](https://github.com/<OWNER>/<REPO>/actions/workflows/ci.yml)
[![E2E (live)](https://github.com/<OWNER>/<REPO>/actions/workflows/e2e-live.yml/badge.svg)](https://github.com/<OWNER>/<REPO>/actions/workflows/e2e-live.yml)
[![Publish](https://github.com/<OWNER>/<REPO>/actions/workflows/publish.yml/badge.svg)](https://github.com/<OWNER>/<REPO>/actions/workflows/publish.yml)

Assistant qui **lit** les tickets GLPI et **propose des réponses** : diagnostics pas-à-pas, questions ciblées, et procédures.  
Il **s’arrête** automatiquement si un **technicien** intervient ou si l’utilisateur **demande un humain**, et peut **reprendre** via `#resume-bot`.

- **Modèle** : Qwen 2.5 (via **Ollama**).  
- **RAG léger** : recherche de **cas similaires** dans l’historique des tickets **résolus/clos**.  
- **Sécurité** : réponses non destructives, respect RGPD.

---

## ✨ Points clés

- Réponses FR (ou EN si le ticket est en anglais), **4–6 étapes max**, ton clair.
- **Self-service** si possible → réponse **publique** à l’utilisateur ; sinon **brouillon privé** au technicien.
- **Opt-out par ticket** : stop si un tech répond / si l’utilisateur veut un humain ; **reprise** via `#resume-bot`.
- **Anti-doublon** : n’envoie pas deux fois la même réponse.
- **Perfs** : cache d’index similaire, polling adaptatif, limitation de tickets par cycle.

---

## 🏗️ Architecture

- **GLPI API**
  - Liste des tickets actifs (statuts 1/2/3), récupération des suivis, création de suivis (public/privé).
  - Détection “tech a répondu” et “je veux parler à un humain”.
- **RAG**
  - Indexe l’historique des tickets **résolus/clos** (pagination), calibre une similarité pondérée par
    les **mots-clés du titre**, le corps et des **mots-clés extraits automatiquement** (alias simples : `wifi`, `vpn`, `ecran_noir`, …).
- **Génération**
  - Appel `/api/chat` (JSON schema) avec fallback sur `/api/generate`.
  - Sortie JSON stricte :  
    `reply`, `confidence`, `tags`, `close_candidate`, `audience (user|technician)`, `public_reply (bool)`.

---

## 🚀 Démarrage rapide

### Option 1 — Docker Compose (recommandé)

1. Copier l’exemple d’environnement :
   ```bash
   cp .env.example .env
   # Éditer .env et renseigner GLPI_URL / GLPI_APP_TOKEN / GLPI_USER_TOKEN
