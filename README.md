# Rental Yield & Deal Score

Where does a rental apartment earn the most, and which listing is priced below its neighbourhood?
One run samples both sides of the local market – apartments for sale and for long-term rent – and returns:

- **Gross rental yield per district and room count**, with medians, quartiles and sample sizes.
- **A 0–100 deal score for every listing for sale**, against the median price per m² of comparable flats.
- **Everything in EUR** (ECB daily rate) next to the local currency, so cities compare directly.

Asking prices and advertised rents, honestly labelled. Gross, not net.

Currently covers Warsaw, Kraków and Wrocław (Poland). Katowice is also available.

## What you get

- **Yield by district** (`areaYield` records): for every district × room group, the median sale price per m², the median monthly rent per m², quartiles, the number of listings behind each number, and the gross yield with a range. Groups with too few listings fall back to the city level and say so (`groupLevel`, `confidence`).
- **Scored listings** (`scoredListing` records): for every apartment for sale, a 0–100 deal score, its discount against comparable flats, an estimated monthly rent and gross yield, and a link to the listing. Sorted best deal first.
- **Sample transparency**: every yield record reports how recent its sample is (median age, oldest listing) and what share of all listings it covers.
- **Two reports in the key-value store**: `YIELD_REPORT` (all groups, all levels) and `RUN_SUMMARY` (what was fetched, rejected and charged, per city and market side).

## Quick start

Run with no settings to analyse Warsaw and Kraków:

```json
{
  "cities": ["warszawa", "krakow"],
  "mode": "both"
}
```

Two-room flats in Wrocław and Kraków, best deals only:

```json
{
  "cities": ["wroclaw", "krakow"],
  "rooms": ["2"],
  "minScore": 70
}
```

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
  "source": "otodom", "url": "https://www.otodom.pl/pl/oferta/...",
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
- `outlier` – priced more than 40% below its group's median. Often a data quirk or a special case; check the listing before trusting the score.

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
- **Cleaning is explicit.** Ads, duplicates, hidden prices, implausible sizes and price outliers are removed and counted in `RUN_SUMMARY`.
- **No personal data.** Names, phone numbers, agency names, photos, descriptions and addresses are dropped when a listing is read; results contain our numbers and a link.
- **Loud failures.** A blocked or empty run fails with a clear message. None of the Actor's result events are charged; Apify charges only its standard start fee of $0.00005.

## Monitoring

Set `onlyNewOrChanged: true` and schedule the Actor (for example daily). Each run returns only listings that are new, or at least 1% cheaper, since the last run with the same `stateKey`, marked `changeType: "new"` or `"priceCut"` with `priceCutPct`. Use one schedule per state key. Unchanged listings are neither returned nor charged.

For schedules we recommend `mode: "scoreListings"`: yield groups follow `mode` in monitoring runs too, so with `both` every scheduled run also returns (and charges) the full set of yield groups. Run a separate yield report when you need one. A run that finds nothing new still succeeds.

## Pricing

Pay per result:

| Event | Price | When |
|---|---|---|
| Yield group | $0.02 | per `areaYield` record with high or medium confidence |
| Scored listing | $0.004 | per `scoredListing` record |

City-level context records (low confidence) are free.

By default a run returns at most 1,000 scored listings, best deals first (`maxScoredListings`; 0 = all). Example from a test run (November 2026): Warsaw and Kraków with default settings return about 109 yield groups ($2.18) and 1,000 scored listings ($4.00), about **$6.18** in total. Kraków alone: about 49 yield groups ($0.98) and 1,000 scored listings ($4.00), about $4.98. With `maxScoredListings: 0` the default run scores all of its about 6,150 listings (about $26.80 in total).

To spend less: `mode: "yieldReport"` returns only the yield groups (about $2 for Warsaw and Kraków); `maxScoredListings`, `minScore` and `rooms` reduce the number of scored listings; and you can set a maximum charge per run. When that maximum is close, the run stops cleanly, staying below it, after delivering free city-level context, the yield groups and the best-scored listings first.

**Very low maximum charge.** The Actor collects the whole sample before it returns any result. If your maximum charge per run is too low to justify that (below about $0.03 with default settings), the run uses a smaller sample instead: the first city in your list, the 360 newest listings for sale and for rent, whole-city comparison. The run still succeeds and returns free city-level context plus what your limit covers (for example 2 scored listings at $0.01), never an event type you did not ask for, and `RUN_SUMMARY` shows `budgetReduced: true`. **Recommended minimum for the default run: $0.05** (with the residential proxy: $2).

## Limitations

- **Asking prices, not transaction prices.** Gross yield, not net (no taxes, vacancy, maintenance).
- **The sample is current supply.** Listings are sampled newest first, so long-unsold stock is under-represented. Every yield record reports the sample's median age, oldest listing and share of all listings.
- **Developer projects are counted, not scored.** Project tiles have no single price or area, and the few example units shown inside a tile are not representative; both are left out. Project counts appear in `RUN_SUMMARY`.
- **Primary and secondary market are mixed by default.** With the default setting, price comparisons include both new builds from developers and resales, and `isPrimaryMarket` is `true` when the portal links the flat to a development and `null` (unknown) otherwise. Set `includePrimaryMarket` to `false` to request resales only; every record then has `isPrimaryMarket: false`.
- **Wrong portal locations can slip through.** The portal takes the location from the advertiser. A flat filed under the wrong city is dropped when its listing text or address names another city; if the real city is named nowhere, it can end up in the results.
- **Flags are keyword-based.** Share, auction and renovation flags rely on words in the listing title, so listings that do not say it are not flagged.
- **No information about the flat's condition.** A cheap listing may need renovation.
- **Katowice has a small rental market** (about 770 rentals city-wide), so many of its groups fall back to the city level.
- **Poland only for now.** More countries are planned.

## FAQ

**Why do the yields differ from the portal's averages?** We use medians per m² within comparable groups, not city-wide means, and only cleaned listings.

**What does `confidence` mean?** `high`: compared within the district with at least 40 sale listings. `medium`: district with fewer listings, or city × room count. `low`: whole-city comparison.

**Why does a listing score 100?** Its price per m² is far below its group's median. Check the listing: very low prices often mean a renovation case, a share of a flat, or a data error.

**How often should I run it?** Daily monitoring catches new listings and price cuts; a full report weekly is enough to follow yields.

## Data sources and responsible use

- Data comes from Otodom search-result pages only, which its robots.txt allows. Listing detail pages are never opened.
- At most one request per second to each website.
- No personal data is collected or stored; each result links to the original listing instead of copying it.
