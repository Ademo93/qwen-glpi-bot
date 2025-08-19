import os
os.environ["DEBUG"] = "0"
# Désactive le cache pour ce test
os.environ["SIMILAR_INDEX_CACHE"] = ""

import app

def test_find_similar_scoring(monkeypatch):
    fake_index = {
        "tickets": [
            {"id": 101, "title": "Wi-Fi eduroam authentification", "title_kw": ["wifi","eduroam"], "content_kw": ["wifi","auth"], "itilcategories_id": 1},
            {"id": 202, "title": "VPN AnyConnect erreur 412",     "title_kw": ["vpn"],            "content_kw": ["vpn","anyconnect"], "itilcategories_id": 2},
        ]
    }
    monkeypatch.setattr(app, "_load_similar_index_cache", lambda: fake_index)
    monkeypatch.setattr(app, "_save_similar_index_cache", lambda data: None)
    monkeypatch.setattr(app, "ensure_ticket_dict", lambda s, t: {"id": t, "name": "stub", "content": "stub"})
    monkeypatch.setattr(app, "glpi_get_solution", lambda s, t: "Solution stub")
    monkeypatch.setattr(app, "last_public_followup_text", lambda s, t: "Dernier suivi stub")

    current_title = "Problème Wi-Fi sur eduroam"
    current_text  = current_title + "\nImpossible de s'authentifier"
    kw = ["wifi","eduroam","auth"]

    sims = app.find_similar_cases(
        session_token="X",
        current_text=current_text,
        current_cat=1,
        current_title=current_title,
        limit_back=100,
        top_k=5,
        cur_keywords=kw,
    )
    assert sims and sims[0]["id"] == 101
