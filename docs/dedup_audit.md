# Dedup audit — 50 clusters

Historical Chicago pilot audit. These results assess the matching rules on that sample. The separate [Dallas audit](dallas_dedup_audit.md) reviews its four observed merges and targeted split risks.

**Result: 50/50 correct (100%). Merge precision 10/10; split precision 40/40.**

This is an agent review of the structured OSM fields in the warehouse, not a human visual verification of every storefront. The sample is stratified, not random: all 10 multi-record clusters, all 8 same-street/different-house clusters, 15 same-name multi-location clusters, and 17 deterministic random singletons. The full row-level data is in `docs/dedup_audit.csv`.

| # | Stratum | Account | Address | Members | Verdict | Why |
|---:|---|---|---|---:|---|---|
| 1 | A_all_merges | Affresco | (no address) | 2 | correct | Two OSM ways, same name, 7 m apart; no address or phone on either. Same restaurant footprint. |
| 2 | A_all_merges | Hon Kee Restaurant | (no address) | 2 | correct | Two nodes, same name, 34 m apart; one carries the phone. Same storefront block. |
| 3 | A_all_merges | Mizu | 9664 West 131st Street, Palos Park, 60464 | 2 | correct | One way with address and one node without; 17 m apart, same name. Same location. |
| 4 | A_all_merges | The Butcher & the Burger | 1021 West Armitage Avenue, Chicago, 60614 | 2 | correct | Name variant ("The" elided), same address, same phone; merged via street_name. |
| 5 | A_all_merges | Chim Thai Cuisine | 3254 West Montrose Avenue | 2 | correct | Same house number and street; one record lacks city/postcode. Same address. |
| 6 | A_all_merges | The Corner Farmacy | 324 North Leavitt Street, Chicago, 60612 | 2 | correct | Same name, same house number, two corner street names (Bell/Leavitt), 23 m apart, same phone. Canonical key is the Bell key; survivor is the Leavitt record. |
| 7 | A_all_merges | Little Bucharest Bistro | 3661 North Elston Avenue, Chicago, 60618 | 2 | correct | House number range 3661-3663 vs 3661; same street and coordinates. |
| 8 | A_all_merges | Mama Luigi's Restaurant | 7500 Harlem Avenue, Bridgeview, 60455 | 2 | correct | One record lacks the house number; same street, city, postcode, and coordinates. |
| 9 | A_all_merges | Mariachi's Tacos | East Touhy Avenue, Des Plaines, 60018 | 2 | correct | One record lacks the house number; same street, city, postcode, same phone. |
| 10 | A_all_merges | Wok cuisine | 4552 North Kedzie Avenue | 2 | correct | Same house number and street; one record lacks city/postcode and has a different URL scheme. |
| 11 | B_multi_name | Lao Sze Chuan | 616 South Wabash Avenue, Chicago, 60605 | 1 | correct | Same name, distinct location; nearest other location is 1950 m away. |
| 12 | B_multi_name | Kimchi Pop | 4429 North Broadway, Chicago, 60640 | 1 | correct | Same name, distinct location; nearest other location is 5078 m away. |
| 13 | B_multi_name | Poke Poké | 1100 West Madison Street, Chicago, 60607 | 1 | correct | Same name, distinct location; nearest other location is 2338 m away. |
| 14 | B_multi_name | Casa Margarita | 25 East Hinsdale Avenue, Hinsdale, 60521 | 1 | correct | Same name, distinct location; nearest other location is 4999 m away. |
| 15 | B_multi_name | Poke Poké | 118 South Wabash Avenue, Chicago, 60603 | 1 | correct | Same name, distinct location; nearest other location is 1498 m away. |
| 16 | B_multi_name | Strings Ramen | 2141 South Archer Avenue, Chicago, 60616 | 1 | correct | Same name, distinct location; nearest other location is 6990 m away. |
| 17 | B_multi_name | Hashbrowns | 1155 North Wells Street, Chicago, 60610 | 1 | correct | Same name, distinct location; nearest other location is 4452 m away. |
| 18 | B_multi_name | Pepe's Mexican Restaurant | 131 East 79th Street, Chicago, 60619 | 1 | correct | Same name, distinct location; nearest other location is 1518 m away. |
| 19 | B_multi_name | Golden Nugget | 3001 North Central Avenue, Chicago, 60634 | 1 | correct | Same name, distinct location; nearest other location is 6440 m away. |
| 20 | B_multi_name | Protein Bar & Kitchen | 10 West Lake Street, Chicago, 60601 | 1 | correct | Same name, distinct location; nearest other location is 616 m away. |
| 21 | B_multi_name | So Gong Dong | 2411 West North Avenue | 1 | correct | Same name, distinct location; nearest other location is 15611 m away. |
| 22 | B_multi_name | Paisans Pizzeria | 4900 West 111th Street, Oak Lawn, 60453 | 1 | correct | Same name, distinct location; nearest other location is 9320 m away. |
| 23 | B_multi_name | Protein Bar | (no address) | 1 | correct | Same name, distinct location; nearest other location is 1126 m away. |
| 24 | B_multi_name | Connie's Pizza | (no address) | 1 | correct | Same name, distinct location; nearest other location is 10789 m away. |
| 25 | B_multi_name | Flaco's Tacos | 725 South Dearborn Street, Chicago, 60605 | 1 | correct | Same name, distinct location; nearest other location is 2692 m away. |
| 26 | C_same_street | Allende | 2221 North Lincoln Avenue, Chicago, 60614 | 1 | correct | Same street name, different house number; nearest other location is 545 m away. |
| 27 | C_same_street | Allende | 2408 North Lincoln Avenue, Chicago, 60614 | 1 | correct | Same street name, different house number; nearest other location is 545 m away. |
| 28 | C_same_street | Baba Saj | 10832 South Cicero Avenue, Oak Lawn, 60453 | 1 | correct | Same street name, different house number; nearest other location is 390 m away. |
| 29 | C_same_street | Baba Saj | 11026 South Cicero Avenue, Oak Lawn, 60453 | 1 | correct | Same street name, different house number; nearest other location is 390 m away. |
| 30 | C_same_street | Barraco's Pizza | 2105 West 95th Street, Chicago, 60643 | 1 | correct | Same street name, different house number; nearest other location is 3249 m away. |
| 31 | C_same_street | Barraco's Pizza | 3701 West 95th Street, Evergreen Park, 60805 | 1 | correct | Same street name, different house number; nearest other location is 3249 m away. |
| 32 | C_same_street | Taco Burrito King | 4427 North Harlem Avenue, Norridge, 60706 | 1 | correct | Same street name, different house number; nearest other location is 2185 m away. |
| 33 | C_same_street | Taco Burrito King | 5509 North Harlem Avenue, Chicago, 60656 | 1 | correct | Same street name, different house number; nearest other location is 2185 m away. |
| 34 | D_random | Cup & Spoon | 2415 West North Avenue, Chicago, 60647 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 35 | D_random | Golden House Restaurant | 4744 North Racine Avenue, Chicago, 60640 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 36 | D_random | PERILLA fare | 401 North Milwaukee Avenue, Chicago, 60654 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 37 | D_random | Santiago's | 4803 North Pulaski Road, Chicago, 60630 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 38 | D_random | Nancy's Pizzeria | 1000 West Washington Boulevard, Chicago, 60607 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 39 | D_random | Piece Brewery & Pizzeria | 1927 West North Avenue, Chicago, 60622 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 40 | D_random | Jin Thai Cuisine | (no address) | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 41 | D_random | Kirkwood Bar & Grill | 2934 North Sheffield Avenue, Chicago, 60657 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 42 | D_random | Denden Restaurant | 6635 North Clark Street, Chicago, 60626 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 43 | D_random | A Taste of the Philippines | 5914 West Lawrence Avenue, Chicago, 60630 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 44 | D_random | Cumin | 1414 North Milwaukee Avenue, Chicago, 60622 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 45 | D_random | Artango Bar & Steakhouse | (no address) | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 46 | D_random | Curry On Fire | 1030 West Taylor Street, Chicago, 60607 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 47 | D_random | Girl & The Goat | 809 West Randolph Street, Chicago, 60607 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 48 | D_random | Surf's Up | (no address) | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 49 | D_random | The Gundis | 2909 North Clark Street, Chicago, 60657 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |
| 50 | D_random | Weber Grill | 539 North State Street, Chicago, 60654 | 1 | correct | No other account with this normalized name; address and coordinates coherent. |

**Key note.** For The Corner Farmacy, `dedup_key` is the canonical `geo_50m` cluster id (`n bell ave`), not the survivor's address key (`n leavitt st`). The second pass assigns both members the lexicographically least address key; the survivor is chosen independently by richness. `int_account_deduped.address_key` exposes the survivor's own key, so the key and the row reconcile without pretending the survivor sits on Bell.

## What this does and does not prove

- All 10 merges are correct in the sample; there are no observed over-merges. That is the failure mode the dedup key is designed to avoid.

- The split checks cover 40 clusters, including every same-street/different-house group. They are distinct locations, not false splits.

- Residual risk: same-name locations that are more than 50 m apart and have no shared address will remain separate. That is intentional; merging them needs a stronger signal than name alone.

- The 50/50 result has a Wilson 95% lower bound of about 93%, so “100%” should be read as “no errors in 50,” not “provably perfect.”
