# -*- coding: utf-8 -*-
"""
Codzienny pobieracz Garmin (pelny) + lokalizacja z aktywnosci + pogoda Open-Meteo.
Uruchamiany przez GitHub Actions lub lokalnie: python update_garmin.py
Wznawia sesje z tokenu (bez MFA). Zapisuje JSON, ktory czyta PWA.

Pobiera dziennie: waga, kroki, dystans, aktywne kalorie, pietra, minuty intensywne,
tetno spoczynkowe/min/max, stres sredni/max, Body Battery max/min, HRV + status,
sen + sen gleboki, SpO2 srednie/min, VO2max, gotowosc treningowa, recovery time,
training status, training load, endurance score, hill score,
sklad ciala (% tluszczu, mięsnie, woda) jesli masz wage Garmin Index,
oraz lokalizacje (z GPS aktywnosci, z przenoszeniem na kolejne dni) i temperature
w tej lokalizacji (max + nocne minimum).
"""
import json, os, time, base64, hashlib, getpass, urllib.parse, requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from datetime import date, timedelta
from garminconnect import Garmin

DNI = 120
PAUZA = 0.15
TOKENY = "tokens"

# Lokalizacja domowa (fallback, gdy brak GPS). Dabrowa Gornicza.
HOME = (50.3217, 19.1873)

# Nazwa pliku z danymi. ZMIEN na wlasny losowy ciag i ustaw te sama nazwe
# w index.html (DATA_URL). Repo prywatne nie ukrywa pliku serwowanego przez Pages!
PLIK = "garmin-7c1f93a2.json"


