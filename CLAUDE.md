# CLAUDE.md — cee-rental-yield

Ten plik opisuje wszystko, czego potrzebujesz, żeby zbudować Actora na Apify w tym repozytorium. Czytaj go w całości przed pierwszą zmianą i wracaj do niego przy każdej decyzji. Jeśli coś tu jest oznaczone **[DO WERYFIKACJI]**, sprawdź to na prawdziwej odpowiedzi serwisu (fixture albo żywe zapytanie) zanim na tym zbudujesz. Nigdy nie wymyślaj nazw pól — bierz je z fixture.

Repo: `https://github.com/data-nest-dev/cee-rental-yield` · Właściciel: datanest.dev (konto Apify: `pl-datanest`)

---

## 0. Stan na 2026-11-20 (M3 zamknięte, M4: Actor opublikowany w Store) — czytaj najpierw

**M1, M2 i M3 ukończone** (test H zaliczony, Actor `data-nest/cee-rental-yield` buduje z `main`). **Teraz M4 (publikacja w Store): decyzje właściciela z 2026-11-19 w punkcie 15 poniżej są źródłem prawdy.**

**Decyzje właściciela (obowiązują):**
1. **Zero ryzyka prawnego i wizerunkowego.** Źródło wchodzi do Actora tylko, jeśli `robots.txt` pozwala na używane ścieżki dla `User-agent: *`. Wątpliwości = nie wchodzi. Sreality wyłączone.
2. **Nazwa produktu:** „Rental Yield & Deal Score” (bez krajów).
3. **Bramka, kryterium 3:** ≥ 70% oczyszczonych ofert sprzedaży porównanych na poziomie dzielnicy (`saleGroupLevel == "district"`); mianownik = wszystkie oczyszczone oferty sprzedaży miasta. Metryka grup `district × rooms` — tylko informacyjnie.
4. **Otodom: `by=LATEST&direction=DESC` + `limit=72`.** Próba to bieżąca podaż — raportujemy jej wiek i udział (`sample.*`).
5. **Domyślne próbkowanie (2026-11-18):** `samplingMode = "perDistrict"`, kwota na dzielnicę i stronę rynku `max(150, ceil(1500 / liczba_dzielnic))` — Warszawa, Kraków, Katowice 150, Wrocław 300. W inpucie `maxListingsPerDistrict = 0` = „automatycznie według tej formuły” (§10).
6. **Wersja 1.0 tylko z Polską:** Warszawa, Kraków, Wrocław; Katowice wybieralne, nie reklamowane. Czeskie źródło w 1.1: `reality.idnes.cz` — **teraz nie piszemy parsera**. `bezrealitky.cz` odpada (`robots.txt` blokuje ścieżkę `search`, której używa wewnętrznie).
7. **Weryfikacja ręczna M2 zaliczona** (2026-11-18): właściciel sprawdził 20 ofert z `storage/m2_review_sample.csv` w przeglądarce — cena, metraż, pokoje i dzielnica się zgadzają.
8. **Proxy (konto właściciela):** datacenter — tylko grupa `BUYPROXIES94952` (5 adresów IP z USA, w cenie planu); residential — dostępne, $8/GB + transfer, z wyborem kraju (PL); dostęp do proxy spoza Actorów wyłączony, więc **lokalne testy idą bez proxy**. Strategia M3: pierwszy test na platformie z datacenter (rotacja sesji między 5 IP); **blokady > 5% → zatrzymaj się i zgłoś**; residential PL dopiero po decyzji właściciela. Kod obsługuje oba warianty przez `proxyConfiguration` z inputu; klucz kraju z inputu to `apifyProxyCountry` (potwierdzone w źródle SDK 4.3.0, §10).
9. **Model opłat:** przy pay-per-event koszty platformy (compute, proxy, transfer) płaci autor, nie klient — każdy koszt w M3 licz z tego punktu widzenia (zysk = 0,8 × przychód − koszty platformy, §15).
10. **Tryb budżetowy (2026-11-18):** dane pobieramy w całości przed fazą push, więc przy bardzo niskim limicie kosztu autor płaciłby pełny compute za grosze przychodu. Na starcie odczytaj limit (`ACTOR_MAX_TOTAL_CHARGE_USD` przez `Actor.get_charging_manager().get_max_total_charge_usd()`; bez limitu SDK zwraca `Decimal('inf')`; poza PPE `get_pricing_info().is_pay_per_event == False` → bez redukcji). Jeśli `0,8 × limit < szacowany koszt autora × 1,5` → tylko pierwsze miasto, `samplingMode = "city"`, `maxListingsPerSide = 360` (zakres jak prefill); **`mode` bez zmian** (korekta 2026-11-19: użytkownik nigdy nie płaci za typ zdarzenia, o który nie prosił; przy `scoreListings` tryb budżetowy dodaje do datasetu tylko darmowe rekordy `low`, nigdy `area-yield`). Nigdy błąd z powodu niskiego budżetu: Succeeded i niepusty dataset. Stałe modelu kosztu w jednym miejscu: `src/budget.py` (źródło każdej stałej w komentarzu; cena CU = założenie do kalibracji w teście H). Progi (512 MB, datacenter): domyślne uruchomienie ≈ $0,029, prefill ≈ $0,0053; z residential PL ≈ $1,69. README zaleca minimum $0,05 (residential: $2).

11. **Decyzje 2026-11-19 (po briefie M3 v2):**
    1. `maxScoredListings` (integer ≥ 0, domyślnie 1000, 0 = wszystkie; „Return at most this many listings, best deals first. 0 = all.”): limit po wszystkich filtrach i po sortowaniu po `dealScore`. Przykład ceny domyślnego uruchomienia (Warszawa + Kraków), run `3cFnNnMtkzpmtPDIb` (256 MB; `RUN_SUMMARY`: 109 grup `areaYield`, z czego `events.area-yield.chargeable` = 107, 2 grupy `low` darmowe; `scored-listing.chargeable` = 1000): 107 × $0,02 + 1000 × $0,004 = **$6,14** (poprawka 2026-11-20; wcześniej błędnie $6,18).
    2. Bez „charges nothing”: przy porażce nasze zdarzenia nie są naliczane, Apify pobiera tylko opłatę startową $0,00005 (`apify-actor-start`).
    3. W monitoringu grupy (`areaYield`) zależą od `mode`; README zaleca `scoreListings` dla harmonogramów.
    4. (J9) Gdy jedna strona rynku miasta zawiedzie (blokada / błąd), całe miasto jest pomijane z powodem w `RUN_SUMMARY`; pozostałe miasta idą dalej. *(Potwierdzone przez właściciela 2026-11-19: to jego decyzja z 2026-11-18.)*
    5. (J10) `rooms` jako enum tekstowy `["1","2","3","4+"]` (edytor multi-select); API przyjmuje też liczby 1–4. *(Potwierdzone przez właściciela 2026-11-19.)*
    6. Akceptacja: prefill ≠ default, cichy run monitoringu = Succeeded, brak `flatten` w widokach w M3 (wraca w M4).
    7. *(Zastąpione decyzją 14.8: kalibracja z rachunku Run 2.)* `USD_PER_COMPUTE_UNIT` zostawał $0,40 do testu H.
