# Otodom Rental Yield & Deal Score – Poland

This Actor calculates the price per m² by district and the gross rental yield by district and room count, and gives every flat for sale a deal score, using Otodom listings for Warsaw, Kraków, Wrocław, Łódź, Poznań and Gdańsk. Prices are in EUR and PLN. Use it for rental yield in Poland, price per m² by district and spotting flats priced below their neighbourhood, whether you are a buy-to-let investor or an analyst. One run samples apartments for sale and for long-term rent and returns:

- **Gross rental yield per district and room count**, with medians, quartiles and sample sizes.
- **A 0–100 deal score for every listing for sale**, against the median price per m² of comparable flats.
- **Everything in EUR** (ECB daily rate) next to the local currency, so cities compare directly.

Asking prices and advertised rents, honestly labelled. Gross, not net.

## Example output

Six rows of a yield report for Łódź (Apify run `kXpCp4wihublvax0d`, ECB rate 4.4588 PLN per EUR):

| District | Rooms | Confidence | Sales / rents (sample) | Sale median EUR/m² | Rent median EUR/m²/mo | Gross yield |
|---|---|---|---|---|---|---|
| Śródmieście | 1 | medium | 24 / 67 | 2195 | 16.4 | 8.99% |
| Bałuty | 1 | high | 45 / 38 | 1951 | 12.5 | 7.67% |
| Górna | 1 | high | 41 / 23 | 2063 | 13.5 | 7.83% |
| Polesie | 2 | high | 124 / 101 | 2176 | 12.2 | 6.74% |
| Widzew | 3 | high | 71 / 29 | 1962 | 10.2 | 6.21% |
| Bałuty | 3 | high | 77 / 29 | 2007 | 9.3 | 5.53% |

Data from 2026-11-23, asking prices; an excerpt of the 20 groups returned for Łódź.

## How to use it without code

1. Open the Actor in Apify Console.
2. Choose the cities and the mode: `yieldReport`, `scoreListings` or `both`.
3. Click **Start**.
4. Download the results as Excel, CSV or JSON from the Output tab. Yield groups are in the `yields` dataset, except in `yieldReport` mode, where they are in the default dataset.

The first run with the default example (prefill: Warsaw, the 360 newest listings) costs about $1.70 and takes under a minute.

## What you get

- **Yield by district** (`areaYield` records): for every district × room group, the median sale price per m², the median monthly rent per m², quartiles, the number of listings behind each number, and the gross yield with a range. Groups with too few listings fall back to the city level and say so (`groupLevel`, `confidence`).
- **Scored listings** (`scoredListing` records): for every apartment for sale, a 0–100 deal score, its discount against comparable flats, an estimated monthly rent and gross yield, and a link to the listing. Sorted best deal first.
- **Sample transparency**: every yield record reports how recent its sample is (median age, oldest listing) and what share of all listings it covers.
- **Two datasets**: scored listings in the default dataset, yield groups in a second dataset called `yields` (see *Where the results are*).
- **Two reports in the key-value store**: `YIELD_REPORT` (all groups, all levels) and `RUN_SUMMARY` (what was fetched, rejected and charged, per city and market side).

## Yields by city

Gross rental yield from test runs in November 2026 (asking prices and advertised rents, medians):

| City | Gross yield | Sale price, EUR/m² | Rent, EUR/month per m² |
|---|---|---|---|
| Łódź | 6.93% | 2,105 | 12.1 |
| Poznań | 5.68% | 2,795 | 13.2 |
| Wrocław | 5.68% | 3,028 | 14.3 |
| Gdańsk | 5.51% | 3,257 | 15.0 |
| Warsaw | 5.26% | 3,927 | 17.2 |
| Kraków | 5.01% | 3,482 | 14.5 |

The portal splits Wrocław, Łódź and Poznań into 5 large districts each and Gdańsk into 32 smaller ones (with the default minimum sample sizes about 12 of them are reported), so district-level results are not equally detailed across cities.

## Quick start

Run with no settings to analyse Warsaw and Kraków:

```json
{
  "cities": ["warszawa", "krakow"],
  "mode": "both"
}
```

More inputs are under *Example inputs* below.

**Proxy.** By default the Actor uses Apify Proxy in automatic mode, with the proxy groups available to your own account. You can pass your own `proxyConfiguration` instead. If Apify Proxy refuses the connection, for example because the selected group is not available to your account, the run fails with a message saying so, and none of the result events are charged.

## Example inputs

**Rental yield by district in Warsaw** – returns one yield record per district and room group, in the default dataset (with `mode: "yieldReport"` the yield records stay there).

