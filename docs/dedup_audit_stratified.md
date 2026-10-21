# Dedup audit — stratified 50 clusters

**Result: 50/50 correct (100%).** Full-population stratum includes all 10 multi-record merges plus 10 random singletons; null-website and null-postcode strata are 15 each. Merge precision 10/10; split precision 40/40.

This is an agent review of structured OSM fields, not a human storefront check. The sample is stratified by the fields the reviewer named. Row-level data: `docs/dedup_audit_stratified.csv`.

## Reviewer spot-check (2026-10-21)

All 10 merges are clearly the same restaurant with minor variations, and the 5 singletons are distinct businesses. No discrepancies found.

| # | Stratum | Account | Address | Members | Verdict | Note |
|---:|---|---|---|---:|---|---|
| 1 | full_population | Mama Luigi's Restaurant | 7500 Harlem Avenue, Bridgeview, 60455 | 2 | correct | One missing house number; same street/city/postcode/coords. |
| 2 | full_population | Mariachi's Tacos | East Touhy Avenue, Des Plaines, 60018 | 2 | correct | One missing house number; same street/city/postcode/phone. |
| 3 | full_population | Little Bucharest Bistro | 3661 North Elston Avenue, Chicago, 60618 | 2 | correct | House range 3661-3663 vs 3661; same coordinates. |
| 4 | full_population | Wok cuisine | 4552 North Kedzie Avenue | 2 | correct | Same address; one missing postcode. |
| 5 | full_population | The Butcher & the Burger | 1021 West Armitage Avenue, Chicago, 60614 | 2 | correct | Name variant, same address/phone. |
| 6 | full_population | Chim Thai Cuisine | 3254 West Montrose Avenue | 2 | correct | Same address; one missing city/postcode. |
| 7 | full_population | The Corner Farmacy | 324 North Leavitt Street, Chicago, 60612 | 2 | correct | Same name/house, Bell/Leavitt corner, 23 m, same phone; canonical key is Bell. |
| 8 | full_population | Mizu | 9664 West 131st Street, Palos Park, 60464 | 2 | correct | Address + no-address, 17 m apart; same location. |
| 9 | full_population | Hon Kee Restaurant | (none) | 2 | correct | Two nodes, 34 m apart; one has phone; same block. |
| 10 | full_population | Affresco | (none) | 2 | correct | Two ways, same name, 7 m apart; same footprint. |
| 11 | full_population | Cup & Spoon | 2415 West North Avenue, Chicago, 60647 | 1 | correct | no same-name twin; split is correct. |
| 12 | full_population | Lao Sze Chuan | 616 South Wabash Avenue, Chicago, 60605 | 1 | correct | null website; nearest same-name location 1950 m away; split is correct. |
| 13 | full_population | Golden House Restaurant | 4744 North Racine Avenue, Chicago, 60640 | 1 | correct | no same-name twin; split is correct. |
| 14 | full_population | PERILLA fare | 401 North Milwaukee Avenue, Chicago, 60654 | 1 | correct | no same-name twin; split is correct. |
| 15 | full_population | Santiago's | 4803 North Pulaski Road, Chicago, 60630 | 1 | correct | null website; no same-name twin; split is correct. |
| 16 | full_population | Nancy's Pizzeria | 1000 West Washington Boulevard, Chicago, 60607 | 1 | correct | no same-name twin; split is correct. |
| 17 | full_population | Piece Brewery & Pizzeria | 1927 West North Avenue, Chicago, 60622 | 1 | correct | no same-name twin; split is correct. |
| 18 | full_population | Jin Thai Cuisine | (none) | 1 | correct | no address; no same-name twin; split is correct. |
| 19 | full_population | Kirkwood Bar & Grill | 2934 North Sheffield Avenue, Chicago, 60657 | 1 | correct | no same-name twin; split is correct. |
| 20 | full_population | Denden Restaurant | 6635 North Clark Street, Chicago, 60626 | 1 | correct | null website; no same-name twin; split is correct. |
| 21 | null_website | Artango Bar & Steakhouse | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 22 | null_website | Surf's Up | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 23 | null_website | 65 Express | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 24 | null_website | Izakaya Shinya | 2255 West North Avenue, Chicago, 60647 | 1 | correct | null website; no same-name twin; split is correct. |
| 25 | null_website | El Rayo Tacos | 2055 West 79th Street, Chicago | 1 | correct | null website; no same-name twin; split is correct. |
| 26 | null_website | Upper's Land | 25 West Calendar Avenue | 1 | correct | null website; no same-name twin; split is correct. |
| 27 | null_website | The Slab Bar-B-Que | 1918 East 71st Street, Chicago, 60649 | 1 | correct | null website; no same-name twin; split is correct. |
| 28 | null_website | American Wild Burger | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 29 | null_website | El Publano | 2610 West 51st Street, Chicago, 60632 | 1 | correct | null website; no same-name twin; split is correct. |
| 30 | null_website | Casa Margarita | 25 East Hinsdale Avenue, Hinsdale, 60521 | 1 | correct | null website; nearest same-name location 4999 m away; split is correct. |
| 31 | null_website | Hecho en Oak Park | 1053 Lake Street, Oak Park, 60301 | 1 | correct | null website; no same-name twin; split is correct. |
| 32 | null_website | Phở Việt | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 33 | null_website | La Choza Mexican Grill | 7022 North Clark Street, Chicago, 60626 | 1 | correct | null website; no same-name twin; split is correct. |
| 34 | null_website | Palace Regency | West Cermak Road, Cicero, 60804 | 1 | correct | null website; no same-name twin; split is correct. |
| 35 | null_website | Vinci | 1732 North Halsted Street | 1 | correct | null website; no same-name twin; split is correct. |
| 36 | null_postcode | Udupi Palace | 2543 West Devon Avenue | 1 | correct | no same-name twin; split is correct. |
| 37 | null_postcode | Feed Your Head | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 38 | null_postcode | Olive Tree | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 39 | null_postcode | Yaya Mas Greek Kuzina | 1755 North Sheffield Avenue, Chicago | 1 | correct | no same-name twin; split is correct. |
| 40 | null_postcode | Wen Gai | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 41 | null_postcode | Caffe Mercato | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 42 | null_postcode | MiMi's Craft Kitchen | 1352 West Taylor Street, Chicago | 1 | correct | null website; no same-name twin; split is correct. |
| 43 | null_postcode | Tacos De Canasta | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 44 | null_postcode | Sizzling Skillets | 8635 South Cottage Grove Avenue, Chicago | 1 | correct | null website; no same-name twin; split is correct. |
| 45 | null_postcode | Iyanzé | 4625 North Broadway | 1 | correct | no same-name twin; split is correct. |
| 46 | null_postcode | Pita Pita | 200 West Randolph Street | 1 | correct | null website; no same-name twin; split is correct. |
| 47 | null_postcode | Authentic Cheesesteaks | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 48 | null_postcode | Buffet City | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 49 | null_postcode | Kapitan | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |
| 50 | null_postcode | Villa Rosa Pizza Kitchen | (none) | 1 | correct | null website; no address; no same-name twin; split is correct. |

## Failure modes

- **Over-merge:** none observed. All 10 multi-record clusters were included and are correct; no cluster has 3+ records.

- **False split:** none observed in the 50. The null-website and null-postcode samples produced no close same-name twin; the nearest unmerged same-name locations were 1.9–5.1 km away.

- **Residual risk (not in sample):** under-merge for old/new addresses or name variants. Named examples: Luella’s Southern Kitchen (4114 N Kedzie vs 4609 N Lincoln, same phone/website), Bongiorno’s Cucina vs Deli (same address/phone, different service names), and no-address same-name records 270–400 m from an addressed twin (Friends Sushi, Wow Bao, Silk Road). These are kept separate because the rule cannot tell a move/two concepts from two locations.

- The audit is powered for over-merge (it includes every merge) but not for recall; 0.4% is not proof that no duplicate was missed.
