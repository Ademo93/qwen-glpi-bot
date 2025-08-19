🧠 GLPI ↔ Qwen Bot (Ollama)

Assistant qui lit les tickets GLPI et propose des réponses structurées : diagnostics pas-à-pas, questions ciblées, et procédures.
Il s’arrête automatiquement si un technicien intervient ou si l’utilisateur demande un humain, et peut reprendre via #resume-bot.

🚀 Utilité

Gain de temps pour le support : tri et premières réponses sur les incidents fréquents (Wi-Fi/eduroam, VPN, Outlook, impressions, ENT/Moodle…).

Qualité constante : réponses en FR (ou EN si ticket anglais), 4–6 étapes max, sans actions destructives, respect RGPD.

Self-service quand c’est possible : si l’utilisateur peut résoudre seul, le bot poste une réponse publique ; sinon, il laisse un brouillon privé pour les techs.

🏗️ Conception (vue d’ensemble)

GLPI API

Liste des tickets actifs (statuts 1/2/3) et de leurs suivis.

Poste des suivis (public/privé) signés “— Réponse générée par Qwen (brouillon)”.

Détecte les réponses tech et mots-clés d’escalade (“je veux parler à un technicien”) → opt-out par ticket.

Reprise via suivi privé #resume-bot.

Mémoire conversationnelle

Historique condensé par ticket (dernier N messages publics + précédents du bot).

RAG léger sur l’historique

Indexe les tickets résolus/clos (pagination GLPI) dans un cache.

Recherche de cas similaires pondérée par les mots-clés du titre, le contenu et des mots-clés extraits automatiquement (alias simples : wifi, ecran_noir, vpn, etc.).

Injecte des résumés de résolutions trouvés dans le prompt du modèle.

Génération (Ollama/Qwen 2.5)

Appelle /api/chat (JSON schema) avec fallback sûr sur /api/generate.

Sortie JSON stricte : reply, confidence, tags, close_candidate, audience (user|technician), public_reply (booleen).

Anti-doublon : n’envoie pas 2 fois la même réponse.

Ops & perfs

Polling adaptatif, cache d’index similaire, limitation de tickets par cycle.

Docker Compose prêt, image GHCR auto-publiée (workflow Actions).

⚙️ Déploiement rapide

Docker Compose local : docker compose up -d --build

Image GHCR : docker pull ghcr.io/<owner>/qwen-glpi-bot:latest

Variables nécessaires : GLPI_URL, GLPI_APP_TOKEN, GLPI_USER_TOKEN, OLLAMA_BASE_URL (par défaut http://ollama:11434).

🔐 Sécurité et garde-fous

Jamais d’action destructive automatisée.

Respect des données sensibles ; le bot oriente vers un tech quand nécessaire.

Arrêt automatique sur intervention humaine.