```json
{"cities": ["warszawa"], "mode": "yieldReport"}
```

**Underpriced 2-room flats in Kraków** – returns scored listings of two-room flats with a deal score of at least 80, best deals first, in the default dataset.

```json
{"cities": ["krakow"], "mode": "scoreListings", "rooms": ["2"], "minScore": 80}
```

**Warsaw vs Wrocław: where buy-to-let pays more** – returns the yield records of both cities in the default dataset, so gross yields can be compared side by side.

```json
{"cities": ["warszawa", "wroclaw"], "mode": "yieldReport"}
```

## Where the results are

- **Scored listings** go to the run's default dataset. This is what `run-sync-get-dataset-items`, the API "last run dataset items" endpoints and the Export button return.
- **Yield groups** (`areaYield` records) go to a second dataset named `yields`. It is linked from the run's Output tab and listed in the Storage tab; its API URL is in the run's `output`. Keeping them apart means a call that reads only the default dataset gets listings that all have the same shape.
- **Exception:** with `mode: "yieldReport"` there are no scored listings, so the yield groups stay in the default dataset. Otherwise that call would return an empty response. The same groups are also copied to the `yields` dataset, so the yield view on the Output tab shows them.
- **`YIELD_REPORT`** in the key-value store always holds the groups of the run, whatever the mode.

## For AI agents

Call the Actor `data-nest/cee-rental-yield` from an agent or over MCP with a small input, for example one city in yield-report mode:

```json
{"cities": ["lodz"], "mode": "yieldReport"}
```

The result is a list of `areaYield` records in the default dataset, one per district and room group, with `city`, `district`, `rooms`, `groupLevel`, `confidence`, `saleCount`, `rentCount`, `salePricePerM2Eur.median`, `rentPerM2MonthlyEur.median`, `grossYieldPct`, `local.currency` and `fx.date`. Set a maximum charge per run to cap the cost.

## Output

An `areaYield` record (example values):

```json
{
  "recordType": "areaYield",
  "country": "PL", "city": "Kraków", "district": "Podgórze", "rooms": "2",
  "groupLevel": "district", "confidence": "high",
  "saleCount": 81, "rentCount": 108,
  "salePricePerM2Eur": {"median": 3610, "p25": 3240, "p75": 4050},
  "rentPerM2MonthlyEur": {"median": 17.3, "p25": 15.6, "p75": 19.4},
  "grossYieldPct": 5.75, "grossYieldRangePct": [4.62, 7.19],
  "local": {"currency": "PLN", "salePricePerM2Median": 15898, "rentPerM2Median": 76.2},
  "fx": {"source": "ECB", "date": "2026-11-17", "eurToLocal": 4.4038},
  "sample": {
    "sale": {"medianAgeDays": 19, "oldestListingDays": 1129, "share": 0.31},
    "rent": {"medianAgeDays": 20, "oldestListingDays": 640, "share": 0.74}
  },
  "priceBasis": "asking", "sources": ["otodom"]
}
```

A `scoredListing` record (example values):

```json
{
  "recordType": "scoredListing",
  "source": "otodom", "url": "…/pl/oferta/…",
  "country": "PL", "city": "Kraków", "district": "Podgórze", "rooms": 2, "areaM2": 48,
  "isPrimaryMarket": null,
  "price": {"local": 610000, "currency": "PLN", "eur": 138520},
  "pricePerM2Eur": 2886, "groupMedianPricePerM2Eur": 3610,
  "dealScore": 87, "discountVsMedianPct": 20.06,
  "estimatedRentMonthlyEur": 830, "grossYieldPct": 7.19,
  "saleGroupLevel": "district", "rentGroupLevel": "district", "confidence": "high",
  "daysOnMarket": 38, "flags": [], "changeType": null, "priceCutPct": null
}
```

`flags` lists reasons to look at a listing twice:

- `needsRenovation` – the listing says the flat needs renovation. It stays in the results and in the medians, so a cheap price may reflect the condition.
- `suspectRooms` – less than 8 m² per room (for example 7 rooms in 27 m²), so the room count looks wrong. The listing is compared at city level only, not within a room group; `rooms` in the record is unchanged.
- Listings priced more than 40% below their group's median are an `outlier`: they are far more likely a data problem than a deal, so they are not returned, not scored in the output and not charged. They are counted in `scoredExcludedOutliers` in `RUN_SUMMARY`.

Identical listings for sale (same district, rooms, area and price, for example identical units of one development) are merged into one record, the one with the lowest listing ID. The other IDs are in `identicalListingIds`; the group counts once in the medians, the deal score and the charges (`identicalMerged` in `RUN_SUMMARY`).

