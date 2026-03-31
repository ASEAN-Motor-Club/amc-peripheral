# AMC Backend Database Guide

PostgreSQL database powering the ASEAN Motor Club game server backend.
Contains live player data, delivery/race history, economy, teams, factions, police system, and government.

## Access Notes

- Read-only access. Only SELECT and WITH (CTE) queries are allowed.
- Finance tables (`amc_finance_*`) are access-restricted and will return permission errors.
- Partition tables (`amc_charloc_p*`) are internal — query `amc_characterlocation` instead.
- All timestamps are `timestamptz` (UTC). The server timezone is Asia/Bangkok (UTC+7).
- Player IDs (`unique_id`) are Steam IDs (large integers like `76561198012345678`).

## Core Identity Tables

### amc_player
Steam accounts. One player can have multiple in-game characters.

| Column | Type | Notes |
|--------|------|-------|
| unique_id | bigint | PK. Steam ID |
| discord_user_id | bigint | Linked Discord account (NULL if unverified) |
| discord_name | varchar | Discord display name |
| adminstrator | bool | Server admin (note: typo in column name is intentional) |
| suspect | bool | Flagged for suspicious activity |
| social_score | int | Community reputation score |

### amc_character
In-game characters. Players may have multiple characters (alts).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | In-game character name |
| guid | varchar | Unique character GUID from game engine |
| player_id | bigint | FK → amc_player.unique_id |
| money | int | Current wallet balance |
| driver_level | int | General driving XP level |
| truck_level | int | Trucking XP level |
| bus_level | int | Bus driving XP level |
| taxi_level | int | Taxi driving XP level |
| police_level | int | Police rank level |
| wrecker_level | int | Tow truck/wrecker level |
| racer_level | int | Racing XP level |
| last_location | geometry | PostGIS point (x, y, z) — last known position |
| last_vehicle_key | varchar | Last vehicle driven (game vehicle ID) |
| last_online | timestamptz | When character was last seen online |
| rp_mode | bool | Roleplay mode enabled |
| gov_employee_until | timestamptz | Government employee status expiry |
| gov_employee_level | int | Government employee rank |
| gov_employee_contributions | bigint | Total government contributions |
| criminal_laundered_total | bigint | Total money laundered (criminal stat) |
| police_confiscated_total | bigint | Total confiscated as police officer |
| credit_score | int | 0–200 (100 = neutral). Affects loan interest |
| total_donations | bigint | Lifetime donation amount |

## Activity & Session Tracking

### amc_playerstatuslog
Login/logout sessions with duration.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| timespan | tstzrange | Time range `[login, logout)` — use `lower(timespan)` for login time, `upper(timespan)` for logout |
| duration | interval | Session length |
| character_id | bigint | FK → amc_character.id |

### amc_playerchatlog
In-game chat messages.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| timestamp | timestamptz | When message was sent |
| text | text | Message content |
| character_id | bigint | FK → amc_character.id |

### amc_playervehiclelog
Vehicle purchase/sale/enter/exit events.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| timestamp | timestamptz | When event occurred |
| action | varchar | One of: `entered`, `exited`, `bought`, `sold` |
| character_id | bigint | FK → amc_character.id |
| vehicle_name | varchar | Vehicle game ID (e.g. `Tuscan`) |

## Delivery & Cargo System

### amc_servercargoarrivedlog
Completed cargo deliveries — the main economic activity log.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| timestamp | timestamptz | Delivery time |
| cargo_key | varchar | Cargo type ID (e.g. `SmallBox`, `Container20ft`) |
| payment | bigint | Amount earned |
| weight | float | Cargo weight |
| damage | float | Damage sustained during transport |
| character_id | bigint | FK → amc_character.id |
| player_id | bigint | FK → amc_player.unique_id |
| sender_point_id | varchar | Pickup location ID |
| destination_point_id | varchar | Delivery location ID |
| data | jsonb | Full webhook payload with vehicle info, distance, etc. |

### amc_delivery
Active in-progress deliveries (not yet delivered).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| cargo_key | varchar | Cargo type ID |
| quantity | int | Number of items |
| character_id | bigint | FK → amc_character.id |
| source_point_id | varchar | Pickup location |
| state | varchar | Current delivery state |
| created_at | timestamptz | When cargo was picked up |

