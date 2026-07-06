# -*- coding: utf-8 -*-
"""
Wysyla poranny briefing jako Web Push do zarejestrowanych urzadzen.
Uruchamiany przez .github/workflows/briefing.yml krotko po aktualizacji danych Garmin.

Odczytuje zaszyfrowany plik danych (DATA_PASSPHRASE), liczy skrocona gotowosc dnia i
sesje z plan.json, po czym wysyla powiadomienie do kazdej subskrypcji z push/subscriptions.json.

Dziala tylko, gdy sa: subskrypcje (push/subscriptions.json) oraz sekrety VAPID.
W przeciwnym razie konczy sie spokojnie (exit 0), NIE psujac niczego.

Sekrety (GitHub Actions):
  DATA_PASSPHRASE     – to samo haslo, ktorym szyfrowane sa dane
  VAPID_PRIVATE_KEY   – prywatny klucz VAPID (base64url, 32 bajty) — patrz PUSH_SETUP.md
  VAPID_SUBJECT       – np. "mailto:ty@example.com"
"""
import os, sys, json, base64, hashlib
from datetime import date

PLIK = "garmin-7c1f93a2.json"          # ten sam plik co w update_garmin.py
SUBS = "push/subscriptions.json"
PLAN = "plan.json"

MEASURE_DOW = 6   # sobota — przypomnienie o pomiarach
CHECKIN_DOW = 7   # niedziela — podsumowanie tygodnia
ACTIVE_MIN = 20   # min. intensywne = "sesja" (proxy, bo log treningow jest tylko w przegladarce)


def _b64(s):
    return base64.b64decode(s)

def decrypt_blob(blob, passphrase):
    salt = _b64(blob["salt"]); iv = _b64(blob["iv"]); ct = _b64(blob["ct"])
    it = int(blob.get("iter", 200000))
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, it, dklen=32)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return json.loads(AESGCM(key).decrypt(iv, ct, None).decode("utf-8"))

def load_rows():
    try:
        with open(PLIK, "r", encoding="utf-8") as f:
            blob = json.load(f)
    except FileNotFoundError:
        return []
    if isinstance(blob, list):
        return blob
    pw = os.environ.get("DATA_PASSPHRASE")
    if not pw or not isinstance(blob, dict) or not blob.get("ct"):
        return []
    try:
        return decrypt_blob(blob, pw)
    except Exception as e:
        print("Nie udalo sie odszyfrowac danych:", e)
        return []


# ---- skrocona gotowosc dnia (spojna z logika apki, uproszczona) ----
def _avg(a):
    a = [x for x in a if isinstance(x, (int, float))]
    return sum(a) / len(a) if a else None

def readiness(rows):
    if not rows:
        return None
    r = rows[-1]
    prev = rows[:-1]
    hrv_base = _avg([x.get("hrv") for x in prev[-14:]])
    parts = []  # (score, weight)
    g = r.get("gotowosc")
    if isinstance(g, (int, float)):
        parts.append((max(0, min(100, g)), 3))
    hrv = r.get("hrv")
    if isinstance(hrv, (int, float)) and hrv_base:
        ratio = hrv / hrv_base
        parts.append((max(25, min(92, 25 + (92 - 25) * (ratio - 0.80) / (1.10 - 0.80))), 2))
    sen = r.get("sen")
    if isinstance(sen, (int, float)):
        parts.append((max(25, min(92, 25 + (92 - 25) * (sen - 4.5) / (7.8 - 4.5))), 1.5))
    bb = r.get("bb_max")
    if isinstance(bb, (int, float)):
        parts.append((max(0, min(100, bb)), 1))
    if not parts:
        return None
    score = round(sum(s * w for s, w in parts) / sum(w for _, w in parts))
    st = (r.get("status") or "").upper()
    if st == "POOR":
        score -= 8
    elif st in ("LOW", "UNBALANCED"):
        score -= 4
    score = max(0, min(100, score))
    zone = "green" if score >= 67 else ("yellow" if score >= 45 else "red")
    return {"score": score, "zone": zone}


def today_session():
    try:
        with open(PLAN, "r", encoding="utf-8") as f:
            plan = json.load(f)
    except Exception:
        return None
    phases = plan.get("phases") or []
    ph = next((p for p in phases if p.get("id") == plan.get("activePhase")), phases[0] if phases else None)
    if not ph:
        return None
    dow = date.today().isoweekday() % 7   # Pn=1..Nd=0 (jak w apce)
    day = (ph.get("days") or {}).get(str(dow)) or {}
    return {"name": day.get("name") or "Regeneracja", "type": day.get("type") or "rest",
            "phase": ph.get("subtitle") or ""}


def _in(row, start, end):
    try:
        d = date.fromisoformat(row.get("data"))
        return start <= d <= end
    except Exception:
        return False

