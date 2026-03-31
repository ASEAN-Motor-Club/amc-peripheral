# Motor Town Game Database Guide

SQLite database extracted from Motor Town game pak files via the mt-pak-extract ETL pipeline.
Contains authoritative static game data — vehicle specs, parts catalog, cargo definitions, delivery locations, and production chains.

**159 vehicles · 1,237 parts · 84 cargos · 66 delivery points · 101 production recipes**

## Key Tables

### vehicles (159 rows)
All drivable vehicles. IDs are PascalCase strings like `Tuscan`, `Gosan_G7`, `Daiho_Mule`.

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT | PK. Vehicle ID, e.g. `Tuscan`, `Atlas_6x4_Semi` |
| name | TEXT | Display name (same as id but may differ) |
| vehicle_type | TEXT | One of: `Small`, `Pickup`, `Truck`, `SemiTractor`, `SemiTrailer`, `SmallTrailer`, `Bus`, `Bike`, `Kart`, `Racecar`, `HeavyMachinery`, `Motorhome` |
| truck_class | TEXT | NULL for non-trucks. One of: `LightDuty`, `MediumDuty`, `HeavyDuty`, `None` |
| cost | INT | Purchase price in game dollars |
| comport | INT | Comfort rating (higher = more comfortable). Used for taxi/limo suitability. |
| is_taxiable | BOOL | Can be used as a taxi |
| is_limoable | BOOL | Can be used as a limousine |
| is_busable | BOOL | Can be used as a bus |
| is_race_car | BOOL | Racing-only vehicle |
| can_haul_trailer | BOOL | Can tow trailers |
| is_hidden | BOOL | Dev/test vehicle, not available to players |
| is_disabled | BOOL | Disabled in current game version |
| delivery_payment_multiplier | REAL | Multiplier applied to delivery payments |
| delivery_base_payment | INT | Base payment for deliveries |

⚠️ **Always filter**: `WHERE (is_hidden = 0 OR is_hidden IS NULL) AND (is_disabled = 0 OR is_disabled IS NULL)`

### vehicle_parts (1,237 rows)
All equippable parts — engines, tires, transmissions, cargo beds, bodywork, etc.

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT | PK. Part ID, e.g. `SmallBlock_140HP`, `BasicTire_65` |
| name | TEXT | Display name |
| part_type | TEXT | Category. Common values: `Engine`, `Tire`, `Transmission`, `LSD`, `CargoBed`, `Suspension_Spring`, `Suspension_Damper`, `BrakePad`, `Wheel`, `Turbocharger`, `FinalDriveRatio`, `Body`, `Bonnet`, `Fender`, `FrontBumper`, `RearBumper`, `Roof`, `RearWing`, `Bullbar`, `TrailerHitch`, `Winch`, `Utility`, `Attachment`, etc. |
| cost | INT | Purchase price |
| mass_kg | REAL | Part weight in kg (NULL for cosmetic parts) |
| is_hidden | BOOL | Hidden from players |

### vehicle_default_parts (6,026 rows)
Factory-installed parts for each vehicle. Links vehicles to their stock parts.

| Column | Type | Notes |
|--------|------|-------|
| vehicle_id | TEXT | FK → vehicles.id |
| slot | TEXT | Slot name like `Engine`, `Transmission`, `Tire0`..`Tire7`, `Wheel0`..`Wheel7`, `LSD0`, `CargoBed0`, `Body`, `Bonnet`, etc. Tires/wheels are numbered per-axle. |
| part_id | TEXT | FK → vehicle_parts.id |

### vehicle_tags (280 rows)
Gameplay tags for vehicles (used for matchmaking, categorization).

| Column | Type | Notes |
|--------|------|-------|
| vehicle_id | TEXT | FK → vehicles.id |
| tag | TEXT | e.g. `Vehicle.Bus`, `Vehicle.Semi`, `Vehicle.Police`, `Vehicle.EV`, `Vehicle.Delivery.Heavy`, `Vehicle.Bike.SportBike` |

