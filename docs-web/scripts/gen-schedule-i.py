#!/usr/bin/env python3
"""Generate the Schedule I reference pages from data/schedule-i.json.

Source of truth: mt-pak-extract/mods/schedule-i/{cargo_entries,recipe_entries}.json
for the version named in the data file. After a Schedule I mod release:

    1. Copy the slimmed configs into data/schedule-i.json (update "version").
    2. python3 scripts/gen-schedule-i.py
    3. Commit the regenerated pages together with the data file.

The generated .md files are committed to the repo (the Nix build does not run
this script), so docs always match the version stamped in data/schedule-i.json.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "data" / "schedule-i.json").read_text())
DOCS = ROOT / "src" / "content" / "docs" / "schedule-i"

V = DATA["version"]
STAMP = f"Values as of **Schedule I {V}** (game 0.7.19)."


def display(e):
    return " ".join(e["display_name"])


def recipe_out(rec):
    if rec.get("output_cargos"):
        return ", ".join(f"{k} \u00d7{v}" for k, v in rec["output_cargos"].items())
    return f"{rec['output_cargo']} \u00d7{rec['output_count']}"


def gen_cargo():
    notes = {
        "Money": "Illicit. Score-carrying; pays a risk premium with police on duty.",
        "MoneyPallet": "Illicit. Pallet-sized cash delivery.",
        "Moonshine": "Illicit (keg). Product of the copper-mine still; feeds bottling and gas-station demand.",
        "MoonshineBottles": "Illicit. Bottled at supermarkets, sold to residents.",
        "CocaPaste": "Illicit (dump cargo). Milled at the hemp farm.",
        "CocaineBase": "Illicit (dump cargo). Cut into bricks at the quicklime factory.",
        "CocaineBricks": "Illicit. Pressed bricks; feeds the toy factory and the packet press.",
        "CocainePackets": "Illicit. Bagged at courier services for street sale.",
        "CocaineBags": "Illicit. High-value street product, delivered to residents.",
        "LiquidCocaine": "Illicit. Exported at the harbor at a 2.0\u00d7 premium.",
        "HydrochloricAcid": "Precursor. Produced at the bottle factory.",
        "Acetone": "Precursor. Tanker liquid refined from crude oil.",
        "Kerosene": "Precursor. Tanker liquid distilled at the crude-oil supplier.",
        "Pseudoephedrine": "Precursor. Bought with money at supermarket counters.",
        "Phosphorus": "Precursor. Quarry product.",
        "AnhydrousAmmonia": "Precursor. Tanker liquid co-produced with acetone.",
        "MethBase": "Illicit intermediate. Cooked at the quicklime factory.",
        "CrystalMeth": "Illicit. Hidden inside furniture for sale.",
        "HiddenMethBed": "Illicit disguise cargo. Unpacked at the furniture store.",
        "HiddenMethSofa": "Illicit disguise cargo. Unpacked at the furniture store.",
        "HiddenMethArmchair": "Illicit disguise cargo. Unpacked at the furniture store.",
    }
    lines = [
        "---",
        'title: "Schedule I \u2014 Cargo"',
        "description: Every cargo added by the Schedule I mod \u2014 payments, weights and transport.",
        "sidebar:",
        "  label: Cargo",
        "  order: 2",
        "---",
        "",
        STAMP,
        "",
        "Payment = base rate \u00d7 distance, multiplied by the destination's [pay multiplier](/schedule-i/delivery-points/). "
        "Only cargos marked *spawns* appear as ambient traffic \u2014 everything else exists only through "
        "the [production chains](/schedule-i/production/).",
        "",
        "| Cargo | Pays per km | Weight (kg) | Cargo space | Spawns | Notes |",
        "|---|---:|---:|---|---|---|",
    ]
    for e in DATA["cargo_entries"]:
        spaces = ", ".join(e.get("cargo_space_types") or ["\u2014"])
        wmin, wmax = e.get("weight_min"), e.get("weight_max")
        weight = f"{wmin}\u2013{wmax}" if wmin != wmax else str(wmin)
        spawn = "yes" if (e.get("spawn_probability") or 0) > 0 else "no"
        lines.append(
            f"| {display(e)} | {e['payment_per_km']} | {weight} | {spaces} | {spawn} | {notes.get(e['row_name'], '\u2014')} |"
        )
    lines += ["", STAMP, ""]
    (DOCS / "cargo.md").write_text("\n".join(lines))


def gen_production():
    lines = [
        "---",
        'title: "Schedule I \u2014 Production"',
        "description: Sources, transforms and catalysts of the Schedule I supply chain.",
        "sidebar:",
        "  label: Production",
        "  order: 3",
        "---",
        "",
        STAMP,
        "",
        "## Sources",
        "",
        "Sites that passively generate cargo over time \u2014 no input needed. The cargo appears in the "
        "site's storage (see the [storage caps](/schedule-i/delivery-points/)) and is delivered like "
        "any other cargo:",
        "",
        "| Site | Produces | Rate |",
        "|---|---|---:|",
    ]
    for s in DATA["sources"]:
        for rec in s["recipes"]:
            lines.append(f"| {s['delivery_point']} | {rec['cargo']} | every {rec['production_time']} s |")
    lines += [
        "",
        "## Transforms",
        "",
        "Conversion recipes. A transform only runs while the site accepts the input cargo \u2014 check the "
        "[demand table](/schedule-i/delivery-points/) before hauling. Recipes marked *(hidden)* exist "
        "in the site's production list but are not advertised to players.",
        "",
        "| Site | Input | Output | Time |",
        "|---|---|---|---:|",
    ]
    for t in DATA["transforms"]:
        for rec in t["recipes"]:
            inp = rec.get("input_cargo")
            inp_s = f"{inp} \u00d7{rec['input_count']}" if inp else "\u2014"
            hidden = " *(hidden)*" if rec.get("hidden") else ""
            lines.append(f"| {t['delivery_point']} | {inp_s} | {recipe_out(rec)}{hidden} | {rec['production_time']} s |")
    lines += [
        "",
        "## Catalysts",
        "",
        "Money spent at a production site to **double its production speed** while the catalyst "
        "budget lasts. Catalysts are consumed \u2014 they buy speed, they do not pay for anything:",
        "",
        "| Site | Catalyst | Time per catalyst |",
        "|---|---|---:|",
    ]
    for c in DATA["catalysts"]:
        for rec in c["recipes"]:
            lines.append(f"| {c['delivery_point']} | {rec['cargo']} \u00d7{rec['count']} | {rec['production_time']} s |")
    lines += ["", STAMP, ""]
    (DOCS / "production.md").write_text("\n".join(lines))


def gen_delivery_points():
    lines = [
        "---",
        'title: "Schedule I \u2014 Delivery Points"',
        "description: Storage caps and demand (pay multipliers) at every Schedule I delivery point.",
        "sidebar:",
        "  label: Delivery Points",
        "  order: 4",
        "---",
        "",
        STAMP,
        "",
        "## Demand \u2014 what sites buy, and at what pay",
        "",
        "Demand is **per cargo**: each entry carries its own pay multiplier and storage cap, so a site "
        "buying moonshine never reprices the fuel it also sells. The multiplier applies on top of the "
        "cargo's per-km rate from the [cargo table](/schedule-i/cargo/).",
        "",
        "| Site | Buys | Pays | Storage cap |",
        "|---|---|---:|---:|",
    ]
    for d in DATA["demand_configs"]:
        for e in d["entries"]:
            lines.append(f"| {d['delivery_point']} | {e['cargo_key']} | {e['payment_multiplier']:g}\u00d7 | {e['max_storage']} |")
    lines += [
        "",
        "## Storage \u2014 what sites hold",
        "",
        "Maximum stock per cargo at each site. When a site's storage is full, its production (and "
        "your delivery) waits until it drains \u2014 low caps force players to spread deliveries across "
        "multiple sites.",
        "",
        "| Site | Cargo | Max storage |",
        "|---|---|---:|",
    ]
    for s in DATA["storage"]:
        for e in s["entries"]:
            lines.append(f"| {s['delivery_point']} | {e['cargo_key']} | {e['max_storage']} |")
    lines += ["", STAMP, ""]
    (DOCS / "delivery-points.md").write_text("\n".join(lines))


def gen_index():
    lines = [
        "---",
        'title: "Schedule I"',
        "description: The AMC illicit cargo economy \u2014 moonshine, cocaine and meth supply chains added by the Schedule I mod.",
        "sidebar:",
        "  label: Overview",
        "  order: 1",
        "---",
        "",
        STAMP,
        "",
        "The Schedule I mod adds the **illicit cargo economy**: precursor chemicals, drug production "
        "chains, and the sites that buy the finished product. Hauling it builds your "
        "[criminal score](/justice/illicit-delivery/) \u2014 and attracts police attention.",
        "",
        "You need the **Schedule I client pak** installed to interact with the modded sites \u2014 see "
        "[Mods & Downloads](/mods/). The server side runs automatically.",
        "",
        "## The supply chains at a glance",
        "",
        "```text",
        "PRECURSORS                      PRODUCTION                        PRODUCT",
        "",
        "Bottle Factory \u2500\u2500 HCl \u2500\u2510",
        "                       \u2500\u253c\u2500\u25b6 Farm Sunflower \u2500\u2500\u25b6 Cocaine Base (dump)",
        "Oil Refinery \u2500\u2500 Acetone\u2518         \u2502                   \u2502",
        "                                 \u2502 (Money catalyst)   \u25bc",
        "                                 \u2502            Quicklime Factory \u2500\u2500\u25b6 Cocaine Bricks",
        "                                 \u2502                                          \u2502",
        "                                 \u2502                        \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2524",
        "Hemp Farm \u2500\u2500\u25b6 Coca Paste (dump) \u2518                        \u25bc                 \u25bc",
        "                                                  Toy Factory        Courier Service",
        "                                                  Bricks\u25b6Packets    Packets \u25b6 Bags",
        "                                                  Bricks\u25b6Money            \u2502",
        "                                                                          \u25bc",
        "Copper Mine \u2500\u2500 Corn \u2500\u2500\u25b6 Moonshine Kegs \u2500\u2500\u25b6 Supermarket \u2500\u2500\u25b6 Moonshine  Residents",
        "                                \u2502              Bottles        (demand)",
        "                                \u2514\u2500\u2500\u25b6 Gas Station (demand) \u2500\u2500\u25b6 consumed",
        "",
        "Limestone Quarry \u2500\u2500\u25b6 Phosphorus \u2500\u2510",
        "Oil Supplier \u2500\u2500\u25b6 Kerosene \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u25b6 Quicklime Factory \u2500\u2500\u25b6 Meth Base",
        "                                 \u2502                           \u2502",
        "Supermarket \u2500\u2500 Money \u2500\u2500\u25b6 Pseudoephedrine \u2518                 \u25bc",
        "                                                    Furniture Factory",
        "                                                    Meth Base \u25b6 hidden",
        "                                                    in beds / sofas /",
        "                                                    armchairs",
        "                                                             \u2502",
        "                                                             \u25bc",
        "                                                    Furniture Store",
        "                                                    unpacks \u25b6 Crystal",
        "                                                    Meth + Money",
        "```",
        "",
        "Money catalysts at the four production sites double their speed \u2014 bring cash when hauling "
        "inputs there. Money is itself a cargo: the toy-factory launderer and the "
        "[harbor](/schedule-i/delivery-points/) turn product into cash payouts.",
        "",
        "## In this section",
        "",
        "- [Cargo](/schedule-i/cargo/) \u2014 every cargo, pay rates, weights, transport type",
        "- [Production](/schedule-i/production/) \u2014 sources, transforms and catalysts",
        "- [Delivery Points](/schedule-i/delivery-points/) \u2014 demand, pay multipliers and storage caps",
        "",
        STAMP,
        "",
    ]
    (DOCS / "index.md").write_text("\n".join(lines))


if __name__ == "__main__":
    DOCS.mkdir(parents=True, exist_ok=True)
    gen_index()
    gen_cargo()
    gen_production()
    gen_delivery_points()
    print(f"generated Schedule I pages for version {V}")