12. **Raporty i limit (poprawki 2026-11-19):** przed push tylko wstępny `RUN_SUMMARY` (liczniki, bez wartości yield i cen); `YIELD_REPORT` po każdej wypchniętej partii, wyłącznie z wypchniętymi grupami (w `scoreListings`: tylko darmowe `low`); handler `ABORTING` zapisuje to, co wypchnięto. Pojemność budżetu liczona tak, by suma opłat była **ściśle poniżej** limitu: dokumentacja PPE: „Once it's reached, `Actor.charge()` stop charging and `Actor.pushData()` stops pushing data over the limit. The platform then aborts the run automatically.” — nigdy nie dochodzimy do limitu, więc run kończy się normalnie (Succeeded). Darmowe rekordy idą przed płatnymi. `RUN_SUMMARY`: `scoredAvailable`, `scoredReturned`, `prefillRun`.
13. **Tożsamość git i przeniesienie repo (stan 2026-11-20):** lokalny `git config` repo: `data-nest-dev <contact@datanest.dev>`; wszystkie 59+ commitów `main` mają tylko tę tożsamość (autor i committer), bez imienia, nazwiska i nazwy hosta; tagów brak. Gałąź `origin/latest-72` (24 commity z prawdziwą tożsamością, `73bf907`…`7b9df88`) usunięto 2026-11-19, ale commity zostają osiągalne przez `refs/pull/1/head` (zamknięty PR #1) — zgłoszenie do GitHub Support było w toku. **Decyzja właściciela (2026-11-20): przeniesienie na nowe, czyste repo** z samym `main`; nazwa i URL `origin` mają pozostać `data-nest-dev/cee-rental-yield`. Stare repo zostaje przemianowane na `cee-rental-yield-old` i **jest do usunięcia razem z purge po udanym buildzie w Apify** z nowego repo (po podmianie źródła Git i deploy key). Z lokalnego klonu usunięto obiekty z `refs/pull/1/head` (`FETCH_HEAD`, `reflog expire`, `gc --prune=now`; `git cat-file -t 7b9df88` → błąd). Lokalne kopie `main-backup-identity` itd. nie istnieją. Push na `main` tylko na polecenie właściciela (punkt 15.7).

14. **Decyzje 2026-11-19 po Run 1 testu H (domyślny input na platformie, datacenter: 2/215 blokad, 267 s, 134 MB):**
    1. Kwota próbkowania bez zmian: `max(150, ceil(1500 / liczba_dzielnic))`. Warunek czasu domyślnego runu: **< 8 min** (codzienny test Apify używa prefillu). Pomiar kwoty 120 (lokalnie): 160 zapytań, bramka 96,6% / 93,0% — odrzucone.
    2. `src/budget.py`: `SECONDS_PER_REQUEST = 1.19` (Run 1). `FIXED_SECONDS`, zapytania na dzielnicę i `BYTES_PER_REQUEST` bez zmian do ≥ 3 runów (przeszacowanie jest bezpieczne); pamięć i `USD_PER_COMPUTE_UNIT` po Run 2 i Usage.
    3. Dedupe najmu po (dzielnica, pokoje, metraż, cena, piętro, typ ogłoszeniodawcy; brak pola = pusta wartość): `rejected.near_duplicate_rent`. Dla sprzedaży (zmiana 2026-11-20): identyczne oferty (miasto, dzielnica, pokoje, metraż, cena) scalane do reprezentanta o najniższym `listingId`; `identicalListingIds`, `RUN_SUMMARY.sides.sale.identicalMerged`; monitoring śledzi wszystkich członków grupy. `suspectRooms`: metraż/pokoje < 8 → tylko poziom `city`. `RUN_SUMMARY.sides.*.market` = ALL|SECONDARY.
    4. Sortowanie wyniku: `dealScore` malejąco, potem `discountVsMedianPct` malejąco.
    5. `scoredListing.flags` (lista): `share`, `auction` — oferta wykluczona z median i z wyniku (liczniki `rejected.share_listing`, `rejected.auction_listing`); `needsRenovation` — zostaje w wyniku i medianie, z flagą; `outlier` (rabat > 40% względem mediany grupy; jeden warunek) — tylko flaga. `title` służy wyłącznie do klasyfikacji w pamięci (`src/flags.py`), nigdy do wyniku ani logów. Słownik słów kluczowych wstępny; poprawki po przeglądzie top 15 przez właściciela.
    5a. `share` tylko dla udziału we własności lokalu („udział w mieszkaniu/lokalu”, „1/2 udziału”, „sprzedam udział”; ułamki tylko obok słowa udział/własności); frazy garażowe i gruntowe jawnie wykluczone. `RUN_SUMMARY.cities.*.sides.rent.nearDuplicateRentShare` = odrzucone `near_duplicate_rent` / pobrane; > 15% na żywych danych zgłaszać.
    5b. `outputCurrency` usunięte (input, kod, README): wynik zawsze ma EUR i walutę lokalną.
    8. **Test H zaliczony (2026-11-19, datacenter `BUYPROXIES94952`).** Run 0 (prefill): Succeeded, ~20 s. Run 1 (domyślny, 512 MB): 268 s, 2/215 blokad (Kraków/sprzedaż, sesje s2 i s3 na pierwszym zapytaniu), szczyt pamięci 133,7 MB. Run 2 (domyślny, 256 MB): 342 s (1,45 s/zapytanie), 124 MB, koszt $0,012 (compute 0,0238 CU = $0,005; 1109 zapisów datasetu = $0,006; 20 zapisów KV = $0,001; transfer i proxy $0). **Pamięć domyślna zostaje 512 MB (decyzja właściciela).**
    9. **Model kosztu autora (`src/budget.py`, kalibracja z Run 2, zaakceptowana):** `CU × $0,21 + rekordy × $0,0000054 + 20 zapisów KV × $0,00005`; `SECONDS_PER_REQUEST` 1,19 przy ≥ 512 MB i 1,45 poniżej. Szacunek Run 2 $0,0125 (zmierzone $0,012). Progi `minMaxChargeUsd`: domyślne 512 MB $0,0304, 256 MB $0,0235, prefill 512 MB $0,0087 (zastępuje progi z decyzji 10: $0,029 / $0,0053). `FIXED_SECONDS` (30), zapytania na dzielnicę (60) i `BYTES_PER_REQUEST` bez zmian do ≥ 3 runów.
    6. Brief M3 nie jest już prowadzony jako artifact: decyzje w CLAUDE.md, raporty w czacie.
    7. Test limitu kosztu na platformie niepotrzebny: pokrywa go lokalny test integracyjny (`tests/test_integration_sdk.py`, decyzja z 2026-11-18).

15. **Decyzje M4 (właściciel, 2026-11-19) — źródło prawdy:**
    1. **Dwa datasety.** `actor.json` → `storages.datasets: {default, yields}` (pliki `dataset_schema.json`, `yields_dataset_schema.json`), `output_schema.json` linkuje oba (`{{links.apiDefaultDatasetUrl}}/items`, `{{storages.datasets.yields.apiUrl}}/items`). Rekordy `areaYield` idą do aliasu `yields`, domyślny dataset ma tylko `scoredListing`. **Wyjątek: `mode = yieldReport`** — yieldy zostają w datasecie domyślnym. **Powód (do README): API** — `run-sync-get-dataset-items` czyta tylko dataset domyślny i przy `yieldReport` zwróciłby pustą odpowiedź; **nie** test Store (ten uruchamia prefill, `mode = both`). Brak syntetycznego `apify-default-dataset-item` dla aliasu (SDK 4.3.0: `is_default_dataset` = False dla aliasu); `Actor.push_data` pisze tylko do domyślnego, więc dla aliasu: `dataset.push_data` → `Actor.charge(event_name, count)`, a pojemność (`ApifyActorPort.capacity(default_dataset=False)`, bez ceny syntetycznej) liczona **przed** pushem; kolejność: pojemność → push → charge (`Actor.charge` przy przekroczeniu budżetu nalicza „fitting + 1”, więc batch jest zawsze przycinany do pojemności). Zweryfikowane w kodzie SDK (`.venv`, `_actor.py`, `_charging.py`, `_dataset_client.py`) i testem integracyjnym z prawdziwym SDK (`tests/test_integration_sdk.py`). `RUN_SUMMARY.yieldsDataset` = `yields` albo `default`.
    2. **Proxy.** `default` i `prefill` = `{"useApifyProxy": true}` bez grup (tryb automatyczny; dedykowana grupa `BUYPROXIES94952` jest używalna tylko przez właściciela, docs: „only you can use them”). Odmowa proxy (HTTP 407/597, `CONNECT tunnel failed`, błąd `create_proxy_configuration`) → `ProxyAccessError` → run kończy się błędem z czytelnym komunikatem, zero opłat (`src/http.py`, `PROXY_ACCESS_MESSAGE`). README nie poleca RESIDENTIAL; mówi tylko, że można podać własne `proxyConfiguration`. **Nieweryfikowane w docs:** czy automatyczne IP datacenter użytkownika dają < 5% blokad na Otodom — weryfikacja po publikacji przez Insights i Issues (zastąpione przez 15.11: brak drugiego konta).
    3. **Monitoring.** Błąd otwarcia named store `cee-rental-yield-state` → ostrzeżenie w `RUN_SUMMARY.monitoring.warning` (`stateAvailable: false`), run bez stanu (zwykły run, `changeType = null`, stan nie zapisywany); błąd zapisu stanu po dostarczeniu wyników → tylko ostrzeżenie. **Test w Console (Limited permissions):** `{"cities":["wroclaw"],"samplingMode":"city","maxListingsPerSide":360,"mode":"scoreListings","onlyNewOrChanged":true,"watchlistName":"m4test"}` dwa razy pod rząd; run 1: wszystkie `new` i w Storage pojawia się `cee-rental-yield-state`; run 2: prawie pusty wynik, `Succeeded`. Powtórzenie z drugiego konta nie jest planowane (zastąpione przez 15.11: brak drugiego konta).
    4. **Teksty Store (EN).** Tytuł: „Poland Rental Yield & Property Deal Score” (w `actor.json`). Katowice nie występują w tekstach (dostępne w inpucie, nie reklamowane). SEO description (145 znaków, sprawdzone kodem): „Web scraping of Polish property listings: gross rental yield per district and a 0–100 deal score for every flat, in EUR. Warsaw, Kraków, Wrocław.” W tekstach marketingowych bez słowa „scraper”.
    5. **Cena przykładowa domyślnego uruchomienia (ujednolicona 2026-11-20):** **$6,14** = 107 płatnych grup × $0,02 + 1000 × $0,004; źródło: `RUN_SUMMARY` runu `3cFnNnMtkzpmtPDIb` (109 grup `areaYield`, `events.area-yield.chargeable` = 107, `scored-listing.chargeable` = 1000; 2 grupy `low` są darmowe). Ta sama wartość i ID w README i §0.11.1. Przy `maxScoredListings: 0` (ok. 6 150 ofert): ≈ $26,74.
    6. **Zasady Apify (docs, 2026-11-19):** podwyżka ceny, nowe płatne zdarzenie i zmiana modelu = powiadomienie 14 dni, nie do anulowania, max raz na miesiąc na Actora; obniżka, usunięcie zdarzenia i zmiana opisu — od razu; bez płacących użytkowników zmiany są natychmiastowe. Checklista monetyzacji: model PPE; `area-yield` $0.02, `scored-listing` $0.004; usunąć `apify-default-dataset-item`; `apify-actor-start` zostaje (nie naliczać z kodu); „Pay per event + usage” wyłączone; zdarzenie główne = `scored-listing`; minimalny max cost $0.05.
    7. **Zasada pracy z gitem (właściciel, 2026-11-20): push na `main` tylko na wyraźne polecenie właściciela.** Commity na gałęziach lokalnych bez pusha i bez merge'a, dopóki właściciel nie poleci. (Commit `bddaf9d` został wypchnięty na `main` bez takiego polecenia — nie powtarzać.)
    8. **Czat (Opus) a Apify (właściciel, 2026-11-20).** Czat ma connector Apify i może uruchamiać runy testowe na koncie właściciela **tylko za jego zgodą**, z podanym inputem, buildem i `maxTotalChargeUsd`. Zdarzenia PPE z runów właściciela nie są mu naliczane (`accountedChargedEventCounts` = 0, zaobserwowane 2026-11-20; mechanizm niezweryfikowany w docs).
    9. **Przekierowania `_next/data` (2026-11-20, build 0.0.24 potwierdzony na platformie).** Przy `market=SECONDARY` trasa danych zwraca 200 z `pageProps.__N_REDIRECT` (ścieżka z segmentem `,rynek-wtorny`). Kod idzie za nim maks. raz, a poznaną ścieżkę zapamiętuje na czas jednego fetchu (miasto × strona rynku × lokalizacja), więc kolejne strony to 1 zapytanie. Cel poza `/pl/wyniki/` jest odrzucany; powtórne przekierowanie → fallback HTML.
    10. **Publikacja (2026-11-20).** Actor opublikowany w Apify Store (`isPublic: true`, build 0.0.25, commit `9442cd6`); Store Publishing Terms zaakceptowane. Weryfikacja pełnego defaultu po publikacji — run `el6ZwdJPWZn5A0NVf` (input `{}`, Warszawa + Kraków, `perDistrict`): 294 s, 106 yieldów (104 płatne) + 1000 ofert = $6,08, 212 zapytań, 2 blokady (0,9%), `identicalMerged` 273 / 235, `suspectRooms` zaobserwowane (1), koszt platformy $0,0155.
    11. **Drugie konto Apify: nie zakładamy** (General Terms 4.3 zakazują wielu kont osobistych bez zgody Apify). Zachowanie u innych użytkowników (proxy, blokady) weryfikujemy przez Insights i Issues; zastępuje to „test z drugiego konta” z punktów 15.2–15.3 i z M4.
    12. **Prefill a auto-test Apify:** codzienny test używa wartości `prefill` z input schema (docs: platform/actors/publishing/test), limit 5 min. **Nie zmieniać prefill na cięższy input.**
    13. **Zmiana nazwy w Store (2026-11-22).** Nazwa w Store: „Otodom Rental Yield & Deal Score – Poland” (SEO name/description z „Otodom”). README: sekcje „How to use it without code” i „Roadmap” oraz disclaimer o braku powiązań z Otodom. Build 0.0.26 (commit `be4a094`); kategorie przypisane automatycznie (Real estate). Slug `data-nest/cee-rental-yield` bez zmian. Zastępuje tytuł z 15.4 w warstwie Store.
    14. **Taski-przykłady w Store (2026-11-22).** Opublikowane 3 Taski (examples): `rental-yield-warsaw`, `underpriced-flats-krakow`, `rental-yield-warsaw-vs-wroclaw`; wszystkie z `samplingMode: "perDistrict"` i `maxListingsPerSide: 1500` (zweryfikowane przez API). **Przy tworzeniu Tasków w Console zawsze wklejać pełny JSON inputu** (formularz podstawia prefill). **Kontekst:** od 2026-11-19 wyszukiwarka Store ukrywa Actory bez użytkowania (blog Apify „Apify Store search is changing”) — pierwszych użytkowników trzeba pozyskać linkiem bezpośrednim i z Google.
    15. **Rabaty Store (PPE), aktywne od 2026-11-23 12:01:30 UTC** (`pricingInfos` zweryfikowane przez API). `scored-listing`: FREE $0.004, BRONZE $0.0038, SILVER $0.0036, GOLD $0.0034. `area-yield`: FREE $0.02, BRONZE $0.019, SILVER $0.018, GOLD $0.017. `apify-actor-start`: $0.00005 na wszystkich poziomach. PLATINUM i DIAMOND Apify ustawił automatycznie na cenę GOLD. Przypisanie planów: Starter = Bronze, Scale = Silver, Business = Gold. Zdarzenie główne i `minimalMaxTotalChargeUsd` ($0.05) bez zmian. Cofnięcie rabatu = podwyżka (powiadomienie 14 dni, max 1 zmiana na miesiąc, §0.15.6).
    16. **Run `pLzS2i9iD5kwTW684` (build 0.0.26, 2026-11-23, konto właściciela).** Input: `cities ["wroclaw"]`, `mode yieldReport`, `samplingMode perDistrict`, `maxListingsPerSide 1500`, reszta domyślna, `maxTotalChargeUsd 2`. Wynik: SUCCEEDED w 79 s, 23 yieldy (22 płatne), 51 zapytań, 1 blokada (rent; nowa sesja proxy pomogła), `stoppedReason last_page` po obu stronach, `identicalMerged` 84, rynek ALL (wtórny + pierwotny). Wrocław ma w Otodom tylko 5 dzielnic (`related_locations`). Yield miasta 5,68% (Warszawa 5,26%, Kraków 5,01% z runu `el6ZwdJPWZn5A0NVf`). **Znane ograniczenie (bez zmian w kodzie):** w grupach Wrocław Śródmieście 3 i 4+ oraz Stare Miasto 3 ceny za m² są bardzo skupione (Śródmieście 3: IQR 68 EUR/m²), prawdopodobnie jedna duża inwestycja.
    17. **Strona z danymi na datanest.dev (decyzja).** EN `/en/rental-yield-poland-2026-11`, PL `/rentownosc-najmu-2026-11` (PL jest domyślny i żyje w korzeniu; `/pl/...` przekierowuje 301), z danych obu runów (16 i 15.10). Strona jest budowana w osobnym repo strony.
    18. **Strona z danymi wdrożona (2026-11-23).** Działa na `https://datanest.dev/en/rental-yield-poland-2026-11` i `https://datanest.dev/rentownosc-najmu-2026-11`, zweryfikowane z zewnątrz. Link w stopce strony głównej (PL → wersja PL, EN/IT/CS → wersja EN). Dane: Warszawa i Kraków z runu `el6ZwdJPWZn5A0NVf`, Wrocław z runu `pLzS2i9iD5kwTW684`, razem 129 grup; yield brutto: Wrocław 5,68%, Warszawa 5,26%, Kraków 5,01%. Strona nie jest w tym repo: hostowana na NAS właściciela, zmiany przez paczki tar.gz z czatu; Claude Code nie pracuje przy stronie. Na stronie poprawiono `APIFY_PROFILE_URL` z `https://apify.com/pl-datanest` na `https://apify.com/data-nest`. Metoda na stronie mówi wprost: czynsz najmu bez czynszu administracyjnego (zgodnie z `src/sources/otodom.py:592`). Promocja: Wykop odpada; Reddit i inne kanały do zbadania w kolejnej rozmowie.

    19. **Promocja (2026-11-23).**
        - Link z README do datanest.dev: **NIE.** Store Publishing Terms 2.2.4.2(i) zakazują linkowania i promowania produktów lub usług poza platformą w Actorze, readme, opisie, issues i recenzjach. Strona datanest.dev linkująca do Actora jest OK.
        - 2026-11-23: wysłane pitche z danymi do redakcji Bankier.pl, direct.money.pl i Bezprawnik. Jednorazowy follow-up ok. 2026-11-30.
        - Opublikowany post na Discordzie Apify (#actor-promotion). Post opublikowany z konta Datanest (nie z prywatnego). Reddit: konto Reddit Datanest NIE zostało założone (wcześniejszy wpis „założone” był na wyrost); właściciel nie jest przekonany do Reddita, więc odpada na razie — nie proponować go ani nie przygotowywać postów, dopóki właściciel sam do tego nie wróci. Wykop odpada.
        - Decyzja: Łódź, Gdańsk i Poznań dodajemy przed 2026-12-06, bo redakcje porównują 8 miast. Kolejny kandydat: osobny Actor dla Imovirtual (Portugalia); rozpoznanie wykonane 2026-11-23, wynik w 15.22.

    20. **Nowe miasta na produkcji (2026-11-23).**
        - Łódź, Gdańsk i Poznań obsługiwane od buildu 0.0.27 (commit `0114428`). Build 0.0.28 (`be08952`): README z sekcją „Yields by city” dla 6 miast. Opis i SEO description w Store zaktualizowane do 6 miast.
        - Runy referencyjne (`yieldReport`, `perDistrict`): Łódź `kXpCp4wihublvax0d` (20 grup), Poznań `rRVZoTR9h7cuUzN7u` (21), Gdańsk `x3WHfYyPk9sKsSNhk` (29; `maxListingsPerSide` 3000, bo Otodom ma tam 32 dzielnice). Łódź i Poznań mają po 5 dzielnic.
        - Strona z danymi na datanest.dev zaktualizowana do 6 miast i 199 grup (paczka 2026-11-23c).
        - **ZASADA:** runów na Otodom nigdy nie uruchamiamy równolegle. Limit 1 zapytania/s obowiązuje na domenę łącznie, także między runami (2026-11-23 dwa równoległe runy przerwano). Runy zawsze po kolei.
        - **ZASADA:** weryfikacja na żywo zawsze przez ścieżkę kodu Actora (nie osobny skrypt) i z zapytaniem kontrolnym dla miasta, które na pewno działa. Przyczyną 404 z 2026-11-23 był skrypt z `sale` zamiast `sprzedaz`.
        - Zapytania na żywo do Otodom tylko po zgodzie właściciela, z podaną liczbą zapytań.
        - Wersja Actora ma w Apify `githubWebhookId`, ale push nie uruchamia automatycznego buildu. Buildy nadal ręczne z Console.

    21. **Stan na 2026-11-23 i zasady pracy (handoff).**
        - Stan produktu: Actor obsługuje 6 miast (Warszawa, Kraków, Wrocław, Łódź, Poznań, Gdańsk; Katowice w inpucie, niereklamowane). Build 0.0.28, `origin/main` = `be08952`, 273 testy offline. README zawiera sekcję „Yields by city”. Reguły runów i weryfikacji na żywo: patrz 15.20.
        - Promocja: pitche z danymi wysłane 2026-11-23 do Bankier.pl, direct.money.pl i Bezprawnika; jednorazowy follow-up zaplanowany na 2026-11-30. Promocja wyłącznie pod marką Datanest, nigdy z kont prywatnych. Reddit odroczony (patrz 15.19).
        - Zasada ciągłości: przy długiej rozmowie czat proponuje nowy handoff; po przejściu do nowej rozmowy w Claude Code wykonuje się `/clear`, więc każdy prompt dla Claude Code musi być samowystarczalny (repo, zadanie, ograniczenia).

    22. **Decyzje 2026-11-23 (miasta, Roadmap, Idealista, Imovirtual).**
        - Kolejne polskie miasta (Katowice, Szczecin, Bydgoszcz, Lublin, Białystok) zostają na grudzień, razem z aktualizacją strony datanest.dev i README (jeden build 0.0.29). Dodanie siódmego miasta wymaga zmiany tytułu strony „sześciu największych miast” (Szczecin, Bydgoszcz, Lublin i Białystok są większe od Katowic).
        - Roadmap w README (po grudniowej aktualizacji): done — Gdańsk, Poznań, Łódź; next — Katowice, Szczecin, Bydgoszcz, Lublin, Białystok; Portugal (Imovirtual) „next in line, once the Polish market is covered”; Czechy wypadają z Roadmapu (wracają po sygnałach popytu).
        - Idealista (ES/IT/PT): odrzucone. Powody: `robots.txt` zabrania paginacji i wielofiltrowych URL-i; silna ochrona antybotowa (wymagałaby omijania zabezpieczeń); co najmniej 9 Actorów konkurencji po $0,0005–0,001 za wynik. Hiszpania/Włochy: ewentualnie inne portale po rozpoznaniu `robots.txt` (Fotocasa/Habitaclia, Immobiliare.it), nie teraz.
        - Imovirtual (PT): rozpoznanie 2026-11-23 wykonane (8 zapytań; notatki i `fetch.py` w `~/PycharmProjects/imovirtual-recon`, poza repo, bez gita; surowe JSON-y usunięte, bo zawierały dane agencji). **Wynik: GO.** `robots.txt` zezwala na `/pt/resultados/` i `/_next/data/`; `Content-Signal: ai-train=no` (nas nie dotyczy, nie trenujemy modeli). Dane w `__NEXT_DATA__` / `_next/data`, struktura jak Otodom; dzielnica (freguesia) w polach `reverseGeocoding` i w filtrze URL; paginacja głęboka (`limit=72`); EUR (bez `fx`). Do ustalenia przed budową: T0 w danych, reguła rynku pierwotnego (`developmentId` niezweryfikowane), zachowanie przy 1 req/s na dużej próbie, czynsz z `totalPrice` (`rentPrice` prawie puste).
        - Plan Imovirtual: osobny Actor z własnym repo, dopiero po zakończeniu polskiego rynku. Zasada ToS bez zmian (nie analizujemy).
        - Odrzucone źródła (2026-11-24): **Immobiliare.it** – NO-GO: `robots.txt` pozwala na listy ofert, ale DataDome zwraca 403 z captchą już przy pierwszym zapytaniu (bez proxy, `curl_cffi` chrome); obejście wymagałoby łamania zabezpieczeń. **Fotocasa (ES)** – ODŁOŻONA (decyzja właściciela 2026-11-24): zajmiemy się nią, gdy Actor Imovirtual będzie działać w 100%. `robots.txt` zabrania paginacji (`/*/l/2*`…`/*/l/39*`), filtrów i sortowania; pierwsze strony lokalizacji dozwolone. Recon 2026-11-24 (8 zapytań, w tym 2 testowo wbrew robots za zgodą właściciela): brak antybota, dane w `<script id="__initial_props__">`, ~30 ofert/stronę; same pierwsze strony barrios dają ~7–10% ofert → za mało. Decyzja o traktowaniu `robots.txt` dla Fotocasy – otwarta, do podjęcia przed budową; do tego czasu obowiązuje zasada z §3.4. Notatki: `~/PycharmProjects/fotocasa-recon/notes.md`. **Pracuj.pl** – odrzucone decyzją właściciela.
        - Przegląd popytu w Store (2026-11-24, użytkownicy/mies., top 5): Idealista ~940, Immobiliare ~300, Fotocasa ~180, Otodom ~90, Imovirtual ~38. Nikt nie liczy rentowności z ofert. Następny Actor: Imovirtual (PT); po Imovirtual → Fotocasa.
        - Poprawka po buildzie 0.0.29: w `mode = yieldReport` yieldy zostają w datasecie default (API), a kopia (bez naliczania, bez wpływu na budżet) trafia też do `yields`, bo widok „Rental yield by district” w Output jest przypięty do `yields` (`src/pipeline.py:_copy_yields_for_output_view`). Roadmap w README zaktualizowany (kolejne polskie miasta, potem Portugalia; Czechy poza Roadmapem).
        - Przed buildem 0.0.29: README (przykład wyniku, koszt, sekcja dla agentów), dataset views (kolumny `local.currency`, `fx.date`), taski w `docs/store-tasks.md`; kategorie Store do ustawienia w Console.

    23. **Stan 2026-11-24.**
        - Kategorie w Apify Store przypisuje Apify automatycznie („Categories are auto-assigned based on your Actor”). Nie ustawiamy ich ręcznie i nie traktujemy „Uncategorized” w API jako błędu (zastępuje uwagę o kategoriach „do ustawienia w Console” z 15.22).
        - Build 0.0.30 = commit `eb3d27f` (potwierdzone logiem buildu), oznaczony jako `latest`.
        - Strony Tasków w Store: tabela z przykładowymi danymi („example dataset”) jest niedostępna (sekcja Dataset schema w Publishing ma tylko wybór datasetu i widoku). Decyzja: pomijamy. Taski `rental-yield-lodz` i `rental-yield-poznan-gdansk` mają dataset `yields` + widok „Rental yield by district” oraz FAQ (7 pytań, EN, dodane w Console). Taska Poznań+Gdańsk nie uruchamiamy (brak potrzeby).
        - Promocja: 2026-11-24 wysłano pitche z danymi 6 miast do Business Insider Polska, Dziennika Łódzkiego, Głosu Wielkopolskiego, Trojmiasto.pl i PropertyNews.pl. Follow-up: 2026-12-01 (te 5) i 2026-11-30 (Bankier, direct.money, Bezprawnik).
        - Monitoring publikacji naszych danych w mediach: cykliczne zadanie poza repo (pon i czw 9:17), szuka nazwy Datanest i par charakterystycznych liczb. Przy grudniowej aktualizacji danych podmienić liczby w jego poleceniu.
        - 2026-11-25: quality score 83/100 (było 79); rekomendacja „Mark sensitive input fields as secret” zniknęła po buildzie 0.0.31 (zmiana `stateKey` → `watchlistName`).

**Po stronie właściciela (nie Claude Code):**
- zaakceptować brief M3 (albo odesłać poprawki),
- podpiąć repo w Apify jako prywatny Actor (Source type: Git repository) — kroki w briefie M3,
- przed publikacją (M4): dane do wypłat i ceny zdarzeń w monetyzacji,
- usunąć kopię `~/PycharmProjects/cee-rental-yield-backup-2026-11-18` (zawiera dane sprzed przepisania historii).

## 1. Co budujemy i dla kogo

**Produkt:** Actor Apify „Rental Yield & Deal Score”. Jedno uruchomienie pobiera z portalu ogłoszenia mieszkań **na sprzedaż i na wynajem długoterminowy** w wybranych miastach i zwraca:

1. **Rentowność brutto najmu** per dzielnica × liczba pokoi (mediany, kwartyle, liczebność próby).
2. **Ocenę 0–100 każdej oferty sprzedaży** względem mediany ceny za m² jej grupy (dzielnica × pokoje) i szacowaną rentowność tej oferty.
3. Wszystko **w EUR** (kurs EBC) obok waluty lokalnej (PLN; CZK od wersji 1.1), żeby miasta z różnych krajów dało się porównać.

**Odbiorcy:** zagraniczni inwestorzy buy-to-let, proptech i wyceny automatyczne, fundusze najmu, analitycy, agenci AI wołający Actora przez MCP. Dlatego wszystkie teksty dla użytkownika (README, opisy pól, komunikaty błędów, tytuły) są **po angielsku**. Kod, komentarze i commity też po angielsku.

**Dlaczego to ma sens:** dla UK, Francji, DACH i USA takie Actory już istnieją (np. `lowlanddata/rightmove-yield-scanner`, `mocha_tassel/real-estate-deal-score` od $4/1000 ocenionych ofert). Dla Polski i Czech są tylko surowe scrapery albo same mediany ceny za m² (`lowlanddata/otodom-price-stats`). Wyróżniki: ocena każdej oferty, EUR, uczciwie opisane pułapki danych, kolejne kraje bez zmiany nazwy (1.0 Polska, 1.1 Czechy).

**To jest jeden Actor z wieloma źródłami**, nie osobny Actor na portal. Źródła to moduły w `src/sources/`. Klient podaje miasta, Actor sam wybiera źródło.

---

## 2. Zakres wersji

| Wersja | Kraj | Źródło | Miasta |
|---|---|---|---|
| 1.0 | Polska | Otodom | Warszawa, Kraków, Wrocław (+ Katowice wybieralne, nie reklamowane) |
| 1.1 | Czechy | `reality.idnes.cz` (decyzja 2026-11-18; parser dopiero w 1.1) | Praha, Brno, Ostrava |
| później | Włochy | Immobiliare | Milano, Roma, Napoli (NIE w tym etapie; wcześniej planowane jako 1.1) |

**W zakresie 1.0:** mieszkania (flats), sprzedaż + najem długoterminowy, rynek wtórny i pierwotny razem (z flagą `isPrimaryMarket`), rentowność per dzielnica × pokoje, ocena ofert sprzedaży, tryb monitoringu (tylko nowe oferty i obniżki), EUR + waluta lokalna.

**Poza zakresem 1.0:** domy, działki, lokale użytkowe, najem krótkoterminowy, rentowność netto, ceny transakcyjne (RCN), zdjęcia, opisy, dane kontaktowe, strony szczegółów ogłoszeń.

---

## 3. Zasady, których nie wolno łamać

1. **Tylko strony wyników wyszukiwania.** Nigdy nie otwieraj pojedynczych ogłoszeń (strony szczegółów). Wszystko, czego potrzebujemy, jest w katalogu.
2. **Zero danych osobowych w wyniku i w logach.** Usuwaj przy parsowaniu, zanim cokolwiek zapiszesz: imiona, nazwiska, telefony, e-maile, nazwy agencji, nazwy właścicieli ogłoszeń, zdjęcia, opisy. Patrz §7.
3. **Wynik to nasze wyliczenia + link do ogłoszenia**, nie kopia ogłoszenia. Zwracamy cenę, metraż, pokoje, dzielnicę, wskaźniki i URL. Bez tytułów ogłoszeń w rekordach wyjściowych (tytuł może zawierać dane osobowe i jest treścią portalu).
4. **Tempo i robots.txt:** maksymalnie 1 zapytanie na sekundę na domenę. **Źródło wchodzi do Actora tylko, gdy `robots.txt` pozwala na nasze ścieżki dla `User-agent: *`** — niezależnie od tego, co robią inne Actory w Apify Store (§0, decyzja 1). Otodom: `robots.txt` pozwala na `/_next/data/` i `/pl/wyniki/`, brak crawl-delay (potwierdzone 2026-11-18) — Otodom zatwierdzony przez właściciela. Sreality: wyłączone.
5. **Bez obchodzenia captchy, bez farm captcha, bez przeglądarki.** Jeśli serwis blokuje, kończymy z czytelnym błędem.
6. **Głośna porażka:** pusty lub zablokowany wynik kończy uruchomienie błędem z opisem i **nie nalicza opłat**. Nigdy pusty „sukces”.
7. **Testy bez sieci.** Wszystkie testy jednostkowe działają na fixtures z `tests/fixtures/`. Żywe zapytania tylko w skrypcie pomiarowym (§13), uruchamianym ręcznie.
8. **Nie zgaduj API Apify z pamięci.** Przed użyciem `Actor.charge`, `push_data` z opłatą, proxy, key-value store sprawdź aktualną dokumentację: `https://docs.apify.com/sdk/python/` i `https://docs.apify.com/platform/actors/publishing/monetize`.

---

## 4. Stos technologiczny

- Python 3.12
- `apify` (Apify SDK for Python, najnowsza stabilna)
- `curl_cffi` (async, `impersonate="chrome"`) jako klient HTTP — lepszy odcisk TLS niż httpx dla Otodom
- standardowa biblioteka do statystyki (`statistics`, `math`), bez pandas/numpy (mały obraz, mała pamięć)
- `pytest`, `pytest-asyncio` w dev
- Docker: obraz bazowy `apify/actor-python:3.12`
- Pamięć Actora: celuj w 256–512 MB. W modelu pay-per-event koszty platformy pokrywa autor, więc lekkość = marża.

---

## 5. Struktura repozytorium

```
cee-rental-yield/
├── CLAUDE.md                     # ten plik
├── README.md                     # strona Actora w Apify Store (EN), §16
├── Dockerfile
├── requirements.txt              # apify, curl_cffi
├── requirements-dev.txt          # pytest, pytest-asyncio
├── .actor/
│   ├── actor.json
│   ├── input_schema.json
│   └── dataset_schema.json
├── src/
│   ├── __init__.py
│   ├── __main__.py               # asyncio.run(main())
│   ├── main.py                   # orkiestracja: input → źródła → clean → stats → output → charge
│   ├── config.py                 # CITIES: miasto → kraj, źródło, slug/ID lokalizacji, waluta
│   ├── models.py                 # dataclasses: Listing, AreaYield, ScoredListing, RunStats
│   ├── http.py                   # klient z limiterem 1 req/s/domena, retry, proxy, licznik blokad
│   ├── fx.py                     # kurs EBC
│   ├── clean.py                  # walidacja, pułapki, deduplikacja, outliery
│   ├── stats.py                  # mediany, kwartyle, MAD, rentowność, ocena, fallback grup
│   ├── monitor.py                # stan monitoringu w key-value store
│   ├── output.py                 # budowa rekordów areaYield / scoredListing / RUN_SUMMARY
│   └── sources/
│       ├── __init__.py           # interfejs Source + rejestr
│       └── otodom.py
├── scripts/
│   ├── measure.py                # pomiar bramki, żywe zapytania, wynik do konsoli/JSON (--scored-out)
│   ├── anonymize_fixture.py      # anonimizacja fixtures przed commitem (§14)
│   └── review_sample.py          # próbka ofert do ręcznej weryfikacji (CSV)
└── tests/
    ├── fixtures/
    │   ├── otodom_rent_katowice.json     # zanonimizowana próbka _next/data, najem Katowice
    │   ├── otodom_sale_katowice.json     # zanonimizowana próbka _next/data, sprzedaż Katowice (8 kafelków INVESTMENT)
    │   └── ecb_daily.xml
    ├── test_otodom_parse.py
    ├── test_otodom_fetch.py      # paginacja, dzielnice, LATEST/72, buildId, fallback HTML (fałszywy klient)
    ├── test_http.py              # okno blokad
    ├── test_fixtures_pii.py      # strażnik danych osobowych we wszystkich fixtures
    ├── test_clean.py
    ├── test_stats.py
    ├── test_fx.py
    └── test_output.py
```

---

## 6. Źródła danych

### 6.1 Otodom (Polska)

**Dostęp:** Otodom to Next.js. Dane wyników wyszukiwania są dostępne jako czysty JSON przez trasę danych Next.js:

```
GET https://www.otodom.pl/_next/data/{buildId}/pl/wyniki/{transaction}/mieszkanie/{locationPath}.json
    ?page={n}&limit=72&by=LATEST&direction=DESC&ownerTypeSingleSelect=ALL&distanceRadius=0
    &searchingCriteria={transaction}&searchingCriteria=mieszkanie
    &searchingCriteria={seg1}&searchingCriteria={seg2}&searchingCriteria={seg3}&searchingCriteria={seg4}
```

- `transaction`: `sprzedaz` albo `wynajem`
- `locationPath`: 4 segmenty `województwo/powiat/gmina/miasto`, każdy segment idzie też jako kolejny `searchingCriteria` w tej samej kolejności
- nagłówki: realistyczny `User-Agent` (Chrome), `Accept: */*`, `x-nextjs-data: 1`, `Referer: https://www.otodom.pl/pl/wyniki/{transaction}/mieszkanie/{locationPath}`
- odpowiedź: `{"pageProps": {...}, "__N_SSP": true}`

**Discovery `buildId`:** `buildId` zmienia się przy każdym wdrożeniu Otodom. Raz na uruchomienie pobierz HTML strony wyników:
`GET https://www.otodom.pl/pl/wyniki/{transaction}/mieszkanie/{locationPath}`, wyciągnij `<script id="__NEXT_DATA__" type="application/json">…</script>`, sparsuj JSON, weź `buildId`. Ten sam JSON ma `props.pageProps` = dane strony 1 (użyj ich, nie pobieraj strony 1 drugi raz). Gdy `_next/data` zwróci 404 → odśwież `buildId` jeden raz → jeśli dalej źle, przejdź na pobieranie stron HTML (`?page=N`) i parsuj `__NEXT_DATA__` z każdej. **Wróć do `_next/data`, gdy strona HTML pokaże inny `buildId`** — 2026-11-18 Otodom wdrażał nową wersję w trakcie pomiaru: odświeżenie widziało jeszcze stary `buildId`, a strony HTML są 3–4× większe (koszt proxy). Strona 1 (HTML) idzie z tymi samymi `limit=72&by=LATEST&direction=DESC`; jeśli `pageProps.sortingOption` lub `itemsPerPage` się nie zgadzają, strona 1 jest pobierana ponownie z `_next/data` — w pomiarze 24/24 stron rynku HTML honorował parametry (potwierdzone 2026-11-18).

**Lokalizacje (slug = locationPath):**

| Miasto (input) | locationPath | Status |
|---|---|---|
| `katowice` | `slaskie/katowice/katowice/katowice` | potwierdzone 2026-11-18 (5 701 ofert) |
| `warszawa` | `mazowieckie/warszawa/warszawa/warszawa` | potwierdzone 2026-11-18 (20 260 ofert) |
| `krakow` | `malopolskie/krakow/krakow/krakow` | potwierdzone 2026-11-18 (14 450 ofert) |
| `wroclaw` | `dolnoslaskie/wroclaw/wroclaw/wroclaw` | potwierdzone 2026-11-18 (10 836 ofert) |

Weryfikacja: w odpowiedzi `pageProps.tracking.listing.selected_locations_id` musi być `["city:{locationPath}"]`.

**Struktura odpowiedzi (potwierdzona w `tests/fixtures/otodom_rent_katowice.json`):**

- `pageProps.data.searchAds.items[]` — oferty (72 na stronę przy `limit=72`, 36 domyślnie; może trafić się dodatkowy element — wstawka reklamowa, patrz pułapki)
- `pageProps.data.searchAds.pagination` — `{itemsPerPage, totalItems, totalPages, currentPage}`
- `pageProps.faqDynamicData` — agregaty Otodom: `avgPrice`, `avgAreaM`, `avgPricePerM` (Katowice najem: 54) — używaj jako testu sensowności naszej mediany, nie jako danych
- `pageProps.data.searchLinksRelatedLocations.items[]` — `{name, estate, transaction, location}` wszystkich dzielnic miasta (22 w Katowicach; slug dzielnicy = ostatni segment `location`). Potwierdzone w fixture i na żywo 2026-11-18: Warszawa 18, Wrocław 5, sprzedaż i najem (te same listy)
- `pageProps.tracking.listing` — `result_count`, `page_count`, `results_per_page`, `selected_locations_id`

**Pola oferty, których używamy** (`items[]`):

| Pole Otodom | Znaczenie | Uwagi |
|---|---|---|
| `id` | ID oferty | int |
| `slug` | slug, np. `mieszkanie-2-pokoje-bogucice-koszutka-ID4E1Sb` | klucz deduplikacji; URL oferty = `https://www.otodom.pl/pl/oferta/{slug}` |
| `href` | ścieżka | jeśli zaczyna się od `hpr/` → wstawka reklamowa, odrzuć |
| `estate` | `FLAT` | filtruj tylko `FLAT` |
| `transaction` | `SELL` / `RENT` | potwierdzone 2026-11-18 |
| `totalPrice.value`, `totalPrice.currency` | cena sprzedaży albo **miesięczny najem** | `null` gdy ukryta |
| `rentPrice.value` | **czynsz administracyjny** (do wspólnoty), NIE najem | może być `null` |
| `hidePrice` | cena ukryta | odrzuć gdy `true` |
| `areaInSquareMeters` | metraż | float |
| `roomsNumber` | `"ONE"`…`"TEN"`, `"MORE"` | mapuj słowa na liczby, nieznane → `None` |
| `floorNumber` | `"GROUND"`, `"FIRST"`…`"TENTH"`, `"ABOVE_TENTH"`, `"CELLAR"`, `"GARRET"` | nieznane/`ABOVE_TENTH` → `None` (nie zgaduj liczby) |
| `pricePerSquareMeter` | bywa `null` | **zawsze licz sam** z ceny i metrażu |
| `location.reverseGeocoding.locations[]` | `{id, locationLevel, name}` | miasto: `locationLevel == "city_or_village"`; dzielnica: `locationLevel == "district"` |
| `createdAtFirst` | data pierwszej publikacji | do `daysOnMarket` |
| `dateCreated` | data utworzenia | fallback dla `createdAtFirst` |
| `pushedUpAt` | podbicie | **NIE używać** do czasu na rynku |
| `developmentId`, `investmentState`, `investment*` | dane inwestycji deweloperskiej | `developmentId > 0` ⇒ `isPrimaryMarket = true`; brak sygnału ⇒ `null` (§6.1) |
| `isPrivateOwner`, `extendedAdvertiserType` | typ ogłoszeniodawcy | możemy zwrócić `advertiserType: "private"|"business"` |
| `isPromoted` | promowane | ignoruj |

**Pola, które musisz usunąć natychmiast po wczytaniu** (dane osobowe / treść): `advertOwner` (całe), `organisationAssignedMember` (całe), `agency` (całe; nazwy agencji JDG to imiona i nazwiska), `images`, `title`, `shortDescription`, `location.address` (ulica), `relatedAds` (zagnieżdżone pełne ogłoszenia lokali z własnymi danymi ogłoszeniodawcy i ulicą).

**Rynek pierwotny/wtórny — reguła `developmentId > 0` OBALONA (2026-11-19).** Filtr wyników `market=PRIMARY|SECONDARY` (parametr z `pageProps.filteringQueryParams.market`, domyślnie `ALL`; Otodom go echo-potwierdza). Warszawa, sprzedaż, strona 1 (LATEST/72): PRIMARY `totalItems` 12 707, SECONDARY 7 598 (suma ≈ 20 274 bez filtra); `developmentId > 0` u **0 z 70** ofert pierwotnych i 0 z 72 wtórnych. `developmentId` oznacza tylko lokale powiązane z kafelkiem inwestycji. Żadne pole oferty nie rozróżnia rynków (te same klucze; jedyna słaba wskazówka: `source = urn:partner:informacja-deweloperska` tylko w pierwotnym, 12/70). **Decyzja właściciela (2026-11-19): (a) + (b), bez (c).** `includePrimaryMarket=false` → `market=SECONDARY` i `isPrimaryMarket=false` dla wszystkich ofert (pewne); `true` (domyślnie) → `market=ALL`, `isPrimaryMarket=true` gdy `developmentId > 0`, w pozostałych przypadkach `null`. README „Limitations” opisuje mieszanie rynków. (c) wraca po teście H, jeśli dane pokażą, że mieszanie rynków zaburza mediany. Rynek pierwotny to ≈ 63% bieżącej podaży sprzedaży w Warszawie.

**Kafelki `INVESTMENT`** (dawne `not_flat`): projekty deweloperskie, nie oferty — `totalPrice`, `areaInSquareMeters`, `roomsNumber` = `null`; mają `priceFromPerSquareMeter`, `investmentUnitsNumber`, zakresy metrażu i pokoi, `investmentState`, `investmentEstimatedDelivery`, `developmentId = 0`, oraz `relatedAds` (2–3 pełne ogłoszenia lokali z `developmentId == id kafelka`). Odrzucane z powodem `primary_market_project`, liczone w `RUN_SUMMARY.primaryMarketProjects`. `relatedAds` są usuwane przy parsowaniu (dane osobowe, niereprezentatywne) — wymień to w README „Limitations”. **Duplikaty:** strony całego miasta (DEFAULT) serwują te same kafelki wielokrotnie (Katowice: 178 kafelków, 36 unikalnych) — deduplikacja po `slug` musi poprzedzać liczenie (poprawione 2026-11-18). Unikalne projekty w pomiarze per dzielnica (sprzedaż): Katowice 44, Warszawa 148, Kraków 136, Wrocław 52; mediana lokali na projekt 30–50.

**Sortowanie i rozmiar strony (decyzja 2026-11-18):** `by=LATEST&direction=DESC`, `limit=72`. Sonda (Warszawa, sprzedaż, 20 274 ofert): LATEST sortuje po `createdAtFirst` (99,1% par malejąco), mediana wieku 1 dzień, strony stabilne po 5 min; DEFAULT sortuje po `pushedUpAt` (płatne podbicia), strony się przesuwają (87–96% pokrycia, duplikaty i pominięcia). `limit=72` działa (72 elementy), `limit=100` po cichu zwraca 36. **Próba = bieżąca podaż** — raportuj jej wiek (§0, zadanie 4).
- **Próbkowanie per dzielnica:** ścieżka dzielnicy potwierdzona 2026-11-18: `/_next/data/{buildId}/pl/wyniki/{tx}/mieszkanie/{locationPath}/{districtSlug}.json` z 7 × `searchingCriteria`; odpowiedź ma `tracking.listing.selected_locations_id == ["district:{locationPath}/{districtSlug}"]`. Lista dzielnic z `pageProps.data.searchLinksRelatedLocations` (fallback: odkrywanie z pierwszych stron całego miasta). Kwota na dzielnicę liczy kandydatów (`FLAT`, nie `hpr/`); oferta liczy się do dzielnicy z `reverseGeocoding`, nie do dzielnicy stronicowanej (efekt granic). Wyniki: „Pomiar decyzyjny” niżej.
- **Granulacja dzielnic różni się między miastami:** Wrocław ma w Otodom 5 dużych dzielnic historycznych, Katowice 22, Warszawa i Kraków po 18. Wyniki pokrycia nie są porównywalne między miastami bez tej uwagi.

**Pomiar decyzyjny (2026-11-18, domowe IP bez proxy, LATEST/72, progi 15/10).** Bramka = % oczyszczonych ofert sprzedaży z `saleGroupLevel == "district"` (obowiązująca); grupy = % grup `district × rooms` z oboma progami (informacyjnie). MB = bajty po dekompresji (górne oszacowanie kosztu proxy). Wiek = dni od `createdAtFirst` (mediana / najstarsza), udział = pobrane / `totalItems` miasta.

| tryb | miasto | sprzedaż / najem | bramka | grupy | zapytania | MB | czas | wiek sprzedaży | udział sprzedaż / najem |
|---|---|---|---|---|---|---|---|---|---|
| per dzielnica 150 | Katowice | 1 585 / 737 | 80,6% | 27,7% | 105 | 38,9 | 107 s | 33 / 1 185 | 0,29 / 0,98 |
| per dzielnica 150 | Warszawa | 3 176 / 3 126 | 98,0% | 77,8% | 107 | 48,0 | 112 s | 8 / 908 | 0,16 / 0,42 |
| per dzielnica 150 | Kraków | 2 974 / 2 336 | 96,2% | 62,5% | 107 | 48,4 | 108 s | 19 / 1 129 | 0,21 / 0,74 |
| per dzielnica 150 | Wrocław | 899 / 985 | 94,2% | 65,0% | 39 | 20,8 | 41 s | 2 / 9 | 0,09 / 0,42 |
| per dzielnica 300 | Katowice | 1 676 / 737 | 81,7% | 27,7% | 116 | 43,9 | 120 s | 36,5 / 1 185 | 0,31 / 0,98 |
| per dzielnica 300 | Warszawa | 5 083 / 4 298 | 98,7% | 83,3% | 194 | 84,2 | 204 s | 13 / 1 430 | 0,26 / 0,58 |
| per dzielnica 300 | Kraków | 4 215 / 3 035 | 98,4% | 68,1% | 163 | 154,8* | 201 s | 26 / 1 867 | 0,30 / 0,96 |
| per dzielnica 300 | Wrocław | 1 627 / 1 571 | 100% | 90,0% | 66 | 103,4* | 82 s | 6 / 16 | 0,16 / 0,68 |
| całe miasto 1500 | Katowice | 1 402 / 737 | 77,2% | 25,3% | 46 | 23,4 | 47 s | 26 / 149 | 0,26 / 0,99 |
| całe miasto 1500 | Warszawa | 1 452 / 1 465 | 82,0% | 39,1% | 44 | 22,8 | 45 s | 2 / 6 | 0,07 / 0,20 |
| całe miasto 1500 | Kraków | 1 496 / 1 465 | 79,0% | 32,4% | 45 | 23,9 | 45 s | 6 / 13 | 0,11 / 0,46 |
| całe miasto 1500 | Wrocław | 1 474 / 1 436 | 100% | 90,0% | 51 | 26,0 | 51 s | 5 / 11 | 0,14 / 0,61 |

\* wdrożenie Otodom w trakcie pomiaru → strony HTML (3–4× większe); naprawione powrotem do `_next/data`. Blokady: 0% we wszystkich 24 stronach rynku. Porównanie z DEFAULT/36 (ten sam dzień, per dzielnica 150, Warszawa): 200 zapytań / 205 s vs 107 / 112 s przy LATEST/72 — 2× mniej, bramka podobna (96,2% vs 98,0%).

**Domyślne uruchomienie `["warszawa","krakow"]`** (samo pobieranie): całe miasto 90 s, per dzielnica 150 — 220 s, per dzielnica 300 — 405 s (> 5 min ✗).

**Decyzja właściciela (2026-11-18, §0 decyzja 5):** per dzielnica, kwota `max(150, ceil(1500 / liczba_dzielnic))` na stronę rynku — Warszawa/Kraków/Katowice 150, Wrocław 300. Spełnia bramkę w Warszawie, Krakowie, Wrocławiu (98,0 / 96,2 / 100%) i czas domyślnego uruchomienia (~220 s). Całe miasto też przechodzi bramkę w 90 s, ale przy LATEST to próba z ostatniego tygodnia (Warszawa: mediana 2 dni, najstarsza oferta 6 dni, 7% rynku) — ocena porównywałaby nowe oferty tylko z nowymi. Stała kwota 150 jest zła dla Wrocławia (5 dzielnic → 899 ofert sprzedaży, mniej niż całe miasto, najstarsza 9 dni). **Ryzyko czasu:** ~214 zapytań przy 1 req/s to ≥ 214 s; z proxy rezydencjalnym czas zapytania może przekroczyć 1 s — zmierzyć w M3, ewentualnie obniżyć kwotę.

**Pułapki Otodom (każda musi mieć test):**

1. `rentPrice` w ogłoszeniach SPRZEDAŻY to czynsz do wspólnoty (inny scraper zmierzył: mediana 731 PLN przy medianie ceny 586 200 PLN). Nigdy nie traktuj go jako najmu.
2. W ogłoszeniach NAJMU najem = `totalPrice.value`, czynsz administracyjny = `rentPrice.value`. Do rentowności bierzemy **sam najem bez czynszu** (właściciel przekazuje czynsz wspólnocie).
3. **Zamienione pola:** w fixture oferta `id=68642713` ma `totalPrice=600`, `rentPrice=1900` przy 63,77 m². Reguła: najem z `rentPrice > totalPrice` → odrzuć z median i policz w `RUN_SUMMARY.rejected.swappedRent`.
4. **Wstawka reklamowa:** w fixture element `id=9000062324` ma `href` zaczynające się od `hpr/`, puste `images`, `dateCreated = "1999-02-29 00:00:01"` (nieistniejąca data) i jest kopią `id=68645667` (ten sam `slug`). Odrzucaj `href.startswith("hpr/")`, deduplikuj po `slug`, parsuj daty defensywnie (błędna data → `None`, nie wyjątek).
5. Ukryta cena: `totalPrice == null` albo `hidePrice == true` → odrzuć.
6. Stare oferty stale podbijane (np. `createdAtFirst` z 2023) — to nie błąd, to sygnał (`daysOnMarket` duże).
7. Oferta spoza miasta: zostaw tylko te, których `reverseGeocoding.locations[]` zawiera `id == locationPath` miasta.

### 6.2 Sreality (Czechy) — WYŁĄCZONE

`robots.txt` sreality.cz: `User-agent: *` → `Disallow: /`. Decyzja właściciela z 2026-11-18: źródło usunięte z repo (§0). Nie przywracaj go bez oficjalnego API lub pisemnej zgody Seznamu.

### 6.2a Czeskie alternatywy do sprawdzenia (zadanie w M2)

Dla każdej sprawdź i opisz w PR: `robots.txt` dla `User-agent: *` (czy ścieżki wyszukiwania i ewentualne `/_next/data/` lub API są dozwolone), liczbę ofert mieszkań na sprzedaż i wynajem w Pradze, Brnie i Ostrawie, sposób dostępu do danych (JSON w stronie, API), ochronę antybotową. Nie uruchamiaj pełnego pobierania z serwisu, zanim `robots.txt` nie zostanie sprawdzony — do oceny liczby ofert wystarczy strona wyników w przeglądarce.

1. `bezrealitky.cz` — oferty bez pośredników, Next.js
2. `reality.idnes.cz`
3. inne portale z dużą liczbą ofert w tych miastach, jeśli znajdziesz

Kryterium wyboru: `robots.txt` pozwala na ścieżki, których używamy, i liczba ofert wystarcza do bramki (≥ 70% ocenionych ofert sprzedaży porównanych na poziomie dzielnicy). Jeśli żadna alternatywa nie przejdzie, wersja 1.0 wychodzi tylko z Polską, a Czechy dochodzą później.

**Wynik przeglądu (2026-11-18; tylko `robots.txt` + jedna strona wyników na portal, Praha, sprzedaż mieszkań):**

| | `bezrealitky.cz` | `reality.idnes.cz` |
|---|---|---|
| `robots.txt` (`User-agent: *`) | `Disallow: /vyhledat*`, `/search*`, `/moje-bezrealitky/*`, `*callbackUrl=*`, formularze hipoteki. Strony katalogu `/vypis/...` i `/_next/data/` **nie** są zablokowane | `Allow: /`; wyniki `/s/...` dozwolone, zablokowane m.in. `page` + `sort`, wielowartościowe filtry (`|`), `s-rd`, `cena-nad-`, popupy, `/broker-evaluation/` |
| Strona sprawdzona | `/vypis/nabidka-prodej/byt/praha` (HTTP 200) | `/s/prodej/byty/praha/` (HTTP 200) |
| Dane | Next.js; oferty w `pageProps.apolloCache` (pamięć GraphQL), 15 na stronę: `price`, `surface`, `disposition` (`DISP_2_KK`), `charges`, adres, `gps`. Wewnętrzna nazwa strony Next.js to `/search/[[...list]]` | HTML renderowany na serwerze (bez JSON), 27 kart na stronę: układ i metraż w tytule karty, ulica + dzielnica („Praha 10 - Vršovice”), cena |
| Oferty (Praha, sprzedaż) | 617 (`totalCount`) — tylko oferty bez pośredników | 4 751 |
| Ochrona | brak captchy przy jednym zapytaniu | brak captchy przy jednym zapytaniu |

**Decyzja właściciela (2026-11-18):** wersja 1.0 tylko z Polską; `reality.idnes.cz` = czeskie źródło w 1.1 (parser dopiero w 1.1, nie teraz); `bezrealitky.cz` odpada. Rekomendacja, na której oparta była decyzja: `reality.idnes.cz` jako główny kandydat (wolumen, dozwolone zwykłe strony wyników bez `sort`; parser HTML), `bezrealitky.cz` najwyżej jako uzupełnienie (mały wolumen; publiczne `/vypis` dozwolone, ale wewnętrzna trasa nazywa się `search`, a `/search*` jest zablokowane — w duchu decyzji 1 to wątpliwość). Przed decyzją właściciel: liczby ofert w przeglądarce dla Pragi (najem), Brna i Ostrawy (sprzedaż, najem) oraz regulaminy obu serwisów (`robots.txt` nie zastępuje regulaminu). Parsera nie pisano.

### 6.3 Kurs walut (EBC)

`GET https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml` — elementy `<Cube currency="PLN" rate="..."/>`, `<Cube currency="CZK" rate="..."/>`; `rate` = ile jednostek waluty za 1 EUR. Zapisz datę kursu (`<Cube time="YYYY-MM-DD">`). Brak kursu → uruchomienie kończy się błędem (nie wymyślaj kursu). Test na zapisanym XML.

---

## 7. Model danych wewnętrznych (`src/models.py`)

```python
@dataclass
class Listing:
    source: str               # "otodom"
    listing_id: str
    dedup_key: str            # otodom: slug
    url: str
    country: str              # "PL" | "CZ"
    city: str                 # nazwa wyświetlana, np. "Kraków"
    district: str | None
    transaction: str          # "sale" | "rent"
    price_local: float        # sprzedaż: cena; najem: miesięczny najem bez opłat
    currency: str             # "PLN" | "CZK"
    admin_fee_local: float | None   # czynsz administracyjny / poplatky, informacyjnie
    area_m2: float
    rooms: int | None
    floor: int | None
    is_primary_market: bool | None
    advertiser_type: str | None     # "private" | "business"
    first_published: date | None
```

`clean.py` przyjmuje surowe elementy ze źródła, zwraca `list[Listing]` + liczniki odrzuceń z powodami. Surowe słowniki nie wychodzą poza moduł źródła.

---

## 8. Czyszczenie (`src/clean.py`) — kolejność ma znaczenie

1. Usuń pola osobowe i treść (§6.1, §3.2) — zanim cokolwiek zalogujesz.
2. Odrzuć wstawki reklamowe (`hpr/`), oferty spoza miasta, `estate != FLAT`.
3. Odrzuć ukryte/zerowe/zastępcze ceny, brak metrażu.
4. Najem: odrzuć `admin_fee > rent` (zamienione pola).
5. Deduplikuj po `dedup_key` (w obrębie źródła i transakcji).
6. Odrzuć metraż `< 15` albo `> 250` m².
7. Odrzuć wartości odstające: cena za m² (sprzedaż) i najem za m² (najem) poza 1.–99. percentylem **miasta** (licz po kroku 6).
8. Każde odrzucenie liczysz w `RunStats.rejected[reason]`.

---

## 9. Statystyka i wzory (`src/stats.py`)

**Grupa:** `(country, city, district, roomsBucket)`, gdzie `roomsBucket ∈ {1, 2, 3, "4+"}` (`rooms is None` → oferta nie wchodzi do grup pokojowych, ale wchodzi do poziomu „city”).

**Fallback — osobno dla sprzedaży i najmu** (zmiana 2026-11-18):
- poziom sprzedaży (`saleGroupLevel`): pierwszy z `district × rooms` → `city × rooms` → `city`, na którym `saleCount ≥ minSaleSample` (15); z niego `median(p)`, `MAD`, `dealScore`, `discountVsMedianPct`;
- poziom najmu (`rentGroupLevel`): pierwszy z tej samej listy, na którym `rentCount ≥ minRentSample` (10); z niego `median(r)` do `estimatedRentMonthlyEur` i rentowności oferty;
- rekord `areaYield` powstaje tylko dla grup, gdzie **oba** progi są spełnione na tym samym poziomie; `groupLevel` w `areaYield` = ten poziom.

**Pewność `confidence`** (w `scoredListing` liczona z gorszego z dwóch poziomów): `high` gdy poziom `district` i `saleCount ≥ 40`; `medium` gdy `district` (15–39) albo `city_rooms`; `low` gdy `city`.

**Mediany i kwartyle:** cena sprzedaży za m² (`p`) i miesięczny najem za m² (`r`) w EUR. Kwartyle metodą `statistics.quantiles(n=4, method="inclusive")`.

**Rentowność brutto grupy:**
```
grossYieldPct = 12 * median(r) / median(p) * 100
grossYieldRangePct = [12 * r25 / p75 * 100, 12 * r75 / p25 * 100]
```

**Oferta sprzedaży i o metrażu A, cenie P (EUR), cena za m² p_i = P/A:**
```
estimatedRentMonthlyEur = median(r) * A
grossYieldPct           = 12 * estimatedRentMonthlyEur / P * 100
discountVsMedianPct     = (median(p) - p_i) / median(p) * 100
```

**Ocena 0–100 (odporna na outliery, na logarytmie):**
```
MAD   = median(|ln p_j - median(ln p)|)  dla ofert sprzedaży w grupie
z     = (ln median(p) - ln p_i) / (1.4826 * MAD)
score = round(100 * Φ(z)),  Φ = dystrybuanta N(0,1) = 0.5 * (1 + erf(z / sqrt(2)))
```
Gdy `MAD == 0` → `score = 50` dla ceny równej medianie, inaczej 0 lub 100 zależnie od znaku. 50 = mediana, ~84 = tańsza o jedno typowe odchylenie, ~98 o dwa.

**Zaokrąglenia w wyniku:** EUR za m² do 1 zł/€ (int), najem za m² do 0,1, procenty do 0,01, kwoty EUR do int.

**Testy statystyki:** syntetyczne, małe zestawy z ręcznie policzonym wynikiem (w tym przypadek fallbacku, MAD = 0, jedna oferta w grupie).

---

## 10. Wejście (`.actor/input_schema.json`)

Domyślne uruchomienie bez ustawień ma dać sensowny wynik w kilka minut (Warszawa + Kraków, < 8 min; zmiana 2026-11-19, patrz §0 decyzja 14). Wszystkie `title`/`description` po angielsku.

| Pole | Typ | Domyślnie | Opis |
|---|---|---|---|
| `cities` | array (enum) | `["warszawa","krakow"]` | `warszawa, krakow, wroclaw, katowice` (Czechy w 1.1, §6.2a) |
| `mode` | string enum | `both` | `yieldReport` (tylko grupy), `scoreListings` (tylko oferty), `both` |
| `rooms` | array (enum tekstowy, multi-select) | `["1","2","3","4+"]` | `"4+"` = 4 i więcej; API przyjmuje też liczby 1–4 (§0 decyzja 11.5) |
| `areaMin` / `areaMax` | integer | 15 / 250 | m² |
| `samplingMode` | enum | `perDistrict` | `perDistrict` (kwota najnowszych ofert na dzielnicę) albo `city` (najnowsze N ofert miasta) |
| `maxListingsPerSide` | integer | 1500 | tryb `city`: limit ofert sprzedaży i osobno najmu na miasto |
| `maxListingsPerDistrict` | integer ≥ 0 | `0` | tryb `perDistrict`: limit na dzielnicę i stronę rynku; `0` = automatycznie `max(150, ceil(1500 / liczba_dzielnic))`; `maxListingsPerSide` jest wtedy ignorowany (opisz to w polu) |
| `minScore` | integer 0–100 | 0 | zwraca tylko oferty z oceną ≥ |
| `maxScoredListings` | integer ≥ 0 | 1000 | „Return at most this many listings, best deals first. 0 = all.” Limit po filtrach i sortowaniu; odcięte oferty w monitoringu nie są oznaczane jako widziane (§0 decyzja 11.1) |
| `includePrimaryMarket` | boolean | true | `true`: `market=ALL`, `isPrimaryMarket` = `true`/`null`; `false`: filtr portalu `market=SECONDARY`, `isPrimaryMarket` = `false` (§6.1) |
| `minSaleSample` / `minRentSample` | integer | 15 / 10 | próg grupy przed fallbackiem |
| `onlyNewOrChanged` | boolean | false | monitoring: tylko nowe oferty i obniżki |
| `watchlistName` | string | `default` | nazwa pamięci monitoringu; pole przemianowane 2026-11-24 z powodu rekomendacji quality score; `stateKey` przyjmowane dalej jako alias |
| `proxyConfiguration` | object (editor `proxy`) | `{"useApifyProxy": true}` (default i prefill; §0 decyzja 15.2; test H szedł przez grupę `BUYPROXIES94952`, którą mógłby użyć tylko właściciel) | Kod obsługuje oba warianty. Potwierdzone w źródle SDK `apify` 4.3.0 (`_actor.py`, `create_proxy_configuration`): czyta `useApifyProxy`, `apifyProxyCountry`, `apifyProxySubdivision`, `apifyProxyGroups`, `proxyUrls`; jawny argument `country_code=` ma pierwszeństwo przed inputem |

---

## 11. Wyjście

Dwa datasety (§0 decyzja 15.1): domyślny (`scoredListing`; przy `mode = yieldReport` także `areaYield`) i `yields` (`areaYield`). Typ rekordu w polu `recordType`. Nazwy pól camelCase. Przykład wartości to ilustracja struktury.

**`areaYield`:**
```json
{
  "recordType": "areaYield",
  "country": "CZ", "city": "Brno", "district": "Brno-střed", "rooms": "2",
  "groupLevel": "district", "confidence": "high",
  "saleCount": 112, "rentCount": 64,
  "salePricePerM2Eur": {"median": 4100, "p25": 3700, "p75": 4600},
  "rentPerM2MonthlyEur": {"median": 14.2, "p25": 12.8, "p75": 15.9},
  "grossYieldPct": 4.16, "grossYieldRangePct": [3.34, 5.16],
  "local": {"currency": "CZK", "salePricePerM2Median": 103000, "rentPerM2Median": 357},
  "fx": {"source": "ECB", "date": "2026-11-17", "eurToLocal": 25.1},
  "priceBasis": "asking", "sources": ["sreality"], "computedAt": "2026-11-17T18:00:00Z"
}
```

**`scoredListing`:**
```json
{
  "recordType": "scoredListing",
  "source": "otodom", "listingId": "66212262", "url": "https://www.otodom.pl/pl/oferta/...",
  "country": "PL", "city": "Kraków", "district": "Podgórze", "rooms": 2, "areaM2": 48,
  "isPrimaryMarket": false,
  "price": {"local": 610000, "currency": "PLN", "eur": 142900},
  "pricePerM2Eur": 2977, "groupMedianPricePerM2Eur": 3420,
  "dealScore": 87, "discountVsMedianPct": 12.95,
  "estimatedRentMonthlyEur": 690, "grossYieldPct": 5.79,
  "saleGroupLevel": "district", "rentGroupLevel": "city_rooms", "confidence": "medium",
  "priceCutPct": 4.7, "daysOnMarket": 38,
  "firstSeenAt": "2026-10-10", "changeType": "priceCut"
}
```
`changeType ∈ {"new", "priceCut", "unchanged"}` (w trybie bez monitoringu: `null`).

**`RUN_SUMMARY`** (key-value store, klucz `RUN_SUMMARY`; pola M3: `status`, `budgetReduced`, `maxChargeUsd`, `estimatedAuthorCostUsd`, `minMaxChargeUsd`, `chargeLimitReached`, `scoredAvailable`, `scoredReturned`, `prefillRun`, `events`, `records`, `totals`, `monitoring`; per strona rynku także `sample`, `primaryMarketProjects`, `proxySessions`): per miasto i strona rynku: liczba stron, ofert surowych, ofert po czyszczeniu, odrzucenia z powodami, zapytania zablokowane/błędne (kody), `buildIdRefreshes`, `fallbackToHtml`, czas; per miasto: odsetek grup z pełną próbą; kurs EBC; porównanie naszej mediany najmu za m² z `faqDynamicData.avgPricePerM` (Otodom). To jest też wynik pomiaru „weekend 1”.

**`.actor/dataset_schema.json`** (domyślny dataset; `yields_dataset_schema.json` ma tylko widok yieldów): dwa widoki tabeli: „Rental yield by district” (pola `areaYield`) i „Scored listings” (pola `scoredListing`, sortowanie po `dealScore`). Format widoków: sprawdź `https://docs.apify.com/platform/actors/development/actor-definition/dataset-schema`. Widoki nie filtrują po `recordType` — puste kolumny drugiego typu są akceptowalne; w trybie `both` dodatkowo zapisz pełny raport grup do key-value store pod `YIELD_REPORT`.

---

## 12. Monitoring (`src/monitor.py`)

Gdy `onlyNewOrChanged = true`: otwórz nazwany key-value store `cee-rental-yield-state` i rekord `{watchlistName}` (nazwa rekordu bez zmian) z mapą `dedup_key → {firstSeenAt, lastPriceLocal}`. Oferta nowa → `changeType = "new"`. Cena niższa o ≥ 1% → `"priceCut"`, `priceCutPct`. Bez zmian → nie zwracamy i nie naliczamy. Stan zapisuj na końcu udanego uruchomienia (przy błędzie nie nadpisuj). `firstSeenAt` zostaje na zawsze, `daysOnMarket` liczymy z `first_published` portalu, a gdy brak — z `firstSeenAt`.

---

## 13. HTTP, proxy, błędy (`src/http.py`) i pomiar

- Limiter: 1 zapytanie/s na domenę (otodom.pl, sreality.cz, ecb.europa.eu osobno). Miasta można przetwarzać równolegle, jeśli są z różnych domen.
- Retry: 3 próby z backoffem wykładniczym + jitter na 429/5xx/timeout. 403 i strona z captchą = blokada: licz w `blocked`, zmień sesję proxy, ponów raz.
- Jeśli blokady > 20% zapytań (min. 10 zapytań) w oknie **miasto × strona rynku** → przerwij to źródło z błędem opisowym („www.otodom.pl blocked X of Y requests (katowice sale); try residential proxy PL”). Okno, nie licznik skumulowany dla domeny (zrobione 2026-11-18).
- Proxy: `await Actor.create_proxy_configuration(actor_proxy_input=...)`, URL per sesja (`new_url(session_id=...)`). Lokalnie bez proxy — dostęp do proxy spoza Actorów jest na koncie wyłączony (§0 decyzja 8). Pierwszy test na platformie: datacenter `BUYPROXIES94952` (5 IP z USA) z rotacją sesji; blokady > 5% → stop i raport; residential PL po decyzji właściciela.
- `scripts/measure.py`: uruchamia pełne pobieranie dla wskazanych miast i wypisuje tabelę: strony, oferty, % blokad, czas, bajty pobrane (do szacowania kosztu proxy), % grup z pełną próbą.

**Bramka decyzyjna po weekendzie 1** (do zapisania w PR / README dla autora): blokady ≤ 5%, koszt proxy ≤ $1 na miasto (bajty × cena GB proxy), ≥ 70% oczyszczonych ofert sprzedaży porównanych na poziomie dzielnicy (`saleGroupLevel == "district"`; mianownik = wszystkie oczyszczone oferty sprzedaży miasta). Jeśli nie przechodzi — zmieniamy miasta, próbkowanie albo źródło, zanim powstanie reszta.

**Stan bramki (2026-11-18, domowe IP):** kryterium 1 — 0% blokad (do powtórzenia na Apify z proxy, M3); kryterium 2 — per dzielnica 150: max 48,4 MB/miasto → ≤ $0,39 przy $8/GB (bajty po dekompresji, górne oszacowanie); kryterium 3 — per dzielnica 150: Warszawa 98,0%, Kraków 96,2%, Wrocław 94,2% (Katowice 80,6%, informacyjnie). Uwaga: poziom `city` zawiera wszystkie oferty sprzedaży, więc oferta nieoceniana występuje tylko w mieście z < 15 ofertami sprzedaży.

---

## 14. Fixtures — co jest i co trzeba pobrać

**Jest:** `tests/fixtures/otodom_rent_katowice.json` — odpowiedź `_next/data` najmu w Katowicach (17.11.2026), 37 elementów (36 + wstawka `hpr/`), `pagination.totalItems = 770`, `faqDynamicData.avgPricePerM = 54`; `tests/fixtures/otodom_sale_katowice.json` — sprzedaż Katowice, 28 elementów (20 `FLAT` + 8 `INVESTMENT`); `tests/fixtures/ecb_daily.xml`. Obie fixtures Otodom przeszły przez `scripts/anonymize_fixture.py` (2026-11-18): nazwy osób, agencji i kontaktów („Agent Testowy N”, „Agencja Testowa N”, „Osoba Prywatna N”, „Kontakt Testowy N”), `firstName`/`lastName`, `userID`/`profileID`, adresy zdjęć, ulice, tytuły i opisy — także w zagnieżdżonych `relatedAds`; zdjęcia przycięte do jednego, mapy usunięte. Pozostałe pola i struktura są oryginalne. Wcześniejsze wersje usunięto z historii git (2026-11-18). `tests/test_fixtures_pii.py` sprawdza każdą fixture rekurencyjnie.

**Do pobrania przez autora (Claude Code: poproś o to, jeśli pliku nie ma):**

```bash
# 1) buildId Otodom
BUILD=$(curl -s 'https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice' \
  -H 'User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36' \
  | grep -o '"buildId":"[^"]*"' | cut -d'"' -f4)

# 2) Otodom sprzedaż Katowice
curl -s "https://www.otodom.pl/_next/data/$BUILD/pl/wyniki/sprzedaz/mieszkanie/slaskie/katowice/katowice/katowice.json?limit=36&page=1&ownerTypeSingleSelect=ALL&searchingCriteria=sprzedaz&searchingCriteria=mieszkanie&searchingCriteria=slaskie&searchingCriteria=katowice&searchingCriteria=katowice&searchingCriteria=katowice" \
  -H 'x-nextjs-data: 1' -H 'Accept: */*' \
  -H 'User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36' \
  > tests/fixtures/otodom_sale_katowice.json

# 3) [NIEAKTUALNE: Sreality wyłączone — §6.2; nie uruchamiać] Sreality Brno sprzedaż i najem
curl -s "https://www.sreality.cz/api/cs/v2/estates?category_main_cb=1&category_type_cb=1&locality_district_id=72&per_page=60&page=1" > tests/fixtures/sreality_sale_brno.json
curl -s "https://www.sreality.cz/api/cs/v2/estates?category_main_cb=1&category_type_cb=2&locality_district_id=72&per_page=60&page=1" > tests/fixtures/sreality_rent_brno.json

# 4) EBC
curl -s https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml > tests/fixtures/ecb_daily.xml
```

**Przed commitem każdej nowej fixture zanonimizuj ją** skryptem `scripts/anonymize_fixture.py` i uruchom `pytest tests/test_fixtures_pii.py`. Jeśli nowa fixture ma pola osobowe, których skrypt nie zna, rozszerz skrypt i strażnika, zanim zrobisz commit. Repo może być publiczne — danych osobowych w nim nie ma być nigdy.

---

## 15. Apify: konfiguracja, opłaty, wdrożenie

**`.actor/actor.json`** (sprawdź aktualny format w dokumentacji):
```json
{
  "actorSpecification": 1,
  "name": "cee-rental-yield",
  "title": "Poland Rental Yield & Property Deal Score",
  "description": "Gross rental yield by district and a 0–100 deal score for every apartment for sale in Warsaw, Kraków, Wrocław and Katowice. In EUR.",
  "version": "0.1",
  "buildTag": "latest",
  "input": "./input_schema.json",
  "storages": { "dataset": "./dataset_schema.json" },
  "dockerfile": "../Dockerfile"
}
```

**`Dockerfile`:** obraz `apify/actor-python:3.12`, `COPY requirements.txt`, `pip install`, `COPY src ./src`, `CMD ["python", "-m", "src"]`. Bez narzędzi przeglądarki.

**Pay-per-event** (ceny ustawia właściciel w Apify Console → Publication → Monetization; kod tylko nalicza zdarzenia):

| Zdarzenie | Cena | Kiedy naliczać |
|---|---|---|
| `area-yield` | $0.02 | po zapisaniu rekordu `areaYield` z `confidence` `high` lub `medium` |
| `scored-listing` | $0.004 | po zapisaniu rekordu `scoredListing` |

- Naliczaj przez SDK (`Actor.charge(event_name=..., count=...)` albo `push_data` z nazwą zdarzenia — **sprawdź aktualne API w dokumentacji SDK**).
- Respektuj limit kosztu ustawiony przez użytkownika (SDK zwraca informację o osiągnięciu limitu) — po osiągnięciu limitu przestań zapisywać rekordy i zakończ uruchomienie poprawnie, z notką w `RUN_SUMMARY`.
- Pusty wynik / blokada / błąd = zero zdarzeń.
- Lokalnie (bez platformy) naliczanie ma być no-op bez wyjątków. (SDK 4.3.0: poza modelem pay-per-event `Actor.charge` loguje jedno ostrzeżenie i zwraca `charged_count=0`.)
- **Tryb budżetowy** przy zbyt niskim limicie kosztu (§0 decyzja 10, `src/budget.py`); pola `RUN_SUMMARY`: `budgetReduced`, `maxChargeUsd`, `estimatedAuthorCostUsd` (oraz `requestedScopeCostUsd`, `minMaxChargeUsd`).
- **Limit kosztu:** pojemność ściśle poniżej limitu (`affordable_count` w `src/charging.py`), bo platforma przerywa run, gdy opłaty osiągną limit (§0 decyzja 12). Sprawdzone testem integracyjnym z prawdziwym SDK (`tests/test_integration_sdk.py`, ceny z `APIFY_ACTOR_PRICING_INFO`).
- **Zdarzenie syntetyczne `apify-default-dataset-item`** jest domyślnie włączone i nalicza się za każdy rekord w domyślnym datasecie — usuń je w Console. Kod i tak liczy pojemność budżetu z pełnej ceny rekordu (zdarzenie + syntetyczne), bo SDK przy braku budżetu przepuszcza 1 rekord ponad limit, a platforma wtedy przerywa uruchomienie (sprawdzone w lokalnym trybie testowym PPE 2026-11-18).
- **Codzienny test Apify** (https://docs.apify.com/platform/actors/publishing/test): uruchamia Actora z wartościami `prefill`, oczekuje statusu Succeeded i niepustego datasetu w ciągu 5 minut; kto płaci za test i czy test ustawia max charge — dokumentacja nie mówi. Prefill = zakres trybu budżetowego.
- **Koszty platformy płaci autor** (§0 decyzja 9): Apify potrąca je z wypłaty; zysk = 0,8 × przychód − koszty platformy (compute, proxy, transfer). Dlatego każdy koszt w M3 liczymy z perspektywy autora.

**Lokalne uruchamianie:** Apify CLI (`npm i -g apify-cli`), `apify login`, wejście w `storage/key_value_stores/default/INPUT.json`, `apify run --purge`. Testy: `pytest -q`.

**Wdrożenie:** Actor w Apify Console z źródłem „Git repository” wskazującym na to repo (gałąź `main`); dla repo prywatnego dodaj deploy key wygenerowany przez Apify w GitHub → Settings → Deploy keys. Build po każdym pushu na `main` (webhook z Apify). Najpierw Actor prywatny; publiczny dopiero po kamieniu milowym 3.

---

## 16. README (strona w Apify Store, po angielsku)

Sekcje: tytuł → dwa zdania „co i dla kogo” → **What you get** (yield per district, deal score, EUR) → **Quick start** (domyślne wejście + przykład dla Wrocławia i Krakowa) → **Output** (oba typy rekordów, przykłady) → **How the numbers are computed** (wzory z §9 prostym językiem, asking prices, gross not net) → **Why the numbers can be trusted** (pułapka czynszu Otodom, liczebność próby, confidence, brak danych osobowych, głośna porażka = $0) → **Monitoring** → **Pricing** (tabela zdarzeń; przykładowy koszt z pomiaru 2026-11-18 przy domyślnym próbkowaniu: Kraków ok. 2 970 ocenionych ofert ≈ $11.90 + ok. 49 grup ≈ $0.98; domyślne uruchomienie Warszawa + Kraków ≈ $27 — liczby z briefu M3) → **Limitations** (ceny ofertowe, nie transakcyjne; próba to bieżąca podaż — sortowanie LATEST, wiek próby w wyniku; kafelki inwestycji i `relatedAds` pomijane; brak stanu wykończenia — tania oferta może być do remontu; mały rynek najmu w Katowicach; na razie tylko Polska) → **FAQ** → **Data sources and responsible use** (tylko strony wyników, 1 req/s, bez danych osobowych, link do oferty zamiast kopii).

Gotowy początek (użyj go):

```markdown
# Rental Yield & Deal Score

Where does a rental apartment earn the most, and which listing is priced below its neighbourhood?
One run samples both sides of the local market – apartments for sale and for long-term rent – and returns:

- **Gross rental yield per district and room count**, with medians, quartiles and sample sizes.
- **A 0–100 deal score for every listing for sale**, against the median price per m² of comparable flats.
- **Everything in EUR** (ECB daily rate) next to the local currency, so cities compare directly.

Asking prices and advertised rents, honestly labelled. Gross, not net.
```

Dodatkowo w Apify: trzy „examples” (zapisane zadania z gotowym wejściem): „Rental yield by district in Warsaw”, „Underpriced 2-room flats in Kraków” (`minScore: 80`, `rooms: [2]`), „Warsaw vs Wrocław: where buy-to-let pays more”. (Przykłady z Pragą i Brnem — w 1.1.)

---

## 17. Kamienie milowe i definicja ukończenia

**M1 — źródła i pomiar (weekend 1)** — gotowe
- [x] szkielet repo z §5, `pytest` przechodzi
- [x] fixtures z §14 pobrane i zanonimizowane; skrypt `anonymize_fixture.py`
- [x] `sources/otodom.py`: discovery `buildId`, katalog `_next/data`, paginacja, fallback HTML, parser
- [x] `sources/sreality.py` — usunięte (robots.txt)
- [x] `clean.py` ze wszystkimi pułapkami z §6 i §8, z testami
- [x] `http.py` z limiterem, retry, licznikiem blokad, proxy
- [x] `scripts/measure.py` + pomiar 7 miast
- [x] **kryterium 3 bramki** dla 4 miast PL (metryka ważona ofertami, §13)
- [x] wyjaśnienie `not_flat` (kafelki `INVESTMENT`), sonda `by=LATEST` i `limit`
- [x] decyzja z bramki §13 — per dzielnica, kwota automatyczna (§0 decyzja 5)

**M2 — statystyka (weekend 2)** — gotowe (2026-11-18)
- [x] usunięcie Sreality z repo
- [x] czeskie źródło: przegląd alternatyw (§6.2a) — decyzja: `reality.idnes.cz` w 1.1
- [x] `fx.py` z testem na XML
- [x] `stats.py` ze wzorami z §9 (niezależny fallback sprzedaży i najmu), testy syntetyczne
- [x] `output.py`: rekordy `areaYield`, `scoredListing`, wpis `RUN_SUMMARY` per strona rynku (`build_side_summary`) — pełny `RUN_SUMMARY` przeniesiony do M3
- [x] ręczna weryfikacja 20 ofert (PL) — zaliczona przez właściciela (cena, metraż, pokoje, dzielnica)

**M3 — Actor (weekend 3)** — plan w briefie M3, czeka na akceptację
- [x] `main.py` (orkiestracja) i pełny `RUN_SUMMARY` (przeniesione z M2) — gałąź `m3`, test H zaliczony (§0 decyzja 14.8)
- [ ] `input_schema.json`, `dataset_schema.json`, `actor.json`, `Dockerfile`
- [ ] naliczanie zdarzeń + limit kosztu + $0 przy porażce
- [ ] monitoring (`monitor.py`) z testem
- [ ] README (§16), trzy przykłady
- [ ] test na prywatnym Actorze w Apify: domyślne uruchomienie < 8 min, koszt pełnej oceny miasta < 25% przychodu z uruchomienia
- [ ] **ponowny pomiar blokad na platformie Apify z proxy** (M1 mierzył z domowego IP bez proxy) — najpierw datacenter `BUYPROXIES94952`; > 5% blokad → stop i raport; kryterium 1 bramki obowiązuje dla środowiska produkcyjnego

**M4 — publikacja (weekend 4)**
- [x] kod: dataset `yields`, proxy bez grup, fallback monitoringu, `output_schema.json`, README pod Store (2026-11-19)
- [ ] test monitoringu w Console, test z drugiego konta (proxy, blokady, naliczanie), ceny PPE w Console, ujednolicenie ceny przykładowej (§0.15.5)
- [x] Actor publiczny w Apify Store pod `pl-datanest` (2026-11-20, build 0.0.25; §0.15.10); test z drugiego konta odpada (§0.15.11)

---

## 18. Jak pracować w tym repo

- Małe commity, opisowe wiadomości po angielsku. Jedna gałąź na kamień milowy, PR do `main`.
- Zanim napiszesz parser, otwórz fixture i potwierdź nazwy pól. Jeśli fixture brakuje — zatrzymaj się i poproś autora o jej pobranie (§14), nie pisz parsera „na pamięć”.
- Każda zmiana w `clean.py` i `stats.py` ma test.
- Logi: liczby i kody, nigdy treść ogłoszeń ani dane osobowe.
- Aktualizuj ten plik, gdy coś z **[DO WERYFIKACJI]** zostanie potwierdzone albo obalone: zamień oznaczenie na „potwierdzone (data, fixture)” albo popraw opis.

## 19. Otwarte pytania (stan 2026-11-18, wieczór, po PR #1)

Rozstrzygnięte: `robots.txt` Otodom, `transaction`, slugi miast, ścieżka i lista dzielnic (fixture + żywe: Warszawa 18, Wrocław 5), `INVESTMENT` = kafelki projektów, sortowanie LATEST + `limit=72`, definicja i mianownik bramki, nazwa produktu, przepisanie historii git, Sreality wyłączone.

Rozstrzygnięte też (2026-11-18, późno): wynik bramki po LATEST/72 (§13), klucze proxy w SDK (`apifyProxyCountry` czytane z inputu, §10), `limit=100` → po cichu 36, strona 1 HTML honoruje LATEST/72.

Rozstrzygnięte też (2026-11-18, wieczór): domyślne próbkowanie (per dzielnica, kwota automatyczna), 1.0 tylko Polska (Czechy w 1.1 przez `reality.idnes.cz`, `bezrealitky.cz` odpada), weryfikacja ręczna M2 zaliczona, strategia proxy w M3, perspektywa kosztów (płaci autor).

Rozstrzygnięte też (2026-11-19): `developmentId > 0` nie oznacza rynku pierwotnego (§6.1); decyzje 11.1–11.7 i 12 w §0.

Rozstrzygnięte też (2026-11-19, później): rynek pierwotny (a)+(b), J9/J10 potwierdzone, tożsamość git naprawiona (§0 decyzja 13).

Otwarte:
1. (c) dokładne oznaczanie rynku — po teście H, tylko jeśli mieszanie rynków zaburza mediany (§6.1).
2. Blokady i czas zapytania na platformie Apify z datacenter (5 IP z USA), potem ewentualnie residential PL (M3) — wpływa na „domyślne uruchomienie < 8 min”. Test H w toku.
3. Pytania z briefu M3 (sekcja „Ryzyka i otwarte pytania”).
4. Fakt (2026-11-20): dwa runy monitoringu pobrały identyczne bajty; przyczyna niezweryfikowana. Teksty dla użytkowników nie twierdzą nic o cache'u Otodomu.

        - 2026-11-25: opublikowany Actor `data-nest/imovirtual-rental-yield` (osobne repo `imovirtual-rental-yield`). README Otodom linkuje do niego w Roadmapie (tylko URL apify.com).
        - Przypomnienie: outliers w `scoredListing` – poprawić przy grudniowym buildzie (jak w imovirtual: nie zwracać, nie naliczać; licznik osobno w `RUN_SUMMARY`).
        - 2026-11-26: w README zanonimizowano URL oferty w przykładowym rekordzie (`"url": "…/pl/oferta/…"`; był tam pełny adres otodom.pl, a Store Publishing Terms 2.2.4.2(i) ograniczają linki poza apify.com). Inne domeny poza apify.com w README nie występowały. Roadmap w README linkuje do Actora Imovirtual (tylko URL apify.com).

## 20. Grudniowa runda – plan (decyzje 2026-11-25)

1. **Nowe miasta** (pomiar 2026-11-25; łączne oferty w portalu, pierwsza strona wyników, `market=ALL`):
   - pełna obsługa (≥ 300 ofert najmu): Katowice 765, Szczecin 562, Gdynia 488, Rzeszów 425, Lublin 384, Bydgoszcz 329;
   - całe miasto i liczba pokoi (150–300 ofert najmu; README: dzielnice ograniczone): Bielsko-Biała 223, Gliwice 216, Częstochowa 189, Białystok 188, Toruń 180;
   - odrzucone (< 150): Kielce 143 i mniejsze, Olsztyn 61, Elbląg 12. Olsztyn (457 sprzedaży) ma podejrzanie mało — sprawdzić slug przed ostatecznym odrzuceniem.
   - **Reguła na przyszłość:** ≥ 300 ofert najmu = pełna obsługa, 150–300 = całe miasto i liczba pokoi, < 150 = nie dodajemy.
   - Wyniki pomiaru: `scripts/out/city-counts-2026-11-25.csv` i `scripts/out/city-counts-2026-11-25b.csv` (nieśledzone).
2. **Slugi Otodom:** `{województwo}/{miasto}/{miasto}/{miasto}`, ASCII bez polskich znaków, spacja → „-”, **łącznik w nazwie → „--”** w każdym segmencie, w którym występuje (`kujawsko--pomorskie`, `warminsko--mazurskie`, `slaskie/bielsko--biala/bielsko--biala/bielsko--biala`). Działające slugi nowych miast (każdy rozwinięty do 4 segmentów): `zachodniopomorskie/szczecin`, `lubelskie/lublin`, `kujawsko--pomorskie/bydgoszcz`, `podlaskie/bialystok`, `slaskie/katowice`, `pomorskie/gdynia`, `slaskie/czestochowa`, `podkarpackie/rzeszow`, `kujawsko--pomorskie/torun`, `slaskie/gliwice`, `slaskie/bielsko--biala`.
3. **Błędy do poprawy w grudniowym buildzie:**
   a) `HttpClient.get` ma `allow_redirects=True`, więc przekierowanie omija limiter i nie jest liczone. Obsługiwać przekierowania ręcznie przez limiter, jak w `imovirtual-rental-yield` (maks. 1 skok, ta sama domena, cel pod `/pl/wyniki/`, liczone w zapytaniach).
   b) `HttpClient` robi 3 próby przy blokadzie. Przejrzeć: przy 403, 429 lub captcha koniec runu z czytelnym komunikatem, bez zmiany sesji proxy i bez obchodzenia. Ponowienie dopuszczalne tylko przy błędach sieci lub 5xx.
   c) (już zapisane w §19) outliers w `scoredListing`.
4. **Lista dzielnic urywa się na 32 pozycjach** (`searchLinksRelatedLocations`; Gdańsk, Bydgoszcz, Rzeszów, Kielce, Radom, Tychy). Przy `samplingMode = perDistrict` dzielnice spoza listy mogą nie trafić do próby. Do zbadania: dla miast z ≤ ok. 6 000 ofert sprzedaży pobierać cały rynek miasta (wszystkie strony), jak w Imovirtual; sprawdzić wpływ na Gdańsk.
5. **Strona z danymi datanest.dev** przy grudniowej aktualizacji: 7+ miast = nowy tytuł; sekcja porównania PL–PT na trzech stronach do odświeżenia.