### cargos (84 rows)
All cargo types in the game.

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT | PK. Cargo ID, e.g. `SmallBox`, `Container20ft`, `Log6m`, `CrudeOil` |
| name | TEXT | Display name |
| cargo_type | TEXT | One of: `SmallPackage`, `LargePackage`, `FinalProduct`, `Container`, `Log`, `Wood`, `Coal`, `Stone`, `Sand`, `Concrete`, `Food`, `Furniture`, `Garbage`, `MilitarySupply`, `None` |
| volume_size | INT | Volume in abstract game grid units (1–8 typical) |
| weight_min | REAL | Minimum weight in kg |
| weight_max | REAL | Maximum weight in kg |
| payment_per_km | INT | Base pay rate per km driven |
| payment_multiplier | REAL | Multiplier applied to final payment |
| base_payment | INT | Flat base payment |
| allow_stacking | BOOL | Can be stacked on a flatbed |
| fragile | BOOL | Takes damage from rough driving |
| is_deprecated | BOOL | Removed from current game |

### active_cargos (VIEW, 77 rows) — **Preferred for cargo queries**
Pre-filtered view excluding deprecated cargos, with resolved actual weight from blueprints.

Same columns as `cargos`, plus:
| Column | Type | Notes |
|--------|------|-------|
| actual_weight_kg | REAL | True weight resolved from game blueprints (more accurate than weight_max) |

### cargo_space_types (139 rows)
Maps which cargo types fit in which vehicle bed types.

| Column | Type | Notes |
|--------|------|-------|
| cargo_id | TEXT | FK → cargos.id |
| space_type | TEXT | One of: `Flatbed`, `Box`, `Container`, `Tanker`, `DryBulk`, `Dump`, `Log`, `ConcreteMixer`, `Garbage`, `Grain`, `LiveFishTanker` |

### cargo_bed_specs (8 rows)
Physical dimensions of cargo bed parts.

| Column | Type | Notes |
|--------|------|-------|
| part_id | TEXT | FK → vehicle_parts.id (CargoBed parts only) |
| cargo_space_type | TEXT | Bed type (matches cargo_space_types.space_type) |
| length_cm | REAL | Bed length in centimeters |
| width_cm | REAL | Bed width in centimeters |
| height_cm | REAL | Bed height in centimeters |
| dump_volume_kl | REAL | For dump beds: volume in kiloliters |

### vehicle_cargo_space (78 rows)
Built-in cargo spaces for vehicles (not from swappable parts). Same columns as cargo_bed_specs plus vehicle_id.

### vehicle_weights (145 rows)
Chassis mass extracted from vehicle blueprints.

| Column | Type | Notes |
|--------|------|-------|
| vehicle_id | TEXT | FK → vehicles.id |
| chassis_mass_kg | REAL | Body/chassis weight in kg (excludes parts) |

### delivery_points (66 rows)
All pickup/delivery locations in the game world.

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT | Location ID, e.g. `ConstructionSite`, `CoalWarehouse`, `BurgerCounter` |
| mission_point_type | TEXT | One of: `Factory`, `Farm`, `Mine`, `Store`, `Supermarket`, `Warehouse`, `Construction`, `Container`, `Courier`, `GasStation`, `Logging`, `OilPump`, `DropOff`, `None` |
| max_passive_deliveries | INT | Max items accepted at once |

### production_configs (101 rows)
Production recipes — what inputs produce what outputs at each location.

| Column | Type | Notes |
|--------|------|-------|
| id | INT | PK (auto-increment) |
| delivery_point_id | TEXT | FK → delivery_points.id |
| production_time_seconds | INT | Seconds to complete one cycle |
| is_hidden | BOOL | Hidden recipe |

### production_inputs (92 rows) / production_outputs (58 rows)
Input and output cargos for each production recipe.

| Column | Type | Notes |
|--------|------|-------|
| production_config_id | INT | FK → production_configs.id |
| cargo_id | TEXT | FK → cargos.id |
| quantity | INT | How many units required/produced |

