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
import sys, json, os, time, base64, hashlib, getpass, urllib.parse, requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from datetime import date, timedelta
from garminconnect import Garmin
try:
    import fitatu
except Exception:
    fitatu = None

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


# ===================== szyfrowanie =====================
def _kdf(passphrase, salt, iters):
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iters, dklen=32)

def encrypt_rows(rows, passphrase, iters=200000):
    plaintext = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_kdf(passphrase, salt, iters)).encrypt(iv, plaintext, None)
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": iters,
            "salt": base64.b64encode(salt).decode(),
            "iv": base64.b64encode(iv).decode(),
            "ct": base64.b64encode(ct).decode()}

def decrypt_blob(blob, passphrase):
    salt = base64.b64decode(blob["salt"]); iv = base64.b64decode(blob["iv"]); ct = base64.b64decode(blob["ct"])
    pt = AESGCM(_kdf(passphrase, salt, int(blob.get("iter", 200000)))).decrypt(iv, ct, None)
    return json.loads(pt.decode("utf-8"))

def load_existing_rows(passphrase):
    """Wczytuje i odszyfrowuje istniejacy PLIK (do scalania w trybie szybkim). Pusto, gdy brak/blad."""
    try:
        with open(PLIK, "r", encoding="utf-8") as f:
            blob = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print("Nie udalo sie wczytac istniejacego pliku:", e); return []
    try:
        if isinstance(blob, list):        # zgodnosc wsteczna: kiedys niezaszyfrowana tablica
            return blob
        if isinstance(blob, dict) and blob.get("ct"):
            return decrypt_blob(blob, passphrase)
    except Exception as e:
        print("Nie udalo sie odszyfrowac istniejacego pliku (zmiana hasla?):", e)
    return []

def merge_rows(old, new):
    """Scala historie: swieze dni (new) nadpisuja stare wpisy o tej samej dacie, reszta zostaje."""
    by = {r["data"]: r for r in old if isinstance(r, dict) and r.get("data")}
    for r in new:
        if isinstance(r, dict) and r.get("data"):
            by[r["data"]] = r
    return sorted(by.values(), key=lambda x: x["data"])


NUTRI_KEYS = ("bialko", "kcal_spozyte", "wegle", "tluszcz", "blonnik", "fitatu")


def carry_forward_nutrition(old_rows, new_rows):
    """Kopiuje pola odzywiania ze starych wierszy na wiersze o tej samej dacie,
    ktore ich jeszcze nie maja. Chroni historie przy pelnym przebiegu (bez merge)."""
    old_by = {r["data"]: r for r in (old_rows or []) if isinstance(r, dict) and r.get("data")}
    for r in new_rows:
        if not isinstance(r, dict): continue
        src = old_by.get(r.get("data"))
        if not src:
            continue
        for k in NUTRI_KEYS:
            if k not in r and k in src:
                r[k] = src[k]


def enrich_nutrition(rows, fetch_fn, days=14):
    """Dla ostatnich `days` dni ustawia pola odzywiania z fetch_fn(date)->dict.
    Pomija dni bez danych (same None)."""
    window = [r for r in rows if r.get("data")][-days:]
    for r in window:
        nutri = fetch_fn(r["data"])
        if not isinstance(nutri, dict):
            continue
        if all(nutri.get(k) is None for k in ("bialko", "kcal_spozyte")):
            continue
        for k in NUTRI_KEYS:
            r[k] = nutri.get(k)


# ===================== budowanie wierszy =====================
def build_rows(g, start, koniec):
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

    end_d = date.fromisoformat(koniec)
    n = (end_d - date.fromisoformat(start)).days + 1

    rows = []
    for i in range(n):
        d = (end_d - timedelta(days=i)).isoformat()
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
    return rows


# ===================== glowna =====================
def main():
    passphrase = os.environ.get("DATA_PASSPHRASE")
    if not passphrase:
        if sys.stdin and sys.stdin.isatty():
            passphrase = getpass.getpass("Haslo szyfrowania danych: ")
        else:
            raise SystemExit("BLAD: brak DATA_PASSPHRASE w srodowisku. "
                             "Ustaw sekret i przekaz go przez 'env:' w kroku workflow.")

    # DNI_OVERRIDE (z workflow_dispatch input 'days'): szybkie odswiezanie tylko ostatnich N dni,
    # scalane z historia z istniejacego pliku. Puste => pelne pobranie DNI dni (cron).
    override = (os.environ.get("DNI_OVERRIDE") or "").strip()
    fast, dni = False, DNI
    if override:
        try:
            v = int(override)
            if v > 0:
                dni, fast = v, True
        except ValueError:
            pass

    g = Garmin()
    g.login(TOKENY)

    today = date.today()
    koniec = today.isoformat()
    start = (today - timedelta(days=dni - 1)).isoformat()

    rows = build_rows(g, start, koniec)

    if fast:
        old = load_existing_rows(passphrase)
        if old and len(old) >= len(rows):
            rows = merge_rows(old, rows)
            print(f"Tryb szybki: scalono {dni} swiezych dni z historia ({len(old)}) -> {len(rows)} dni")
        else:
            # Brak uzytecznej historii — zeby jej nie utracic, dociagamy pelne dane.
            print("Tryb szybki bez historii — dociagam pelne dane, by jej nie skasowac.")
            start = (today - timedelta(days=DNI - 1)).isoformat()
            rows = build_rows(g, start, koniec)

    # ---- odzywianie z Fitatu (opcjonalne; nigdy nie psuje aktualizacji Garmina) ----
    f_email = os.environ.get("FITATU_EMAIL")
    f_pw = os.environ.get("FITATU_PASSWORD")
    if fitatu and f_email and f_pw:
        try:
            old_nutri = old if fast else load_existing_rows(passphrase)
            carry_forward_nutrition(old_nutri, rows)
            fclient = fitatu.login(f_email, f_pw)
            f_days = int(os.environ.get("FITATU_DNI") or 14)
            enrich_nutrition(rows, lambda d: fitatu.fetch_normalized(fclient, d), days=f_days)
            print(f"Fitatu: uzupelniono odzywianie dla ostatnich {f_days} dni")
        except Exception as e:
            print("Fitatu pominiete (blad):", str(e)[:200])
    else:
        print("Fitatu: modul niedostepny lub brak FITATU_EMAIL/FITATU_PASSWORD — pomijam odzywianie.")

    blob = encrypt_rows(rows, passphrase)
    with open(PLIK, "w", encoding="utf-8") as f:
        json.dump(blob, f, separators=(",", ":"))

    def cnt(k):
        return sum(1 for r in rows if r.get(k) not in (None, ""))
    print(f"Zapisano {PLIK}: {len(rows)} dni")
    for k in ("waga", "hrv", "temp_noc", "miejsce", "body_fat", "training_status", "bialko", "kcal_spozyte"):
        print(f"  {k}: {cnt(k)}")


if __name__ == "__main__":
    main()