def _delta(a, b):
    if a is None or b is None:
        return None
    return a - b

def activity_sessions(rows, week_start):
    from datetime import timedelta
    end = week_start + timedelta(days=6)
    n = 0
    for r in rows:
        try:
            d = date.fromisoformat(r.get("data"))
        except Exception:
            continue
        if week_start <= d <= end:
            mi = r.get("min_intensywne")
            if isinstance(mi, (int, float)) and mi >= ACTIVE_MIN:
                n += 1
    return n

def weekly_summary(rows):
    title = "📊 Podsumowanie tygodnia · Protokół"
    try:
        from datetime import date, timedelta
        if not rows:
            return title, "Zbieram dane — pelne podsumowanie po pierwszym tygodniu."
        today = date.today()
        this_mon = today - timedelta(days=today.weekday()) - timedelta(days=7)  # last complete week
        prev_mon = this_mon - timedelta(days=7)
        def wk(mon):
            end = mon + timedelta(days=6)
            return [r for r in rows if _in(r, mon, end)]
        cur, prev = wk(this_mon), wk(prev_mon)
        parts = []
        dw = _delta(_avg([r.get("waga") for r in cur]), _avg([r.get("waga") for r in prev]))
        if dw is not None:
            parts.append(f"waga {dw:+.1f} kg")
        pavg = _avg([r.get("bialko") for r in cur])
        if pavg is not None:
            parts.append(f"bialko sr. {round(pavg)} g")
        sess = activity_sessions(rows, this_mon)
        parts.append(f"~{sess} sesji")
        ds = _delta(_avg([r.get("sen") for r in cur]), _avg([r.get("sen") for r in prev]))
        if ds is not None:
            parts.append(f"sen {ds:+.1f} h")
        body = " · ".join(parts) if parts else "Tydzien zaliczony — otworz apke po szczegoly."
        body += " · pelne serie w apce."
        return title, body
    except Exception as e:
        print("weekly_summary blad:", e)
        return title, "Podsumowanie tygodnia — otworz apke."


def build_message(rows):
    dow = date.today().isoweekday()   # 1=Pn..7=Nd
    if dow == CHECKIN_DOW:
        try:
            return weekly_summary(rows)
        except Exception:
            pass
    rd = readiness(rows)
    sess = today_session() or {"name": "Twój plan", "type": "rest"}
    emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(rd["zone"], "⚪") if rd else "⚪"
    label = {"green": "Gotowy", "yellow": "Lekko", "red": "Regeneracja"}.get(rd["zone"], "") if rd else ""
    score = f" {rd['score']}" if rd else ""
    title = f"{emoji} {label}{score} · Protokół"
    if rd and rd["zone"] == "red" and sess["type"] != "rest":
        tip = f"Dziś odpuść — regeneracja zamiast: {sess['name']}."
    elif rd and rd["zone"] == "green" and sess["type"] == "strength":
        tip = f"Dziś: {sess['name']} — masz zapas, możesz docisnąć."
    else:
        tip = f"Dziś: {sess['name']}."
    if dow == MEASURE_DOW:
        tip += " · ⚖️ dziś pomiary: waga na czczo + talia."
    return title, tip


def main():
    try:
        with open(SUBS, "r", encoding="utf-8") as f:
            subs = json.load(f)
    except FileNotFoundError:
        print("Brak push/subscriptions.json — nic do wyslania."); return
    if not isinstance(subs, list) or not subs:
        print("Brak subskrypcji."); return

    vapid_key = os.environ.get("VAPID_PRIVATE_KEY")
    vapid_sub = os.environ.get("VAPID_SUBJECT") or "mailto:admin@example.com"
    if not vapid_key:
        print("Brak VAPID_PRIVATE_KEY — pomijam wysylke."); return

    rows = load_rows()
    title, body = build_message(rows)
    payload = json.dumps({"title": title, "body": body, "url": "./"}, ensure_ascii=False)
    print("Briefing:", title, "|", body)

    try:
        from pywebpush import webpush, WebPushException
    except Exception as e:
        print("Brak biblioteki pywebpush:", e); return

    sent = dead = 0
    for s in subs:
        try:
            webpush(subscription_info=s, data=payload,
                    vapid_private_key=vapid_key, vapid_claims={"sub": vapid_sub})
            sent += 1
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):
                dead += 1   # subskrypcja wygasla — mozna by ja usunac przy nastepnej rejestracji
            print("Push blad:", code, str(e)[:160])
        except Exception as e:
            print("Push wyjatek:", str(e)[:160])
    print(f"Wyslano: {sent}, wygaslych: {dead}, wszystkich: {len(subs)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Briefing nigdy nie moze wywrocic workflow.
        print("send_briefing nieoczekiwany blad:", e)
        sys.exit(0)
