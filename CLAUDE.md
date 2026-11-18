# CLAUDE.md — cee-rental-yield

Ten plik opisuje wszystko, czego potrzebujesz, żeby zbudować Actora na Apify w tym repozytorium. Czytaj go w całości przed pierwszą zmianą i wracaj do niego przy każdej decyzji. Jeśli coś tu jest oznaczone **[DO WERYFIKACJI]**, sprawdź to na prawdziwej odpowiedzi serwisu (fixture albo żywe zapytanie) zanim na tym zbudujesz. Nigdy nie wymyślaj nazw pól — bierz je z fixture.

Repo: `https://github.com/data-nest-dev/cee-rental-yield` · Właściciel: datanest.dev (konto Apify: `pl-datanest`)

---

## 1. Co budujemy i dla kogo

**Produkt:** Actor Apify „Rental Yield & Deal Score – Poland & Czechia”. Jedno uruchomienie pobiera z portalu ogłoszenia mieszkań **na sprzedaż i na wynajem długoterminowy** w wybranych miastach i zwraca:

1. **Rentowność brutto najmu** per dzielnica × liczba pokoi (mediany, kwartyle, liczebność próby).
2. **Ocenę 0–100 każdej oferty sprzedaży** względem mediany ceny za m² jej grupy (dzielnica × pokoje) i szacowaną rentowność tej oferty.
3. Wszystko **w EUR** (kurs EBC) obok waluty lokalnej (PLN, CZK), żeby miasta z różnych krajów dało się porównać.

**Odbiorcy:** zagraniczni inwestorzy buy-to-let, proptech i wyceny automatyczne, fundusze najmu, analitycy, agenci AI wołający Actora przez MCP. Dlatego wszystkie teksty dla użytkownika (README, opisy pól, komunikaty błędów, tytuły) są **po angielsku**. Kod, komentarze i commity też po angielsku.

**Dlaczego to ma sens:** dla UK, Francji, DACH i USA takie Actory już istnieją (np. `lowlanddata/rightmove-yield-scanner`, `mocha_tassel/real-estate-deal-score` od $4/1000 ocenionych ofert). Dla Polski i Czech są tylko surowe scrapery albo same mediany ceny za m² (`lowlanddata/otodom-price-stats`). Wyróżniki: dwa kraje naraz, ocena każdej oferty, EUR, uczciwie opisane pułapki danych.

**To jest jeden Actor z wieloma źródłami**, nie osobny Actor na portal. Źródła to moduły w `src/sources/`. Klient podaje miasta, Actor sam wybiera źródło.

---

## 2. Zakres wersji

| Wersja | Kraj | Źródło | Miasta |
|---|---|---|---|
| 1.0 | Polska | Otodom | Warszawa, Kraków, Wrocław (+ Katowice jako miasto testowe) |
| 1.0 | Czechy | Sreality | Praha, Brno, Ostrava |
| 1.1 | Włochy | Immobiliare | Milano, Roma, Napoli (NIE w tym etapie) |

**W zakresie 1.0:** mieszkania (flats), sprzedaż + najem długoterminowy, rynek wtórny i pierwotny razem (z flagą `isPrimaryMarket`), rentowność per dzielnica × pokoje, ocena ofert sprzedaży, tryb monitoringu (tylko nowe oferty i obniżki), EUR + waluta lokalna.

**Poza zakresem 1.0:** domy, działki, lokale użytkowe, najem krótkoterminowy, rentowność netto, ceny transakcyjne (RCN), zdjęcia, opisy, dane kontaktowe, strony szczegółów ogłoszeń.

---

## 3. Zasady, których nie wolno łamać