# ===================== narzedzia =====================
def bezp(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return None

def godz(s):
    return round(s / 3600.0, 2) if s else None

def first(d, *ks):
    if not isinstance(d, dict):
        return None
    for k in ks:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None

def _json(url, headers=None):
    r = requests.get(url, headers=headers or {}, timeout=30)
    r.raise_for_status()
    return r.json()


# ===================== lokalizacja =====================
def build_locations(g, start, koniec):
    """Mapa data -> (lat,lon) z aktywnosci GPS, przenoszona na dni bez GPS; fallback dom."""
    loc_by_date = {}
    acts = bezp(g.get_activities_by_date, start, koniec) or []
    if isinstance(acts, list):
        for a in acts:
            if not isinstance(a, dict):
                continue
            d = (a.get("startTimeLocal") or "")[:10]
            la, lo = a.get("startLatitude"), a.get("startLongitude")
            if d and la and lo and d not in loc_by_date:
                loc_by_date[d] = (round(la, 4), round(lo, 4))
    out = {}
    last = HOME
    dd, end = date.fromisoformat(start), date.fromisoformat(koniec)
    while dd <= end:
        k = dd.isoformat()
        if k in loc_by_date:
            last = loc_by_date[k]
        out[k] = last
        dd += timedelta(days=1)
    return out

def rev_geo(lat, lon):
    try:
        q = urllib.parse.urlencode({"lat": lat, "lon": lon, "format": "json", "zoom": 10})
        j = _json("https://nominatim.openstreetmap.org/reverse?" + q,
                  headers={"User-Agent": "protokol-health/1.0"})
        a = j.get("address", {})
        return a.get("city") or a.get("town") or a.get("village") or a.get("county") or ""
    except Exception:
        return ""


# ===================== pogoda =====================
def archive_forecast(lat, lon, start, end):
    out = {}
    try:
        q = urllib.parse.urlencode({"latitude": lat, "longitude": lon,
            "start_date": start, "end_date": end,
            "daily": "temperature_2m_max,temperature_2m_min", "timezone": "Europe/Warsaw"})
        d = _json("https://archive-api.open-meteo.com/v1/archive?" + q).get("daily", {})
        for dt, tx, tn in zip(d.get("time", []), d.get("temperature_2m_max", []), d.get("temperature_2m_min", [])):
            out[dt] = {"max": tx, "min": tn}
    except Exception as e:
        print("archiwum pogody:", e)
    try:
        q = urllib.parse.urlencode({"latitude": lat, "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min", "timezone": "Europe/Warsaw",
            "past_days": 14, "forecast_days": 1})
        d = _json("https://api.open-meteo.com/v1/forecast?" + q).get("daily", {})
        for dt, tx, tn in zip(d.get("time", []), d.get("temperature_2m_max", []), d.get("temperature_2m_min", [])):
            out[dt] = {"max": tx, "min": tn}
    except Exception as e:
        print("prognoza pogody:", e)
    return out

def weather_for(locations, start, end):
    distinct = {}
    for (la, lo) in locations.values():
        distinct.setdefault((round(la, 2), round(lo, 2)), (la, lo))
    cache, names = {}, {}
    for key, (la, lo) in distinct.items():
        cache[key] = archive_forecast(la, lo, start, end)
        names[key] = rev_geo(la, lo)
        time.sleep(1)  # grzecznie dla Nominatim
    res = {}
    for k, (la, lo) in locations.items():
        key = (round(la, 2), round(lo, 2))
        t = cache.get(key, {}).get(k, {})
        res[k] = {"temp_max": t.get("max"), "temp_noc": t.get("min"),
                  "miejsce": names.get(key, ""), "lat": round(la, 3), "lon": round(lo, 3)}
    return res


# ===================== training status / score =====================
def parse_training_status(ts):
    status = load = None
    try:
        latest = (ts.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {}
        for _dev, data in latest.items():
            if not isinstance(data, dict):
                continue
            status = data.get("trainingStatusFeedbackPhrase") or status
            atl = data.get("acuteTrainingLoadDTO") or {}
            load = atl.get("dailyTrainingLoadAcute") or atl.get("acuteTrainingLoad") or load
            break
    except Exception:
        pass
    return status, load

def score_map(resp, *score_keys):
    """Probuje wyciagnac mape data->wynik z odpowiedzi endurance/hill (rozne ksztalty)."""
    out = {}
    if not isinstance(resp, dict):
        return out
    # czasem jest lista pod jakims kluczem
    for v in resp.values():
        if isinstance(v, list):
            for it in v:
                if isinstance(it, dict):
                    dt = first(it, "calendarDate", "date")
                    sc = first(it, *score_keys)
                    if dt and sc is not None:
                        out[str(dt)[:10]] = sc
    return out


# ===================== glowna =====================
def main():
    g = Garmin()
    g.login(TOKENY)

    today = date.today()
    start = (today - timedelta(days=DNI)).isoformat()
    koniec = today.isoformat()

    wmap = {}
    wi = bezp(g.get_weigh_ins, start, koniec)
    if isinstance(wi, dict):
        for dz in (wi.get("dailyWeightSummaries") or []):
            dt = first(dz, "summaryDate", "calendarDate")
            w = (dz.get("latestWeight") or {})
            kg = w.get("weight") if isinstance(w, dict) else None
            if dt and kg:
                wmap[str(dt)[:10]] = round(kg / 1000.0, 1)

    locations = build_locations(g, start, koniec)
    weather = weather_for(locations, start, koniec)
    endurance = score_map(bezp(g.get_endurance_score, start, koniec), "overallScore", "enduranceScore")
    hill = score_map(bezp(g.get_hill_score, start, koniec), "overallScore", "hillScore", "strengthScore")

    rows = []
    for i in range(DNI):
        d = (today - timedelta(days=i)).isoformat()
        r = {"data": d, "waga": None, "kroki": None, "dystans_km": None, "kcal_aktywne": None,
             "pietra": None, "min_intensywne": None, "rhr": None, "hr_max": None, "hr_min": None,
             "stres": None, "stres_max": None, "bb_max": None, "bb_min": None,
             "hrv": None, "status": "", "sen": None, "sen_gleboki": None,
             "spo2": None, "spo2_min": None, "vo2max": None, "gotowosc": None, "recovery_h": None,
             "training_status": None, "training_load": None, "endurance": None, "hill": None,
             "body_fat": None, "muscle_kg": None, "body_water": None,
             "miejsce": "", "lat": None, "lon": None, "temp_max": None, "temp_noc": None}

        s = bezp(g.get_stats, d)
        if isinstance(s, dict):
            r["kroki"] = first(s, "totalSteps")
            dist = first(s, "totalDistanceMeters")
            r["dystans_km"] = round(dist / 1000.0, 2) if isinstance(dist, (int, float)) else None
            r["kcal_aktywne"] = first(s, "activeKilocalories")
            r["pietra"] = first(s, "floorsAscended")
            mod = s.get("moderateIntensityMinutes") or 0
            vig = s.get("vigorousIntensityMinutes") or 0
            r["min_intensywne"] = (mod + vig) if (mod or vig) else None
            r["rhr"] = first(s, "restingHeartRate")
            r["hr_max"] = first(s, "maxHeartRate")
            r["hr_min"] = first(s, "minHeartRate")
            r["stres"] = first(s, "averageStressLevel")
            r["stres_max"] = first(s, "maxStressLevel")
            r["bb_max"] = first(s, "bodyBatteryHighestValue", "bodyBatteryMostRecentValue")
            r["bb_min"] = first(s, "bodyBatteryLowestValue")
            r["spo2"] = first(s, "averageSpo2", "averageSpo2Value")
            r["spo2_min"] = first(s, "lowestSpo2", "lowestSpo2Value")

        r["waga"] = wmap.get(d)
        if d in wmap or r["waga"] is None:
            bc = bezp(g.get_body_composition, d)
            if isinstance(bc, dict):
                lst = bc.get("dateWeightList") or []
                if lst and isinstance(lst[0], dict):
                    e = lst[0]
                    if r["waga"] is None and e.get("weight"):
                        r["waga"] = round(e["weight"] / 1000.0, 1)
                    if e.get("bodyFat") is not None:
                        r["body_fat"] = round(e["bodyFat"], 1)
                    if e.get("muscleMass"):
                        r["muscle_kg"] = round(e["muscleMass"] / 1000.0, 1)
                    if e.get("bodyWater") is not None:
                        r["body_water"] = round(e["bodyWater"], 1)

        sl = bezp(g.get_sleep_data, d)
        if isinstance(sl, dict):
            dto = sl.get("dailySleepDTO") or {}
            r["sen"] = godz(dto.get("sleepTimeSeconds"))
            r["sen_gleboki"] = godz(dto.get("deepSleepSeconds"))
            if r["spo2"] is None:
                r["spo2"] = first(sl, "averageSpO2Value")
            if r["spo2_min"] is None:
                r["spo2_min"] = first(sl, "lowestSpO2Value")

        hv = bezp(g.get_hrv_data, d)
        if isinstance(hv, dict):
            summ = hv.get("hrvSummary") or {}
            r["hrv"] = first(summ, "lastNightAvg")
            r["status"] = first(summ, "status") or ""

        mm = bezp(g.get_max_metrics, d)
        if isinstance(mm, list) and mm and isinstance(mm[0], dict):
            gen = mm[0].get("generic") or {}
            r["vo2max"] = first(gen, "vo2MaxPreciseValue", "vo2MaxValue")

        tr = bezp(g.get_training_readiness, d)
        if isinstance(tr, list) and tr and isinstance(tr[0], dict):
            r["gotowosc"] = first(tr[0], "score")
            rec = first(tr[0], "recoveryTime")  # godziny
            if isinstance(rec, (int, float)):
                r["recovery_h"] = round(rec, 1)

        ts = bezp(g.get_training_status, d)
        if isinstance(ts, dict):
            st, ld = parse_training_status(ts)
            r["training_status"], r["training_load"] = st, ld

        r["endurance"] = endurance.get(d)
        r["hill"] = hill.get(d)

        w = weather.get(d, {})
        r["temp_max"], r["temp_noc"] = w.get("temp_max"), w.get("temp_noc")
        r["miejsce"], r["lat"], r["lon"] = w.get("miejsce", ""), w.get("lat"), w.get("lon")

        rows.append(r)
        time.sleep(PAUZA)

    rows.sort(key=lambda x: x["data"])

    # --- szyfrowanie AES-256-GCM (klucz z hasla przez PBKDF2) ---
    plaintext = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    passphrase = os.environ.get("DATA_PASSPHRASE") or getpass.getpass("Haslo szyfrowania danych: ")
    ITER = 200000
    salt, iv = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, ITER, dklen=32)
    ct = AESGCM(key).encrypt(iv, plaintext, None)
    blob = {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITER,
            "salt": base64.b64encode(salt).decode(),
            "iv": base64.b64encode(iv).decode(),
            "ct": base64.b64encode(ct).decode()}
    with open(PLIK, "w", encoding="utf-8") as f:
        json.dump(blob, f, separators=(",", ":"))

    def cnt(k):
        return sum(1 for r in rows if r[k] not in (None, ""))
    print(f"Zapisano {PLIK}: {len(rows)} dni")
    for k in ("waga", "hrv", "temp_noc", "miejsce", "body_fat", "training_status"):
        print(f"  {k}: {cnt(k)}")


if __name__ == "__main__":
    main()