# Odświeżanie danych z Garmina jednym kliknięciem w apce

## Jak to działa (i dlaczego bezpiecznie)

```
Apka (PWA)  --POST {auth=hash(hasła)}-->  Cloudflare Worker  --token GitHub-->  GitHub Actions
   ^                                                                                   |
   |                                              nowy, zaszyfrowany garmin-*.json  <---+
   +--- co 12 s sprawdza plik, aż się zmieni → odszyfrowuje hasłem → pokazuje ----------+
```

- Token GitHuba leży **tylko** w Workerze (jako sekret). Nigdy nie trafia do kodu strony (a strona na GitHub Pages jest publiczna).
- Worker dostaje **wyłącznie hash** Twojego `DATA_PASSPHRASE` (PBKDF2), nie samo hasło — więc **nie jest w stanie odszyfrować** Twoich danych zdrowotnych. Sprawdza tylko, czy hash pasuje, i jeśli tak — uruchamia workflow.
- Bez poprawnego hasła nikt nie odpali Twojego workflow (odpowiedź 401).

Potrzebujesz: konta **Cloudflare** (darmowy plan wystarcza) i zainstalowanego **Node.js**.

---

## Krok 1 — token GitHuba (fine-grained, minimalny zakres)

1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. **Resource owner:** Twoje konto. **Repository access:** *Only select repositories* → zaznacz **`flechow/health`**.
3. **Permissions → Repository permissions → Actions: _Read and write_** (to jedyne potrzebne; „Metadata: Read-only" dołączy się samo).
4. Wygeneruj i **skopiuj token** (widać go tylko raz).

Ten token może co najwyżej uruchamiać workflow w tym jednym repo — nie ma dostępu do kodu ani innych repozytoriów.

## Krok 2 — policz REFRESH_AUTH_HASH ze swojego hasła

W katalogu `worker/`:

```bash
cd worker
node derive-auth.mjs
# wpisz swoje DATA_PASSPHRASE, gdy zapyta — wypisze długi hex
```

Skopiuj wynik (64 znaki hex). To jest `REFRESH_AUTH_HASH`. Liczony jest identycznie jak w przeglądarce (PBKDF2-SHA256, sól `protokol-refresh-auth-v1`, 100000 iteracji).

## Krok 3 — wdróż Workera

```bash
npm install -g wrangler      # jednorazowo
cd worker
wrangler login               # otworzy przeglądarkę
wrangler deploy              # wypisze adres, np. https://protokol-refresh.TWOJ.workers.dev
```

Zapisz ten adres — wklejasz go w kroku 5.

## Krok 4 — ustaw sekrety Workera

```bash
wrangler secret put GH_TOKEN            # wklej token z kroku 1
wrangler secret put REFRESH_AUTH_HASH   # wklej hash z kroku 2
```

(Zmienne jawne `GH_REPO`, `GH_WORKFLOW`, `GH_REF`, `REFRESH_DAYS` są już w `wrangler.toml`.)

## Krok 5 — wpnij adres Workera w apkę

W `index.html` znajdź linię:

```js
const REFRESH_URL="https://REPLACE-ME.workers.dev";
```

Wpisz adres z kroku 3, zacommituj i wypchnij:

```bash
git add index.html && git commit -m "Podepnij Worker odswiezania" && git push
```

Gotowe. W apce po odblokowaniu hasłem pojawi się przycisk **„🔄 Odśwież dane z Garmina"**. Po kliknięciu apka uruchamia pobranie i czeka (do ~3 min), aż pojawią się świeże dane.

## Krok 6 (zalecane) — zawęź dostęp do Workera

W `wrangler.toml` zmień `ALLOW_ORIGIN = "*"` na dokładny adres Twojej strony Pages (np. `"https://flechow.github.io"`), potem `wrangler deploy`. Autoryzacja hasłem działa niezależnie, ale to dodatkowa warstwa.

---

## Test i rozwiązywanie problemów

- **Kliknięcie nic nie robi / „Brak skonfigurowanego adresu"** → nie wpisałeś `REFRESH_URL` w `index.html` (krok 5).
- **401 / „hasło nie pasuje"** → `REFRESH_AUTH_HASH` policzony z innego hasła niż wpisujesz w apce. Przelicz krok 2 tym samym hasłem.
- **Błąd 422 z GitHuba** → workflow nie zna inputu `days`. Upewnij się, że wypchnąłeś nową wersję `.github/workflows/update.yml` (ma sekcję `inputs: days`).
- **Błąd 403/404 z GitHuba** → token bez uprawnienia *Actions: Read and write* albo zły `GH_REPO`.
- **Podgląd, czy zadanie ruszyło** → zakładka **Actions** w repo; zobaczysz uruchomienie „Aktualizacja danych Garmin".

## Czas i limity

- Szybkie odświeżanie pobiera tylko ostatnie **3 dni** (`REFRESH_DAYS` w `wrangler.toml`) i scala z historią — zwykle ~1–2 min z narzutem na build Pages.
- Codzienny cron (05:00 UTC) dalej robi pełne 120 dni.
- Repo prywatne: GitHub Actions ma darmowy limit minut/mies. — przy ~1–2 min na odświeżenie spokojnie wystarcza na setki kliknięć.

## Alternatywa bez Cloudflare — Val.town

Jeśli nie chcesz instalować `wrangler`: załóż konto na val.town, stwórz „HTTP val", wklej logikę z `worker/worker.js` (dostosuj `Deno.env`/sekrety wg ich dokumentacji), ustaw sekrety `GH_TOKEN` i `REFRESH_AUTH_HASH`, i użyj adresu vala jako `REFRESH_URL`. Model bezpieczeństwa jest ten sam.
