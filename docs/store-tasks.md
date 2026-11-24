# Store Tasks (inputs for the owner to create in Apify Console)

Paste the full JSON into the Task input (the form would otherwise fill in the prefill). `maxTotalChargeUsd` is a run option, not an input field.

## `rental-yield-lodz` – "Rental yield by district – Łódź"

Recommended `maxTotalChargeUsd`: 2

```json
{"areaMax":250,"areaMin":15,"cities":["lodz"],"includePrimaryMarket":true,"maxListingsPerDistrict":0,"maxListingsPerSide":1500,"maxScoredListings":1000,"minRentSample":10,"minSaleSample":15,"minScore":0,"mode":"yieldReport","onlyNewOrChanged":false,"proxyConfiguration":{"useApifyProxy":true},"rooms":["1","2","3","4+"],"samplingMode":"perDistrict","watchlistName":"default"}
```

## `rental-yield-poznan-gdansk` – "Rental yield by district – Poznań and Gdańsk"

Recommended `maxTotalChargeUsd`: 5

```json
{"areaMax":250,"areaMin":15,"cities":["poznan","gdansk"],"includePrimaryMarket":true,"maxListingsPerDistrict":0,"maxListingsPerSide":3000,"maxScoredListings":1000,"minRentSample":10,"minSaleSample":15,"minScore":0,"mode":"yieldReport","onlyNewOrChanged":false,"proxyConfiguration":{"useApifyProxy":true},"rooms":["1","2","3","4+"],"samplingMode":"perDistrict","watchlistName":"default"}
```
