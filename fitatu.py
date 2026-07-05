# -*- coding: utf-8 -*-
"""Nieoficjalny pobieracz odzywiania z Fitatu (analogicznie do garminconnect).
Loguje sie, pobiera dzienny plan/diete i sumuje makro do pol wiersza.
Endpointy z nieoficjalnego fitatu-sdk (Capure/fitatu-sdk), potwierdzone spikem."""
import json, base64, requests

BASE = "https://pl-pl.fitatu.com/api"
_HEADERS = {
    "api-key": "FITATU-MOBILE-APP",
    "api-secret": "PYRXtfs88UDJMuCCrNpLV",
    "User-Agent": "protokol-health/1.0",
    "Accept": "application/json",
}

# Docelowe pole wiersza -> nazwa pola w pozycji posilku Fitatu.
_SUM = {"bialko": "protein", "kcal_spozyte": "energy", "wegle": "carbohydrate",
        "tluszcz": "fat", "blonnik": "fiber"}
_KEYS = ("bialko", "kcal_spozyte", "wegle", "tluszcz", "blonnik", "fitatu")


def _parse_jwt(token):
    """Dekoduje payload JWT (bez weryfikacji podpisu) — tylko po to, by odczytac id."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))


def login(email, password):
    s = requests.Session()
    s.headers.update(_HEADERS)
    r = s.post(BASE + "/login", json={"_username": email, "_password": password}, timeout=30)
    r.raise_for_status()
    token = r.json().get("token")
    uid = str(_parse_jwt(token).get("id"))
    s.headers.update({"Authorization": "Bearer " + token})
    return {"session": s, "uid": uid}


def fetch_nutrition(client, day):
    try:
        url = f"{BASE}/diet-and-activity-plan/{client['uid']}/day/{day}"
        r = client["session"].get(url, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("Fitatu fetch", day, "blad:", str(e)[:160])
        return None


def normalize_nutrition(raw):
    if not isinstance(raw, dict):
        return {k: None for k in _KEYS}
    out = {k: None for k in _KEYS}
    out["fitatu"] = raw
    diet = raw.get("dietPlan")
    if not isinstance(diet, dict):
        return out
    totals = {dst: 0.0 for dst in _SUM}
    any_item = False
    for meal in diet.values():
        if not isinstance(meal, dict):
            continue
        for item in (meal.get("items") or []):
            if not isinstance(item, dict):
                continue
            any_item = True
            for dst, src in _SUM.items():
                v = item.get(src)
                if isinstance(v, (int, float)):
                    totals[dst] += v
    if any_item:
        for dst in _SUM:
            out[dst] = round(totals[dst], 1)
    return out


def fetch_normalized(client, day):
    return normalize_nutrition(fetch_nutrition(client, day))