### part_tuning (26,079 rows)
Detailed performance values for parts (engine torque curves, tire grip, suspension settings, etc.)

| Column | Type | Notes |
|--------|------|-------|
| part_id | TEXT | FK → vehicle_parts.id |
| struct_type | TEXT | Data structure category |
| field_name | TEXT | Specific parameter |
| field_value | REAL | Numeric value |

## Useful Views

### vehicles_with_weight
Combines chassis mass + default parts mass into total weight.
Columns: id, name, vehicle_type, truck_class, cost, chassis_mass_kg, parts_weight_kg, total_weight_kg, part_count

### vehicles_with_cargo_space
Shows what cargo space type each vehicle has (from cargo beds or built-in spaces), with dimensions in meters.
Columns: id, name, vehicle_type, truck_class, cargo_space_type, length_m, width_m, height_m, dump_volume_kl, volume_m3, source

### vehicles_with_engines
Links vehicles to their default engine.
Columns: id, name, cost, engine_id, engine_mass_kg

### active_cargos / cargos_with_weights
Pre-filtered cargo views with resolved blueprint weights.

## Common Query Recipes

### "What's the heaviest cargo?"
```sql
SELECT name, actual_weight_kg, cargo_type FROM active_cargos ORDER BY actual_weight_kg DESC LIMIT 5
```

### "What vehicles can carry containers?"
```sql
SELECT DISTINCT v.name, v.vehicle_type, v.cost
FROM vehicles v
JOIN vehicles_with_cargo_space vcs ON v.id = vcs.id
JOIN cargo_space_types cst ON vcs.cargo_space_type = cst.space_type
WHERE cst.cargo_id = 'Container20ft'
  AND (v.is_hidden = 0 OR v.is_hidden IS NULL)
ORDER BY v.cost
```

### "Show default parts for a vehicle"
```sql
SELECT vdp.slot, vp.name AS part_name, vp.part_type, vp.mass_kg
FROM vehicle_default_parts vdp
JOIN vehicle_parts vp ON vdp.part_id = vp.id
WHERE vdp.vehicle_id = 'Tuscan'
ORDER BY vdp.slot
```

### "What's the total weight of a vehicle?"
```sql
SELECT * FROM vehicles_with_weight WHERE id = 'Tuscan'
```

### "Which vehicles have flatbed cargo space?"
```sql
SELECT * FROM vehicles_with_cargo_space WHERE cargo_space_type = 'Flatbed'
```

### "Where is a cargo produced?"
```sql
SELECT dp.id AS location, dp.mission_point_type,
       pi.cargo_id AS input_cargo, pi.quantity AS input_qty,
       po.cargo_id AS output_cargo, po.quantity AS output_qty,
       pc.production_time_seconds
FROM production_configs pc
JOIN delivery_points dp ON pc.delivery_point_id = dp.id
LEFT JOIN production_inputs pi ON pc.id = pi.production_config_id
LEFT JOIN production_outputs po ON pc.id = po.production_config_id
WHERE po.cargo_id = 'SmallBox'
```

### "What cargo can go on a flatbed vs box truck?"
```sql
SELECT space_type, GROUP_CONCAT(cargo_id, ', ') AS compatible_cargos
FROM cargo_space_types
GROUP BY space_type
ORDER BY space_type
```

### "Compare vehicle costs by type"
```sql
SELECT vehicle_type, COUNT(*) as count, 
       MIN(cost) as cheapest, MAX(cost) as most_expensive, AVG(cost) as avg_cost
FROM vehicles
WHERE (is_hidden = 0 OR is_hidden IS NULL)
GROUP BY vehicle_type
ORDER BY avg_cost DESC
```

### "Search for a vehicle by name"
Use LIKE with wildcards — vehicle IDs use PascalCase with underscores:
```sql
SELECT id, name, vehicle_type, cost FROM vehicles WHERE id LIKE '%Gosan%' OR name LIKE '%Gosan%'
```
