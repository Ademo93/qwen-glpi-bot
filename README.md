# Qwen ↔ GLPI Bot (Ollama)

Assistant qui lit les tickets GLPI, propose des réponses (privées/publics), s’arrête si un technicien répond, et s’inspire de cas similaires via un mini-RAG.
Inclut Docker Compose + tests unitaires + E2E (optionnels).

## Démarrage rapide (Docker Compose)

1. Copiez `.env.example` en `.env` et **renseignez** les tokens GLPI.
2. Lancez :
   ```bash
   docker compose up -d --build
   ```
3. Le service `bot` tourne en continu. Pour un passage unique :
   ```bash
   docker compose run --rm bot python app.py --once
   ```

## Services

- **ollama** : sert le modèle `qwen2.5:1.5b-instruct`.
- **bot** : exécute `app.py`. Monte un volume `/data` pour `state.json` et `similar_index.json`.

## Variables principales

Voir `.env.example`. Les plus importantes :
- `GLPI_URL`, `GLPI_APP_TOKEN`, `GLPI_USER_TOKEN`
- `OLLAMA_BASE_URL` (par défaut `http://ollama:11434`)

## Tests

- **Unitaires (sans GLPI)** :
  ```bash
  pip install -r requirements.txt
  pytest -q
  ```

- **E2E (réels)** : voir `.github/workflows/e2e-live.yml` (nécessite secrets GLPI et accès réseau).