### amc_deliveryjob
Posted delivery jobs (board postings with rewards).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | Job title |
| description | text | Job description |
| bonus_multiplier | float | Payment bonus multiplier |
| completion_bonus | int | Flat bonus on completion |
| fulfilled | bool | Whether job is completed |
| rp_mode | bool | Roleplay job |
| funding_term_id | bigint | FK → amc_ministryterm.id (government-funded jobs) |

## Racing System

### amc_gameevent
Individual race instances.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | Race name |
| guid | varchar | Game-generated race GUID |
| start_time | timestamptz | Race start time |
| state | int | Race state (running, finished, etc.) |
| race_setup_id | bigint | FK → amc_racesetup.id (track/config) |
| scheduled_event_id | bigint | FK → amc_scheduledevent.id (if from an organized event) |

### amc_gameeventcharacter
Race participants with results.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| rank | int | Final position |
| laps | int | Laps completed |
| section_index | int | Last checkpoint reached |
| best_lap_time | float | Best single lap in seconds |
| net_time | float | Total race time minus penalties |
| penalty_seconds | float | Time penalties |
| finished | bool | Completed the race |
| disqualified | bool | Disqualified |
| wrong_engine | bool | Used wrong engine for class |
| wrong_vehicle | bool | Used wrong vehicle for class |
| character_id | bigint | FK → amc_character.id |
| game_event_id | bigint | FK → amc_gameevent.id |

### amc_racesetup
Track configurations (routes, laps, allowed vehicles).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | Track name (may be NULL — check config JSON) |
| config | jsonb | Full track config: `Route.RouteName`, `NumLaps`, `VehicleKeys`, `EngineKeys` |
| hash | varchar | Config hash for deduplication |

### amc_scheduledevent
Organized racing events (from Discord/admin).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | Event name |
| start_time | timestamptz | Scheduled start |
| end_time | timestamptz | Scheduled end |
| championship_id | bigint | FK → amc_championship.id (if part of a championship) |
| time_trial | bool | Time trial format (multiple attempts allowed) |
| race_setup_id | bigint | FK → amc_racesetup.id |

### amc_championship / amc_championshippoint
Championship series and point standings.

## Teams

### amc_team
Racing/social teams.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | Team name |
| tag | varchar | Short tag (max 6 chars), e.g. `[AMC]` |
| racing | bool | Active in racing |

### amc_teammembership
Team rosters.

| Column | Type | Notes |
|--------|------|-------|
| player_id | bigint | FK → amc_player.unique_id |
| team_id | bigint | FK → amc_team.id |
| character_id | bigint | FK → amc_character.id |
| date_joined | timestamptz | Join date |

## Factions & Police

### amc_factionmembership
Cop/Criminal faction assignments.

| Column | Type | Notes |
|--------|------|-------|
| player_id | bigint | FK → amc_player.unique_id |
| faction | varchar | `cop` or `criminal` |
| joined_at | timestamptz | When they joined |
| last_switched_at | timestamptz | Last faction switch (24h cooldown) |

### amc_policesession
On-duty police sessions.

| Column | Type | Notes |
|--------|------|-------|
| character_id | bigint | FK → amc_character.id |
| started_at | timestamptz | Shift start |
| ended_at | timestamptz | Shift end (NULL = still on duty) |

### amc_confiscation
Police confiscation records.

| Column | Type | Notes |
|--------|------|-------|
| character_id | bigint | FK → amc_character.id (criminal) |
| officer_id | bigint | FK → amc_character.id (arresting officer) |
| cargo_key | varchar | Confiscated cargo type |
| amount | int | Dollar value confiscated |
| created_at | timestamptz | When confiscation occurred |

### amc_criminalrecord
Active criminal records with expiry.

| Column | Type | Notes |
|--------|------|-------|
| character_id | bigint | FK → amc_character.id |
| reason | varchar | Criminal offense |
| created_at | timestamptz | When record was created |
| expires_at | timestamptz | When record expires |

## Government & Ministry

### amc_ministryterm
Minister terms in office.

| Column | Type | Notes |
|--------|------|-------|
| minister_id | bigint | FK → amc_character.id |
| start_date | timestamptz | Term start |
| end_date | timestamptz | Term end |
| is_active | bool | Currently serving |
| initial_budget | numeric | Starting budget |
| current_budget | numeric | Remaining budget |
| total_spent | numeric | Amount spent on jobs |

## Server Status

### amc_serverstatus
Periodic server performance snapshots.

| Column | Type | Notes |
|--------|------|-------|
| timestamp | timestamptz | Snapshot time |
| fps | int | Server FPS |
| used_memory | bigint | Memory usage in bytes |
| num_players | int | Players online |