1. **Tylko strony wyników wyszukiwania.** Nigdy nie otwieraj pojedynczych ogłoszeń (strony szczegółów). Wszystko, czego potrzebujemy, jest w katalogu.
2. **Zero danych osobowych w wyniku i w logach.** Usuwaj przy parsowaniu, zanim cokolwiek zapiszesz: imiona, nazwiska, telefony, e-maile, nazwy agencji, nazwy właścicieli ogłoszeń, zdjęcia, opisy. Patrz §7.
3. **Wynik to nasze wyliczenia + link do ogłoszenia**, nie kopia ogłoszenia. Zwracamy cenę, metraż, pokoje, dzielnicę, wskaźniki i URL. Bez tytułów ogłoszeń w rekordach wyjściowych (tytuł może zawierać dane osobowe i jest treścią portalu).
4. **Tempo:** maksymalnie 1 zapytanie na sekundę na domenę. Szanuj `robots.txt` (sprawdź aktualny dla każdej domeny, **[DO WERYFIKACJI]** czy `/_next/data/` na otodom.pl nie jest zablokowane).
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
│       ├── otodom.py
│       └── sreality.py
├── scripts/
│   └── measure.py                # pomiar „weekend 1”, żywe zapytania, wynik do konsoli/JSON
└── tests/
    ├── fixtures/
    │   ├── otodom_rent_katowice.json     # JEST (zanonimizowana próbka _next/data, najem Katowice)
    │   ├── otodom_sale_katowice.json     # DO POBRANIA (§14)
    │   ├── sreality_sale_brno.json       # DO POBRANIA (§14)
    │   └── sreality_rent_brno.json       # DO POBRANIA (§14)
    ├── test_otodom_parse.py
    ├── test_sreality_parse.py
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
    ?page={n}&limit=36&ownerTypeSingleSelect=ALL&by=DEFAULT&direction=DESC&distanceRadius=0
    &searchingCriteria={transaction}&searchingCriteria=mieszkanie
    &searchingCriteria={seg1}&searchingCriteria={seg2}&searchingCriteria={seg3}&searchingCriteria={seg4}
