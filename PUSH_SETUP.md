# Poranny briefing (Web Push) — konfiguracja

Powiadomienie push z gotowością na dziś przychodzi codziennie rano, kilka minut po
automatycznej aktualizacji danych z Garmina. Wszystko jest już w kodzie — trzeba tylko
raz uzupełnić klucze i włączyć powiadomienia na telefonie.

## Jak to działa

```
07:00  update.yml  → pobiera dane z Garmina, commit
07:12  briefing.yml → odszyfrowuje dane, liczy gotowość + sesję dnia,
                       wysyła Web Push do zarejestrowanych urządzeń (send_briefing.py)
telefon → Service Worker (sw.js) pokazuje powiadomienie
```

Rejestracja urządzenia: w apce dotykasz **„🔔 Włącz poranny briefing"** → przeglądarka pyta o
zgodę → subskrypcja trafia (przez Twój Cloudflare Worker, autoryzacja hasłem) do pliku
`push/subscriptions.json` w repo. `send_briefing.py` czyta ten plik i wysyła powiadomienia.

## Krok 1 — klucze VAPID

Publiczny klucz jest już w `index.html` (`VAPID_PUBLIC_KEY`). Prywatny dodaj jako **sekret repo**:

- `Settings → Secrets and variables → Actions → New repository secret`
  - `VAPID_PRIVATE_KEY` = *(prywatny klucz — przekazany osobno, base64url, 32 bajty)*
  - `VAPID_SUBJECT` = `mailto:twoj-email@example.com`

> Chcesz własną parę kluczy? Wygeneruj `npx web-push generate-vapid-keys`, wstaw publiczny do
> `VAPID_PUBLIC_KEY` w `index.html`, a prywatny do sekretu `VAPID_PRIVATE_KEY`.

Sekret `DATA_PASSPHRASE` jest już ustawiony (używa go update.yml) — briefing korzysta z tego samego.

## Krok 2 — Worker: uprawnienie do zapisu subskrypcji

`push/subscriptions.json` zapisuje Worker przez GitHub API, więc token Workera
(`GH_TOKEN`) musi mieć **contents: write** do repo (dotąd wystarczał actions: write).
Zaktualizuj token (fine-grained: Repository permissions → Contents: Read and write) i:

```
cd worker && wrangler deploy
```

Kod Workera (`worker/worker.js`) jest już gotowy — rozpoznaje żądanie z subskrypcją.

## Krok 3 — telefon (iPhone / Android)

- **iPhone (iOS 16.4+):** otwórz stronę w Safari → Udostępnij → **Dodaj do ekranu głównego**.
  Uruchom apkę z ikony (nie z Safari!), odblokuj hasłem, dotknij **🔔 Włącz poranny briefing**,
  zezwól na powiadomienia. Push działa tylko dla apki dodanej do ekranu głównego.
- **Android/Chrome:** wystarczy dotknąć **🔔 Włącz poranny briefing** i zezwolić.

## Test

Ręcznie odpal `Actions → Poranny briefing (push) → Run workflow`. Jeśli masz zarejestrowane
urządzenie i ustawione sekrety, powiadomienie przyjdzie w kilka sekund. Bez sekretów/subskrypcji
workflow po prostu kończy się bez wysyłki (nic nie psuje).

## Bezpieczeństwo

- Publiczny klucz VAPID w kodzie jest bezpieczny (z założenia jawny).
- Subskrypcja push pozwala wyłącznie **wysyłać Ci powiadomienia** — nie daje dostępu do danych zdrowotnych.
- Dane pozostają zaszyfrowane; briefing odszyfrowuje je tylko w GitHub Actions, w pamięci, do policzenia treści.
