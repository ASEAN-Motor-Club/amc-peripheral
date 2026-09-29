---
title: "Schedule I — Delivery Points"
description: Storage caps and demand (pay multipliers) at every Schedule I delivery point.
sidebar:
  label: Delivery Points
  order: 4
---

Values as of **Schedule I 0.7.5** (game 0.7.19).

## Demand — what sites buy, and at what pay

Demand is **per cargo**: each entry carries its own pay multiplier and storage cap, so a site buying moonshine never reprices the fuel it also sells. The multiplier applies on top of the cargo's per-km rate from the [cargo table](/schedule-i/cargo/).

| Site | Buys | Pays | Storage cap |
|---|---|---:|---:|
| Mine_CopperOre | CornPallet | 1× | 20 |
| Supermarket | Moonshine | 1.5× | 5 |
| GasStation | Moonshine | 1.2× | 5 |
| Export_Harbor | LiquidCocaine | 2× | 10 |
| Farm_Hemp | Money | 1× | 10 |
| Farm_Sunflower | Money | 1× | 25 |
| Resident | CocaineBags | 2× | 2 |
| Resident | MoonshineBottles | 1.2× | 3 |
| Resident | CrystalMeth | 2× | 2 |
| Factory_Toy | Money | 1× | 25 |
| Factory_Quicklime | CocaineBase | 1× | 30 |

## Storage — what sites hold

Maximum stock per cargo at each site. When a site's storage is full, its production (and your delivery) waits until it drains — low caps force players to spread deliveries across multiple sites.

| Site | Cargo | Max storage |
|---|---|---:|
| CrudeOil_Supplier | Kerosene | 50 |
| CrudeOil_Supplier | Money | 50 |
| Mine_CopperOre | CornPallet | 40 |
| Mine_CopperOre | Moonshine | 100 |
| Farm_Hemp | Kerosene | 50 |
| Farm_Hemp | QuicklimePallet | 30 |
| Farm_Hemp | CocaPaste | 40 |
| Farm_Hemp | Money | 10 |
| Farm_Sunflower | CocaPaste | 40 |
| Farm_Sunflower | Acetone | 100 |
| Farm_Sunflower | HydrochloricAcid | 50 |
| Farm_Sunflower | CocaineBase | 30 |
| Farm_Sunflower | CocaineBricks | 30 |
| Farm_Sunflower | Money | 25 |
| Farm_Sunflower | LiquidCocaine | 40 |
| Factory_Toy | CocaineBricks | 30 |
| Factory_Toy | CocainePackets | 50 |
| Factory_Toy | Money | 50 |
| CourierService | CocainePackets | 10 |
| CourierService | CocaineBags | 20 |
| Refinery_Oil | CrudeOil | 50 |
| Refinery_Oil | Acetone | 100 |
| Refinery_Oil | AnhydrousAmmonia | 50 |
| Factory_Bottle | HydrochloricAcid | 20 |
| Supermarket | MoonshineBottles | 30 |
| Supermarket | Money | 10 |
| Supermarket | Pseudoephedrine | 10 |
| Factory_Quicklime | CocaineBase | 30 |
| Factory_Quicklime | CocaineBricks | 50 |
| Factory_Quicklime | CocainePackets | 50 |
| Factory_Quicklime | Money | 40 |
| Factory_Quicklime | Pseudoephedrine | 50 |
| Factory_Quicklime | Phosphorus | 50 |
| Factory_Quicklime | AnhydrousAmmonia | 50 |
| Factory_Quicklime | MethBase | 50 |
| Factory_Limestone_Drop | Moonshine | 50 |
| Factory_Limestone_Drop | Money | 50 |
| Factory_Furniture | MethBase | 50 |
| Factory_Furniture | HiddenMethBed | 50 |
| Factory_Furniture | HiddenMethSofa | 50 |
| Factory_Furniture | HiddenMethArmchair | 50 |
| Store_Furniture | HiddenMethBed | 50 |
| Store_Furniture | HiddenMethSofa | 50 |
| Store_Furniture | HiddenMethArmchair | 50 |
| Store_Furniture | CrystalMeth | 50 |
| Store_Furniture | Money | 50 |

Values as of **Schedule I 0.7.5** (game 0.7.19).