```

- `transaction`: `sprzedaz` albo `wynajem`
- `locationPath`: 4 segmenty `województwo/powiat/gmina/miasto`, każdy segment idzie też jako kolejny `searchingCriteria` w tej samej kolejności
- nagłówki: realistyczny `User-Agent` (Chrome), `Accept: */*`, `x-nextjs-data: 1`, `Referer: https://www.otodom.pl/pl/wyniki/{transaction}/mieszkanie/{locationPath}`
- odpowiedź: `{"pageProps": {...}, "__N_SSP": true}`

**Discovery `buildId`:** `buildId` zmienia się przy każdym wdrożeniu Otodom. Raz na uruchomienie pobierz HTML strony wyników:
`GET https://www.otodom.pl/pl/wyniki/{transaction}/mieszkanie/{locationPath}`, wyciągnij `<script id="__NEXT_DATA__" type="application/json">…</script>`, sparsuj JSON, weź `buildId`. Ten sam JSON ma `props.pageProps` = dane strony 1 (użyj ich, nie pobieraj strony 1 drugi raz). Gdy `_next/data` zwróci 404 → odśwież `buildId` jeden raz → jeśli dalej źle, przejdź na pobieranie stron HTML (`?page=N`) i parsuj `__NEXT_DATA__` z każdej.

**Lokalizacje (slug = locationPath):**

| Miasto (input) | locationPath | Status |
|---|---|---|
| `katowice` | `slaskie/katowice/katowice/katowice` | potwierdzone (fixture) |
| `warszawa` | `mazowieckie/warszawa/warszawa/warszawa` | [DO WERYFIKACJI] |
| `krakow` | `malopolskie/krakow/krakow/krakow` | [DO WERYFIKACJI] |
| `wroclaw` | `dolnoslaskie/wroclaw/wroclaw/wroclaw` | [DO WERYFIKACJI] |

Weryfikacja: w odpowiedzi `pageProps.tracking.listing.selected_locations_id` musi być `["city:{locationPath}"]`.

**Struktura odpowiedzi (potwierdzona w `tests/fixtures/otodom_rent_katowice.json`):**

- `pageProps.data.searchAds.items[]` — oferty (36 na stronę; może trafić się 37. element — wstawka reklamowa, patrz pułapki)
- `pageProps.data.searchAds.pagination` — `{itemsPerPage, totalItems, totalPages, currentPage}`
- `pageProps.faqDynamicData` — agregaty Otodom: `avgPrice`, `avgAreaM`, `avgPricePerM` (Katowice najem: 54) — używaj jako testu sensowności naszej mediany, nie jako danych
- `pageProps.searchLinksRelatedLocations.items[]` — `{name, location}` dzielnic miasta (slug dzielnicy w `location`)
- `pageProps.tracking.listing` — `result_count`, `page_count`, `results_per_page`, `selected_locations_id`

**Pola oferty, których używamy** (`items[]`):

| Pole Otodom | Znaczenie | Uwagi |
|---|---|---|
| `id` | ID oferty | int |
| `slug` | slug, np. `mieszkanie-2-pokoje-bogucice-koszutka-ID4E1Sb` | klucz deduplikacji; URL oferty = `https://www.otodom.pl/pl/oferta/{slug}` |
| `href` | ścieżka | jeśli zaczyna się od `hpr/` → wstawka reklamowa, odrzuć |
| `estate` | `FLAT` | filtruj tylko `FLAT` |
| `transaction` | `SELL` / `RENT` | **potwierdzone (2026-11-18, fixture otodom_sale_katowice.json)**: sprzedaż = `"SELL"` |
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
| `developmentId`, `investmentState`, `investment*` | dane inwestycji deweloperskiej | kandydat na `isPrimaryMarket` (§6.1 rynek) |
| `isPrivateOwner`, `extendedAdvertiserType` | typ ogłoszeniodawcy | możemy zwrócić `advertiserType: "private"|"business"` |
| `isPromoted` | promowane | ignoruj |

**Pola, które musisz usunąć natychmiast po wczytaniu** (dane osobowe / treść): `advertOwner` (całe), `organisationAssignedMember` (całe), `agency` (całe; nazwy agencji JDG to imiona i nazwiska), `images`, `title`, `shortDescription`, `location.address` (ulica).

**Rynek pierwotny/wtórny:** **potwierdzone (2026-11-18, fixture otodom_sale_katowice.json)**: oferty deweloperskie mają `developmentId > 0` (5/28 w próbce Katowice). `investmentState` bywa `null` nawet przy `developmentId > 0`. Reguła: `isPrimaryMarket = developmentId is not None and developmentId > 0`.

**Sortowanie i próbkowanie:** domyślnie bierzemy pierwsze `maxListingsPerSide` ofert każdej strony rynku. Lepsza próba to najnowsze ogłoszenia: **[DO WERYFIKACJI]** parametr `by=LATEST&direction=DESC`. Jeśli działa, użyj go.

**Pułapki Otodom (każda musi mieć test):**

1. `rentPrice` w ogłoszeniach SPRZEDAŻY to czynsz do wspólnoty (inny scraper zmierzył: mediana 731 PLN przy medianie ceny 586 200 PLN). Nigdy nie traktuj go jako najmu.
2. W ogłoszeniach NAJMU najem = `totalPrice.value`, czynsz administracyjny = `rentPrice.value`. Do rentowności bierzemy **sam najem bez czynszu** (właściciel przekazuje czynsz wspólnocie).
3. **Zamienione pola:** w fixture oferta `id=68642713` ma `totalPrice=600`, `rentPrice=1900` przy 63,77 m². Reguła: najem z `rentPrice > totalPrice` → odrzuć z median i policz w `RUN_SUMMARY.rejected.swappedRent`.
4. **Wstawka reklamowa:** w fixture element `id=9000062324` ma `href` zaczynające się od `hpr/`, puste `images`, `dateCreated = "1999-02-29 00:00:01"` (nieistniejąca data) i jest kopią `id=68645667` (ten sam `slug`). Odrzucaj `href.startswith("hpr/")`, deduplikuj po `slug`, parsuj daty defensywnie (błędna data → `None`, nie wyjątek).
5. Ukryta cena: `totalPrice == null` albo `hidePrice == true` → odrzuć.
6. Stare oferty stale podbijane (np. `createdAtFirst` z 2023) — to nie błąd, to sygnał (`daysOnMarket` duże).
7. Oferta spoza miasta: zostaw tylko te, których `reverseGeocoding.locations[]` zawiera `id == locationPath` miasta.

### 6.2 Sreality (Czechy)

**Dostęp:** nieudokumentowane JSON API serwisu (używane przez kilka Actorów w Apify Store, brak DataDome/Akamai):

```
GET https://www.sreality.cz/api/cs/v2/estates
    ?category_main_cb=1            # 1 = byty (mieszkania)
    &category_type_cb=1            # 1 = prodej (sprzedaż), 2 = pronájem (najem)
    &locality_region_id=10         # Praha  [DO WERYFIKACJI]
    &locality_district_id=72       # Brno-město  [DO WERYFIKACJI]
    &per_page=60&page={n}
```

**potwierdzone (2026-11-18):** Sreality przeszło na Next.js. Endpoint `/api/cs/v2/estates` zwraca 404. Dane dostępne przez:
1. HTML strony wyników z osadzonym `__NEXT_DATA__` JSON (tak jak Otodom)
2. `_next/data/{buildId}/cs/hledani/{tx}/byty/{city}.json?strana={page}` z nagłówkiem `x-nextjs-data: 1`

Dane w `pageProps.dehydratedState.queries[]` pod kluczem `estatesSearch`. Paginacja: `{limit: 22, offset, total, totalWithPromo}`. Wyniki w `state.data.results[]`. Oferta: `id` (int), `name` (np. "Prodej bytu 2+kk 54 m²"), `priceCzk` (int), `priceCzkPerSqM` (int), `locality` (obiekt z `city`, `cityPart` = dzielnica, `district`, `districtId`, `citySeoName`), `categorySubCb` ({name, value} — np. "2+kk"/4), `categoryTypeCb` ({name, value} — 1=prodej, 2=pronájem).

**Lokalizacje (do weryfikacji na żywo):**

| Miasto | Parametr | Wartość |
|---|---|---|
| `praha` | `locality_region_id` | 10 [DO WERYFIKACJI] |
| `brno` | `locality_district_id` | 72 **potwierdzone (2026-11-18, fixture sreality_sale_brno.json)** — ale uwaga: Sreality przeszło na Next.js, stary parametr nie działa. URL: `/hledani/prodej/byty/brno` |
| `ostrava` | `locality_district_id` | [DO USTALENIA] |

**Pola (potwierdzone 2026-11-18, fixture sreality_sale_brno.json):** odpowiedź w `dehydratedState.queries[estatesSearch].state.data`: `{pagination: {limit, offset, total, totalWithPromo}, results: [...]}`. Oferta: `id` (int), `name` (np. „Prodej bytu 2+kk 54 m²”), `locality` (obiekt: `city`, `cityPart`, `citySeoName`, `district`, `districtId`, `quarter`, `quarterId`), `priceCzk` (int), `priceCzkPerSqM` (int), `categorySubCb` ({name, value}), `categoryTypeCb` ({name, value}), `premiseId` (ID agencji, null = prywatny). URL oferty: `https://www.sreality.cz/detail/{categoryTypeCb.name.lower()}/byt/{categorySubCb.name.lower()}/{citySeoName}/{id}`.

**Parsowanie:**
- metraż z `name`: regex `(\d+(?:[.,]\d+)?)\s*m²`
- układ z `name`: regex `(\d)\s*\+\s*(kk|\d)`; liczba pokoi = pierwsza cyfra (`2+kk` i `2+1` → 2). „Atypický”, „pokoj” → `None`, odrzuć.
- dzielnica: **potwierdzone (2026-11-18)** — `locality.cityPart` zawiera nazwę dzielnicy (np. „Žebětín”, „Trnitá”); `locality.quarter` zawiera szerszą nazwę (np. „Brno-Žebětín”). Używamy `cityPart` jako district.
- najem: `price` to miesięczny czynsz najmu; tekstowe „+ poplatky”, „+ energie” ignorujemy (bierzemy sam najem)

**Pułapki Sreality:**
1. Ceny zastępcze → odrzuć gdy `priceCzk <= 1` **potwierdzone (2026-11-18)**: w fixture nie widać takiego przypadku, ale logika jest zaimplementowana w parserze.
2. Licytacje/dražby w wynikach (jeśli są oznaczone) → odrzuć z median.
3. Duplikaty między stronami → deduplikuj po `hash_id`.

### 6.3 Kurs walut (EBC)

`GET https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml` — elementy `<Cube currency="PLN" rate="..."/>`, `<Cube currency="CZK" rate="..."/>`; `rate` = ile jednostek waluty za 1 EUR. Zapisz datę kursu (`<Cube time="YYYY-MM-DD">`). Brak kursu → uruchomienie kończy się błędem (nie wymyślaj kursu). Test na zapisanym XML.

---

## 7. Model danych wewnętrznych (`src/models.py`)

```python
@dataclass
class Listing:
    source: str               # "otodom" | "sreality"
    listing_id: str
    dedup_key: str            # otodom: slug, sreality: hash_id
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

**Fallback:** grupa potrzebuje `saleCount ≥ minSaleSample` (domyślnie 15) **i** `rentCount ≥ minRentSample` (domyślnie 10). Jeśli dzielnica nie spełnia → `(city, roomsBucket)` → `(city)`. Zapisz `groupLevel ∈ {"district", "city_rooms", "city"}`.

**Pewność `confidence`:** `high` gdy `groupLevel == "district"` i `saleCount ≥ 40`; `medium` gdy `groupLevel == "district"` (15–39) albo `city_rooms`; `low` gdy `city`.

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

Domyślne uruchomienie bez ustawień ma dać sensowny wynik w kilka minut (Warszawa + Praha). Wszystkie `title`/`description` po angielsku.

| Pole | Typ | Domyślnie | Opis |
|---|---|---|---|
| `cities` | array (enum) | `["warszawa","praha"]` | `warszawa, krakow, wroclaw, katowice, praha, brno, ostrava` |
| `mode` | string enum | `both` | `yieldReport` (tylko grupy), `scoreListings` (tylko oferty), `both` |
| `rooms` | array int | `[1,2,3,4]` | 4 = 4 i więcej |
| `areaMin` / `areaMax` | integer | 15 / 250 | m² |
| `maxListingsPerSide` | integer | 1500 | limit ofert sprzedaży i osobno najmu na miasto |
| `minScore` | integer 0–100 | 0 | zwraca tylko oferty z oceną ≥ |
| `includePrimaryMarket` | boolean | true | czy liczyć rynek pierwotny |
| `minSaleSample` / `minRentSample` | integer | 15 / 10 | próg grupy przed fallbackiem |
| `onlyNewOrChanged` | boolean | false | monitoring: tylko nowe oferty i obniżki |
| `stateKey` | string | `default` | nazwa pamięci monitoringu |
| `outputCurrency` | enum | `EUR` | `EUR` / `local` — waluta sortowania; lokalna zawsze obecna |
| `proxyConfiguration` | object (editor `proxy`) | `{"useApifyProxy": true, "apifyProxyGroups": ["RESIDENTIAL"], "apifyProxyCountry": "PL"}` | Otodom: rezydencjalne PL; Sreality może iść bez rezydencjalnych |

---

## 11. Wyjście

Jeden dataset, typ rekordu w polu `recordType`. Nazwy pól camelCase. Przykład wartości to ilustracja struktury.

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
  "groupLevel": "district", "confidence": "high",
  "priceCutPct": 4.7, "daysOnMarket": 38,
  "firstSeenAt": "2026-10-10", "changeType": "priceCut"
}
```
`changeType ∈ {"new", "priceCut", "unchanged"}` (w trybie bez monitoringu: `null`).

**`RUN_SUMMARY`** (key-value store, klucz `RUN_SUMMARY`): per miasto i strona rynku: liczba stron, ofert surowych, ofert po czyszczeniu, odrzucenia z powodami, zapytania zablokowane/błędne (kody), `buildIdRefreshes`, `fallbackToHtml`, czas; per miasto: odsetek grup z pełną próbą; kurs EBC; porównanie naszej mediany najmu za m² z `faqDynamicData.avgPricePerM` (Otodom). To jest też wynik pomiaru „weekend 1”.

**`.actor/dataset_schema.json`:** dwa widoki tabeli: „Rental yield by district” (pola `areaYield`) i „Scored listings” (pola `scoredListing`, sortowanie po `dealScore`). Format widoków: sprawdź `https://docs.apify.com/platform/actors/development/actor-definition/dataset-schema`. Widoki nie filtrują po `recordType` — puste kolumny drugiego typu są akceptowalne; w trybie `both` dodatkowo zapisz pełny raport grup do key-value store pod `YIELD_REPORT`.

---

## 12. Monitoring (`src/monitor.py`)

Gdy `onlyNewOrChanged = true`: otwórz nazwany key-value store `cee-rental-yield-state` i rekord `{stateKey}` z mapą `dedup_key → {firstSeenAt, lastPriceLocal}`. Oferta nowa → `changeType = "new"`. Cena niższa o ≥ 1% → `"priceCut"`, `priceCutPct`. Bez zmian → nie zwracamy i nie naliczamy. Stan zapisuj na końcu udanego uruchomienia (przy błędzie nie nadpisuj). `firstSeenAt` zostaje na zawsze, `daysOnMarket` liczymy z `first_published` portalu, a gdy brak — z `firstSeenAt`.

---

## 13. HTTP, proxy, błędy (`src/http.py`) i pomiar

- Limiter: 1 zapytanie/s na domenę (otodom.pl, sreality.cz, ecb.europa.eu osobno). Miasta można przetwarzać równolegle, jeśli są z różnych domen.
- Retry: 3 próby z backoffem wykładniczym + jitter na 429/5xx/timeout. 403 i strona z captchą = blokada: licz w `blocked`, zmień sesję proxy, ponów raz.
- Jeśli blokady > 20% zapytań do domeny → przerwij to źródło z błędem opisowym („Otodom blocked X of Y requests; try residential proxy PL”).
- Proxy: `await Actor.create_proxy_configuration(actor_proxy_input=...)`, URL per sesja. Lokalnie bez Apify proxy (zmienna środowiskowa lub brak tokena) → bez proxy.
- `scripts/measure.py`: uruchamia pełne pobieranie dla wskazanych miast i wypisuje tabelę: strony, oferty, % blokad, czas, bajty pobrane (do szacowania kosztu proxy), % grup z pełną próbą.

**Bramka decyzyjna po weekendzie 1** (do zapisania w PR / README dla autora): blokady ≤ 5%, koszt proxy ≤ $1 na miasto (bajty × cena GB proxy), ≥ 70% grup dzielnica × pokoje z pełną próbą. Jeśli nie przechodzi — zmieniamy miasta, próbkowanie albo źródło, zanim powstanie reszta.

---

## 14. Fixtures — co jest i co trzeba pobrać

**Jest:** `tests/fixtures/otodom_rent_katowice.json` — odpowiedź `_next/data` najmu w Katowicach (17.11.2026), 37 elementów (36 + wstawka `hpr/`), `pagination.totalItems = 770`, `faqDynamicData.avgPricePerM = 54`. Imiona, nazwiska i nazwy agencji są **zanonimizowane** („Agent Testowy N”, „Agencja Testowa N”, „Osoba Prywatna N”), zdjęcia przycięte do jednego, mapy usunięte. Struktura i wszystkie pozostałe pola są oryginalne.

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

# 3) Sreality Brno sprzedaż i najem (ID lokalizacji do weryfikacji)
curl -s "https://www.sreality.cz/api/cs/v2/estates?category_main_cb=1&category_type_cb=1&locality_district_id=72&per_page=60&page=1" > tests/fixtures/sreality_sale_brno.json
curl -s "https://www.sreality.cz/api/cs/v2/estates?category_main_cb=1&category_type_cb=2&locality_district_id=72&per_page=60&page=1" > tests/fixtures/sreality_rent_brno.json

# 4) EBC
curl -s https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml > tests/fixtures/ecb_daily.xml
```

**Przed commitem każdej nowej fixture zanonimizuj ją** skryptem `scripts/anonymize_fixture.py` (napisz go: podmień `advertOwner`, `organisationAssignedMember`, `agency.name/slug`, kontakty, ulice na wartości testowe; przytnij `images` do jednego; usuń mapy). Repo może być publiczne — danych osobowych w nim nie ma być nigdy.

---

## 15. Apify: konfiguracja, opłaty, wdrożenie

**`.actor/actor.json`** (sprawdź aktualny format w dokumentacji):
```json
{
  "actorSpecification": 1,
  "name": "cee-rental-yield",
  "title": "Rental Yield & Deal Score – Poland & Czechia",
  "description": "Gross rental yield by district and a 0–100 deal score for every apartment for sale in Warsaw, Kraków, Wrocław, Prague, Brno and Ostrava. In EUR.",
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
- Lokalnie (bez platformy) naliczanie ma być no-op bez wyjątków.

**Lokalne uruchamianie:** Apify CLI (`npm i -g apify-cli`), `apify login`, wejście w `storage/key_value_stores/default/INPUT.json`, `apify run --purge`. Testy: `pytest -q`.

**Wdrożenie:** Actor w Apify Console z źródłem „Git repository” wskazującym na to repo (gałąź `main`); dla repo prywatnego dodaj deploy key wygenerowany przez Apify w GitHub → Settings → Deploy keys. Build po każdym pushu na `main` (webhook z Apify). Najpierw Actor prywatny; publiczny dopiero po kamieniu milowym 3.

---

## 16. README (strona w Apify Store, po angielsku)

Sekcje: tytuł → dwa zdania „co i dla kogo” → **What you get** (yield per district, deal score, EUR) → **Quick start** (domyślne wejście + przykład dla Brna i Krakowa) → **Output** (oba typy rekordów, przykłady) → **How the numbers are computed** (wzory z §9 prostym językiem, asking prices, gross not net) → **Why the numbers can be trusted** (pułapka czynszu Otodom, liczebność próby, confidence, brak danych osobowych, głośna porażka = $0) → **Monitoring** → **Pricing** (tabela zdarzeń, przykładowy koszt: Kraków ok. 24 grupy ≈ $0.50, 1500 ocenionych ofert = $6) → **Limitations** (ceny ofertowe, nie transakcyjne; brak stanu wykończenia — tania oferta może być do remontu; tylko wymienione miasta) → **FAQ** → **Data sources and responsible use** (tylko strony wyników, 1 req/s, bez danych osobowych, link do oferty zamiast kopii).

Gotowy początek (użyj go):

```markdown
# Rental Yield & Deal Score – Poland & Czechia

Where does a rental apartment earn the most in Central Europe, and which listing is priced below its neighbourhood?
One run samples both sides of the local market – apartments for sale and for long-term rent – and returns:

- **Gross rental yield per district and room count**, with medians, quartiles and sample sizes.
- **A 0–100 deal score for every listing for sale**, against the median price per m² of comparable flats.
- **Everything in EUR** (ECB daily rate) next to PLN or CZK, so Warsaw and Prague compare directly.

Asking prices and advertised rents, honestly labelled. Gross, not net.
```

Dodatkowo w Apify: trzy „examples” (zapisane zadania z gotowym wejściem): „Rental yield by district in Prague”, „Underpriced 2-room flats in Kraków” (`minScore: 80`, `rooms: [2]`), „Brno vs Wrocław: where buy-to-let pays more”.

---

## 17. Kamienie milowe i definicja ukończenia

**M1 — źródła i pomiar (weekend 1)**
- [ ] szkielet repo z §5, `pytest` przechodzi
- [ ] fixtures z §14 pobrane i zanonimizowane; skrypt `anonymize_fixture.py`
- [ ] `sources/otodom.py`: discovery `buildId`, katalog `_next/data`, paginacja, fallback HTML, parser → surowe elementy
- [ ] `sources/sreality.py`: katalog, paginacja, parser
- [ ] `clean.py` ze wszystkimi pułapkami z §6 i §8, każda z testem (w tym `id=68642713` zamienione pola, `id=9000062324` wstawka `hpr/`)
- [ ] `http.py` z limiterem, retry, licznikiem blokad, proxy
- [ ] `scripts/measure.py` + wyniki pomiaru dla 6 miast (+ Katowice) w opisie PR
- [ ] decyzja z bramki §13

**M2 — statystyka (weekend 2)**
- [ ] `fx.py` z testem na XML
- [ ] `stats.py` ze wzorami z §9, testy syntetyczne
- [ ] `output.py`: rekordy `areaYield`, `scoredListing`, `RUN_SUMMARY`
- [ ] ręczna weryfikacja 20 ofert na kraj (cena/m², przypisanie grupy) — lista w PR

**M3 — Actor (weekend 3)**
- [ ] `input_schema.json`, `dataset_schema.json`, `actor.json`, `Dockerfile`
- [ ] naliczanie zdarzeń + limit kosztu + $0 przy porażce
- [ ] monitoring (`monitor.py`) z testem
- [ ] README (§16), trzy przykłady
- [ ] test na prywatnym Actorze w Apify: domyślne uruchomienie < 5 min, koszt pełnej oceny miasta < 25% przychodu z uruchomienia

**M4 — publikacja (weekend 4)**
- [ ] Actor publiczny w Apify Store pod `pl-datanest`, ceny ustawione przez właściciela

---

## 18. Jak pracować w tym repo

- Małe commity, opisowe wiadomości po angielsku. Jedna gałąź na kamień milowy, PR do `main`.
- Zanim napiszesz parser, otwórz fixture i potwierdź nazwy pól. Jeśli fixture brakuje — zatrzymaj się i poproś autora o jej pobranie (§14), nie pisz parsera „na pamięć”.
- Każda zmiana w `clean.py` i `stats.py` ma test.
- Logi: liczby i kody, nigdy treść ogłoszeń ani dane osobowe.
- Aktualizuj ten plik, gdy coś z **[DO WERYFIKACJI]** zostanie potwierdzone albo obalone: zamień oznaczenie na „potwierdzone (data, fixture)” albo popraw opis.

## 19. Otwarte pytania (do rozstrzygnięcia w M1)

1. Czy `/_next/data/` na otodom.pl jest dozwolone w aktualnym `robots.txt`?
2. Wartość `transaction` dla sprzedaży w Otodom (`SELL`?) i czy `developmentId` oznacza rynek pierwotny.
3. Czy działa `by=LATEST` i jaki jest maksymalny `limit` na stronę (36? 72?).
4. Slugi Otodom dla Warszawy, Krakowa, Wrocławia.
5. Aktualny endpoint Sreality, ID lokalizacji Praha/Brno/Ostrava, format cen zastępczych, wzór URL oferty.
6. Czy Otodom ogranicza liczbę stron wyników dla dużych miast (Warszawa) — jeśli tak, próbkowanie per dzielnica przez `searchLinksRelatedLocations`.
