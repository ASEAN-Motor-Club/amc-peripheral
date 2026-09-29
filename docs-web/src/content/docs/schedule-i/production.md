---
title: "Schedule I — Production"
description: Sources, transforms and catalysts of the Schedule I supply chain.
sidebar:
  label: Production
  order: 3
---

Values as of **Schedule I 0.7.5** (game 0.7.19).

## Sources

Sites that passively generate cargo over time — no input needed. The cargo appears in the site's storage (see the [storage caps](/schedule-i/delivery-points/)) and is delivered like any other cargo:

| Site | Produces | Rate |
|---|---|---:|
| Factory_Bottle | HydrochloricAcid | every 180 s |
| CrudeOil_Supplier | Kerosene | every 120 s |
| Farm_Hemp | HempPallet | every 300 s |
| Mine_LimestoneRockQuarry | Phosphorus | every 120 s |

## Transforms

Conversion recipes. A transform only runs while the site accepts the input cargo — check the [demand table](/schedule-i/delivery-points/) before hauling. Recipes marked *(hidden)* exist in the site's production list but are not advertised to players.

| Site | Input | Output | Time |
|---|---|---|---:|
| CrudeOil_Supplier | — | Kerosene ×1 | 30 s |
| Mine_CopperOre | CornPallet ×1 | Moonshine ×5 | 180 s |
| Farm_Sunflower | — | CocaineBase ×2 | 600 s |
| Farm_Sunflower | — | LiquidCocaine ×2 | 600 s |
| Factory_Toy | CocaineBricks ×1 | Money ×3 | 120 s |
| Factory_Toy | CocaineBricks ×1 | CocainePackets ×3 | 180 s |
| CourierService | CocainePackets ×1 | CocaineBags ×1 | 120 s |
| Refinery_Oil | CrudeOil ×1 | Acetone ×1, AnhydrousAmmonia ×1 | 180 s |
| Factory_Quicklime | — | CocaineBricks ×3 | 600 s |
| Factory_Quicklime | — | MethBase ×2 | 900 s |
| Farm_Hemp | — | CocaPaste ×2 | 600 s |
| Export_Harbor | — | Money ×3 | 300 s |
| Factory_Limestone_Drop | Moonshine ×1 | Moonshine ×1 | 1 s |
| Factory_Limestone_Drop | Moonshine ×1 | Money ×1 | 120 s |
| Supermarket | Moonshine ×1 | MoonshineBottles ×5 | 300 s |
| Supermarket | Money ×1 | Pseudoephedrine ×1 | 60 s |
| Factory_Furniture | MethBase ×1 | HiddenMethBed ×2 | 300 s |
| Factory_Furniture | MethBase ×1 | HiddenMethSofa ×2 | 300 s |
| Factory_Furniture | MethBase ×1 | HiddenMethArmchair ×2 | 300 s |
| Store_Furniture | HiddenMethBed ×1 | CrystalMeth ×2, Money ×2 | 120 s |
| Store_Furniture | HiddenMethSofa ×1 | CrystalMeth ×2, Money ×2 | 120 s |
| Store_Furniture | HiddenMethArmchair ×1 | CrystalMeth ×2, Money ×2 | 120 s |

## Catalysts

Money spent at a production site to **double its production speed** while the catalyst budget lasts. Catalysts are consumed — they buy speed, they do not pay for anything:

| Site | Catalyst | Time per catalyst |
|---|---|---:|
| Farm_Sunflower | Money ×1 | 600 s |
| Factory_Toy | Money ×1 | 600 s |
| Factory_Quicklime | Money ×1 | 600 s |
| Farm_Hemp | Money ×1 | 600 s |

Values as of **Schedule I 0.7.5** (game 0.7.19).
