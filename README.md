# Rental Yield & Deal Score

Where does a rental apartment earn the most, and which listing is priced below its neighbourhood?
One run samples both sides of the local market – apartments for sale and for long-term rent – and returns:

- **Gross rental yield per district and room count**, with medians, quartiles and sample sizes.
- **A 0–100 deal score for every listing for sale**, against the median price per m² of comparable flats.
- **Everything in EUR** (ECB daily rate) next to the local currency, so cities compare directly.

Asking prices and advertised rents, honestly labelled. Gross, not net.

Currently covers Warsaw, Kraków, Wrocław and Katowice (Poland).

## Limitations

- **Asking prices, not transaction prices.** Gross yield, not net.
- **The sample is current supply.** Listings are sampled newest first, so long-unsold stock is under-represented. Every yield record reports the sample's median age, oldest listing and share of all listings.
- **Developer projects are counted, not scored.** Project tiles have no single price or area. The few example units Otodom shows inside a project tile are not representative and are left out; project counts appear in the run summary.