Listings that are a share of a flat (`share`) or a court auction (`auction`) are not comparable to ordinary flats. They are left out of the medians and of the results, and counted in `RUN_SUMMARY` (`share_listing`, `auction_listing`). Flags come from keywords in the listing title; the title itself is never stored or returned. Repeated posts of the same rental (same district, rooms, area, price, floor and advertiser type) count once (`near_duplicate_rent` in `RUN_SUMMARY`). Results are sorted by deal score, then by discount against the median.

## How the numbers are computed

- **Groups.** Listings are grouped by city, district and room count (1, 2, 3, 4+). Sale prices and rents fall back to the city level independently: a listing's price is compared with at least 15 comparable flats for sale, and its rent is estimated from at least 10 comparable rentals. Each record says which level it used.
- **Gross yield** = 12 × median monthly rent per m² ÷ median sale price per m². The range uses the quartiles (low rent against high price, and the reverse).
- **Deal score.** A listing's price per m² is compared with the median of its group on a log scale, divided by the group's typical spread (median absolute deviation). 50 means priced at the median; about 84 is one typical deviation cheaper; about 98 is two.
- **Estimated rent** for a listing = median rent per m² of its group × the flat's area.
- **Prices** are asking prices and advertised rents, converted with the ECB daily rate. Monthly building fees (czynsz administracyjny) are not counted as rent.

## Why the numbers can be trusted

- **The admin-fee trap is handled.** On Otodom, `rentPrice` in a sale listing is the building fee, not a rent; it is never used as rent. Listings with swapped rent and fee fields are rejected.
- **Sample sizes are shown.** Every group carries its listing counts and a confidence level; thin groups fall back to the city level instead of producing noisy numbers.
- **Cleaning is explicit.** Ads, duplicates, hidden prices and implausible sizes are removed and counted in `RUN_SUMMARY`. The cheapest 1% and the most expensive 1% of each city's listings by price per m² are dropped before scoring (counted as `outlier` in `RUN_SUMMARY`), so the very cheapest listings are never scored. Separately, listings priced more than 40% below their group's median are left out of the scored listings and are not charged; their number is `scoredExcludedOutliers` in `RUN_SUMMARY`.
- **No personal data.** Names, phone numbers, agency names, photos, descriptions and addresses are dropped when a listing is read; results contain our numbers and a link.
- **Loud failures.** If the portal answers a request with HTTP 403, HTTP 429 or a captcha, the Actor does not retry and does not work around it: the run stops fetching with a clear message (`blockedMessage` in `RUN_SUMMARY`). Cities that were completed before the block are delivered and charged; the city being fetched and the remaining ones are marked `skipped`, with no partial numbers. If nothing was completed, the run fails and none of the Actor's result events are charged (network errors and server errors are retried up to three times). An empty run also fails with a clear message; Apify charges only its standard start fee of $0.00005.

## Monitoring

Set `onlyNewOrChanged: true` and schedule the Actor (for example daily). Each run returns only listings that are new, or at least 1% cheaper, since the last run with the same `watchlistName`, marked `changeType: "new"` or `"priceCut"` with `priceCutPct`. Use one schedule per watchlist name. Running more often than every few minutes rarely returns new listings; a daily schedule is recommended. Unchanged listings are neither returned nor charged.

The monitoring memory is a named key-value store (`cee-rental-yield-state`) in your account. If it cannot be opened or written, the run does not fail: it returns the listings without change detection (`changeType` is `null`) or, when only the final save fails, keeps the results already delivered, and `RUN_SUMMARY.monitoring.warning` says what happened.

For schedules we recommend `mode: "scoreListings"`: yield groups follow `mode` in monitoring runs too, so with `both` every scheduled run also returns (and charges) the full set of yield groups. Run a separate yield report when you need one. A run that finds nothing new still succeeds.

## Pricing

Pay per result:

| Event | Price | When |
|---|---|---|
| Yield group | $0.02 | per `areaYield` record with high or medium confidence |
| Scored listing | $0.004 | per `scoredListing` record |

City-level context records (low confidence) are free.

By default a run returns at most 1,000 scored listings, best deals first (`maxScoredListings`; 0 = all). Example from a test run (November 2026, Apify run `3cFnNnMtkzpmtPDIb`): Warsaw and Kraków with default settings returned 109 yield groups, of which 107 were charged ($2.14; the 2 city-level context groups are free), and 1,000 scored listings ($4.00), **$6.14** in total. Kraków alone costs up to about $5. With `maxScoredListings: 0` the default run scores all of its about 5,600 listings (about $24.50 in total).