## Common Query Recipes

### "Who delivered the most cargo this week?"
```sql
SELECT c.name, COUNT(*) as deliveries, SUM(scal.payment) as total_earned
FROM amc_servercargoarrivedlog scal
JOIN amc_character c ON scal.character_id = c.id
WHERE scal.timestamp > NOW() - INTERVAL '7 days'
GROUP BY c.name
ORDER BY total_earned DESC
LIMIT 10
```

### "Who played the most hours?"
```sql
SELECT c.name, SUM(psl.duration) as total_time
FROM amc_playerstatuslog psl
JOIN amc_character c ON psl.character_id = c.id
WHERE lower(psl.timespan) > NOW() - INTERVAL '30 days'
GROUP BY c.name
ORDER BY total_time DESC
LIMIT 10
```

### "Show race results for a specific event"
```sql
SELECT c.name, gec.rank, gec.best_lap_time, gec.net_time, gec.laps,
       gec.finished, gec.disqualified
FROM amc_gameeventcharacter gec
JOIN amc_character c ON gec.character_id = c.id
WHERE gec.game_event_id = <event_id>
ORDER BY gec.disqualified, gec.finished DESC, gec.net_time
```

### "Who is on a team?"
```sql
SELECT t.name AS team, t.tag, c.name AS player
FROM amc_teammembership tm
JOIN amc_team t ON tm.team_id = t.id
JOIN amc_character c ON tm.character_id = c.id
ORDER BY t.name, c.name
```

### "Top police officers by confiscations"
```sql
SELECT c.name, c.police_confiscated_total, c.police_level
FROM amc_character c
WHERE c.police_confiscated_total > 0
ORDER BY c.police_confiscated_total DESC
LIMIT 10
```

### "Currently online players"
Use the backend API endpoint instead: `GET /api/active_players/`
For recent activity:
```sql
SELECT c.name, c.last_online, c.last_vehicle_key
FROM amc_character c
WHERE c.last_online > NOW() - INTERVAL '5 minutes'
ORDER BY c.last_online DESC
```

### "What cargo types are delivered most?"
```sql
SELECT cargo_key, COUNT(*) as deliveries, SUM(payment) as total_revenue
FROM amc_servercargoarrivedlog
WHERE timestamp > NOW() - INTERVAL '30 days'
GROUP BY cargo_key
ORDER BY deliveries DESC
```

### "Player's delivery history"
```sql
SELECT scal.timestamp, scal.cargo_key, scal.payment, scal.sender_point_id, scal.destination_point_id
FROM amc_servercargoarrivedlog scal
JOIN amc_character c ON scal.character_id = c.id
WHERE c.name ILIKE '%playerName%'
ORDER BY scal.timestamp DESC
LIMIT 20
```

### "Active criminal records"
```sql
SELECT c.name, cr.reason, cr.expires_at
FROM amc_criminalrecord cr
JOIN amc_character c ON cr.character_id = c.id
WHERE cr.expires_at > NOW()
ORDER BY cr.expires_at
```

## Important Relationships

- **Player → Character**: one-to-many via `amc_character.player_id`
- **Character → Deliveries**: via `amc_servercargoarrivedlog.character_id`
- **Character → Sessions**: via `amc_playerstatuslog.character_id`
- **Character → Race Results**: via `amc_gameeventcharacter.character_id`
- **Character → Team**: via `amc_teammembership.character_id`
- **Player → Faction**: via `amc_factionmembership.player_id`
- **Character → Police Sessions**: via `amc_policesession.character_id`
- **Race Event → Track**: via `amc_gameevent.race_setup_id`
- **Race Event → Organized Event**: via `amc_gameevent.scheduled_event_id`

## Pitfalls

- `amc_player.adminstrator` has a typo — it's intentional, do not "fix" it in queries.
- `amc_playerstatuslog.timespan` is a PostgreSQL range type. Use `lower()` and `upper()` to extract start/end times.
- Finance tables (`amc_finance_account`, `amc_finance_journalentry`, etc.) will return permission denied errors.
- `amc_characterlocation` is a partitioned table — queries work normally but may be slow without timestamp filters.
- Character names are not unique — use `character.id` or `character.guid` for reliable lookups. Use `ILIKE` for name searches.
- The `data` JSON columns on log tables contain the raw webhook payload and may have useful extra fields like vehicle name, distance, travel time.
