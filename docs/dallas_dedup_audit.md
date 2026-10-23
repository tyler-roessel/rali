# Dallas account dedup audit — 2026-10-23

This is a targeted review of the Dallas OpenStreetMap extract saved on 2026-10-21. It is an agent review of map fields and selected public business websites, not an in-person check of storefronts or a measured recall study. The account model still needs human identity review before outreach.

## Scope and result

- The saved payload returned 1,785 elements. After excluding 302 brand-tagged records, 1,483 records loaded. The corrected dedup model returns **1,479 account rows and four two-record merges**.
- All four observed merges were reviewed below. Their name/address evidence supports a single location in each case; Bowl Mami has a substantial coordinate conflict that remains visible as a data-quality concern.
- Targeted split screens found **one likely missed duplicate**: the pickup node for Mythri's Indian Cuisine. The model leaves it separate because the names differ and the pickup node has no address. This means the 1,479 model rows should not be presented as a verified count of distinct operating restaurants.
- The proximity check now scales longitude using each pair's mean latitude instead of a Chicago constant. No Dallas pair crossed the 50 m decision boundary when this was corrected; the four observed merges and the 1,479-row model count stayed the same. None of the four merges used the proximity rule.

## Every merged group

| Account | OSM node IDs | Separation | Evidence and decision |
|---|---|---:|---|
| Bowl Mami | 13513631801, 9494065054 | 422.4 m | Both map records have the same name and 2701 Old Denton Road; the richer one has the [business website](https://www.bowlmami.com/), which lists that address. **Supported merge, coordinate conflict.** One node appears misplaced; the address match, not distance, caused the merge. |
| Gilgamesh Restaurant & Bakery | 13991020902, 13991023101 | 0 m | Same name, suite 301 address, and point; one record carries the website and phone. The [business website](https://gilgameshdallas.com/) confirms suite 301. **Supported merge.** |
| Koryo Korean BBQ | 13302226901, 13302228101 | 0 m | Same name, address, point, phone, and website. The [business website](https://www.eatkoryo.com/) confirms 2560 Royal Lane, suite 105. **Supported merge.** |
| Sunny Street Cafe | 14140655101, 8392026875 | 1.8 m | Same name, address, and phone; one URL is the Carrollton location page and the other is the home page. The [location page](https://www.sunnystreetcafe.com/store_locations/carrollton-restaurant/) confirms 2150 N Josey Lane. **Supported merge.** |

All four merged keys used `street_name`. A supported merge means the available evidence points to one restaurant location; it does not prove that every OSM field is accurate or that the business is currently an eligible prospect.

## Split-risk screens

The screens used the full 1,483-record saved extract after rebuilding the corrected model in an isolated local Postgres database. They were selected to find likely errors, not sampled randomly. Screen counts may overlap.

| Screen | Candidate rows | What the review found |
|---|---:|---|
| Same normalized name, separate accounts, within 1 km | 0 | No near exact-name split in this extract. |
| Same normalized name, separate accounts, within 5 km | 12 | Most have different street addresses or location-specific URLs, including two [Gloria's](https://www.gloriascuisine.com/locations/dallas-uptown) [locations](https://www.gloriascuisine.com/locations/dallas-lemmon-ave). The unaddressed Shell Shack and Taqueria Taxco records remain possible stale or separate locations; distance alone cannot settle them. |
| Similar names (trigram similarity at least 0.60), separate accounts, within 500 m | 3 | Mythri's pickup is a likely false split; Revolver's TO GO and Elm Street restaurant are separate storefronts; Main Street Deli and Main Street Cafe have different addresses and business sites. |
| Same normalized phone, separate accounts | 4 | Two pairs are same-brand locations more than 11 km apart; Carbone and Sadelle's have different names and addresses. Shawarma World and Tacomex Las Colinas share an OSM phone and address, but [Shawarma World's site](https://shawarmaworld.site/) currently lists a different phone. Keep this pair in review rather than merge it by phone. |
| Ten closest separate-name pairs with the same normalized address | 10 | These are named as distinct restaurants or concepts in the map data. Shared shopping-center or building addresses do not establish one operating account. No automatic merge is supported by this screen alone. |
| Same website host, separate accounts, within 500 m | 2 | The [Revolver site](https://revolvertacolounge.com/revolver-taco-lounge/) identifies its TO GO window at 2701 Main Street and its [restaurant](https://revolvertacolounge.com/gastro-cantina-deep-ellum/) at 2646 Elm Street. Biergarten and Coal Vines share an Omni domain but have different names; shared hosting does not establish one restaurant. |

**Likely missed duplicate:** `Mythri's Indian Cuisine Pickup` (OSM node 9357025484) is 15.3 m from `Mythri's Indian Cuisine` (node 9357025483). The pickup record has no address, phone, or website. The [business site](https://www.mythrisusa.com/) lists one Irving restaurant at 8350 N MacArthur Boulevard with online ordering; the nearby pickup node is best treated as a service point for that location. The model does not merge different names automatically, so this pair requires explicit resolution. We did not change the general matching rule for one ambiguous suffix, and the committed lifecycle and mock CRM data still use the 1,479-account model.

**Correct nearby split:** Revolver Taco Lounge's two map records are 56.6 m apart but correspond to different addresses and service formats on the business's own site. They should remain distinct location records even though they share a brand and website host.

## Verification and limits

- The full Dallas dedup view was rebuilt from the saved public extract after the latitude fix: **1,483 raw rows, 1,479 account rows, four merged groups, zero `geo_50m` members**. A pre/post comparison found zero pairwise decisions changed at the 50 m threshold.
- The committed 200-account fixture contains all four merged groups (204 raw rows). Its full isolated Postgres `dbt build` passed **197/197** nodes after the fix, including 173 data tests. Those tests check model mechanics and relationships; they do not prove real-world identity correctness.
- The full saved Overpass payload is local and not committed. A public reviewer can reproduce the four-merge inspection from the fixture but cannot reproduce every full-market split screen from the clone alone without obtaining the extract. The audit records the screening criteria and selected evidence so the claim stays bounded.
- The targeted screen found a likely false split, so no recall percentage is claimed. This audit does not validate OSM market coverage, buyer identity, live CRM status, or the fit score.
