import os
os.environ["DEBUG"] = "0"
import app

def test_extract_keywords_basic():
    title = "Problème Wi-Fi eduroam sur campus"
    desc = "Impossible de s'authentifier. Message EAP échec."
    kw = app.extract_keywords(title, desc, top_k=8)
    assert isinstance(kw, list) and len(kw) >= 3
    assert ("wifi" in kw) or ("eduroam" in kw)