To spend less: `mode: "yieldReport"` returns only the yield groups (about $2 for Warsaw and Kraków); `maxScoredListings`, `minScore` and `rooms` reduce the number of scored listings; and you can set a maximum charge per run. When that maximum is close, the run stops cleanly, staying below it, after delivering free city-level context, the yield groups and the best-scored listings first.

**Very low maximum charge.** The Actor collects the whole sample before it returns any result. If your maximum charge per run is too low to justify that (below about $0.03 with default settings), the run uses a smaller sample instead: the first city in your list, the 360 newest listings for sale and for rent, whole-city comparison. The run still succeeds and returns free city-level context plus what your limit covers (for example 2 scored listings at $0.01), never an event type you did not ask for, and `RUN_SUMMARY` shows `budgetReduced: true`. **Recommended minimum for the default run: $0.05.**

## What a report costs

A report (`mode: "yieldReport"`) is charged only for yield groups: $0.02 per `area-yield` event at the Free plan price. No `scored-listing` events are charged in this mode, and city-level context groups (low confidence) are free. Apify adds its own start event of $0.00005 per run.

| City | Yield groups in a recent run | About |
|---|---|---|
| Łódź | 20 | 20 × $0.02 = $0.40 |
| Poznań | 21 | 21 × $0.02 = $0.42 |
| Wrocław | 23 | 23 × $0.02 = $0.46 |
| Gdańsk | 29 | 29 × $0.02 = $0.58 |

These are upper bounds: free groups are not charged. Prices fall on higher Apify plans: for `area-yield`, $0.019 on Bronze, $0.018 on Silver and $0.017 on Gold.

## Limitations

- **Asking prices, not transaction prices.** Gross yield, not net (no taxes, vacancy, maintenance).
- **The sample is current supply.** Listings are sampled newest first, so long-unsold stock is under-represented. Every yield record reports the sample's median age, oldest listing and share of all listings.
- **Developer projects are counted, not scored.** Project tiles have no single price or area, and the few example units shown inside a tile are not representative; both are left out. Project counts appear in `RUN_SUMMARY`.
- **New builds are not always recognised.** Developer listings that the portal does not link to a development are marked `isPrimaryMarket: null` (unknown), not `true`.
- **Primary and secondary market are mixed by default.** With the default setting, price comparisons include both new builds from developers and resales, and `isPrimaryMarket` is `true` when the portal links the flat to a development and `null` (unknown) otherwise. Set `includePrimaryMarket` to `false` to request resales only; every record then has `isPrimaryMarket: false`.
- **Wrong portal locations can slip through.** The portal takes the location from the advertiser. A flat filed under the wrong city is dropped when its listing text or address names another city; if the real city is named nowhere, it can end up in the results.
- **Flags are keyword-based.** Share, auction and renovation flags rely on words in the listing title, so listings that do not say it are not flagged.
- **No information about the flat's condition.** A cheap listing may need renovation.
- **Poland only for now.** More countries are planned.

## FAQ

**Why do the yields differ from the portal's averages?** We use medians per m² within comparable groups, not city-wide means, and only cleaned listings.

**What does `confidence` mean?** `high`: compared within the district with at least 40 sale listings; a city × room count or whole-city comparison is also `high` when at least 80% of the city's listings were fetched and both sides have enough listings (100 sales and 30 rents, or 200 and 50 for the whole city). `medium`: district with fewer listings, or city × room count. `low`: whole-city comparison.

**Why does a listing score 100?** Its price per m² is far below its group's median. Check the listing: very low prices often mean a renovation case, a share of a flat, or a data error.

**How often should I run it?** Daily monitoring catches new listings and price cuts; a full report weekly is enough to follow yields.

## Roadmap

* ~~More Polish cities (Gdańsk, Poznań, Łódź)~~ – done.
* More Polish cities (Katowice, Szczecin, Bydgoszcz, Lublin, Białystok) – next.
* **Portugal – available now:** gross rental yield by freguesia and deal scores for Lisbon and Porto: https://apify.com/data-nest/imovirtual-rental-yield
* Missing a city or a metric? Open an issue on the Issues tab – requests decide what comes next.

## Data sources and responsible use

- Data comes from Otodom search-result pages only, which its robots.txt allows. Listing detail pages are never opened.
- At most one request per second to each website.
- No personal data is collected or stored; each result links to the original listing instead of copying it.
- This Actor is independent and not affiliated with or endorsed by Otodom.
