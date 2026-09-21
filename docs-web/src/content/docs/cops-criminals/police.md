---
title: Serving as police
description: Going on duty, chases, arrests and rewards.
sidebar:
  order: 3
---

## Going on duty

`/police` activates police duty. Requirements:

- A **police uniform** (from the approved costume list).
- **On foot** — you can't duty-up from inside a vehicle.
- You can't duty up **while wanted**, and a suspect costume blocks it too.
- If your **criminal score is above zero**, duty-up asks for a
  **confirmation code** — entering it **wipes your criminal score to
  zero** before the activation completes. This is the intended way to
  retire your record and join the force.

Activating teleports you to the nearest police station (stations within
1 km of a wanted suspect are skipped). While on duty your name tag shows
your rank, e.g. `[RP1]`.

## On-duty rules

Police teleporting is locked down while on duty — this is enforced
server-side:

- No `/tp` to custom destinations, no `/tp2marker`.
- No teleporting to points within 1 km of a wanted suspect.
- Teleports are simply silent-blocked on duty.

Leaving duty (via `/police` again) restores normal rules.

## The chase

When a player becomes wanted, every on-duty officer receives **compass
flashes** — bearing and distance to the suspect. The design:

- Updates are **throttled** — you read flashes while driving, they are
  not a live pin on the map.
- The interval slows when the suspect drives fast and is far away.
- A suspect **hiding within 500 m of any officer** stops receiving
  updates silently.
- More officers watching the same suspect does **not** multiply the
  flash rate — the force's total intel is capped.

Speed and distance cut both ways: a suspect driving fast and far is
harder to corner, but hiding slow and close clears their wanted status
faster.

**No cops on duty = no wanted system.** If every officer goes off duty,
all active wanted statuses are cleared (amnesty) and no new triggers
fire until someone is back on duty.

## Making arrests

You don't need a special command — arrests happen automatically through
the game's traffic-stop system:

1. Get behind a suspect in your vehicle and perform the **pull-over**.
2. Choose **warning** or **penalty** — a penalty against a wanted player
   executes the full arrest: teleport to jail, confiscation, reward.

Other arrest paths are automatic: the suspect logging out within 2 km of
you, going underwater, or entering a portal while wanted.

## Rewards

- The **arrest reward** is split among **all online, non-AFK police** —
  not pocketed by the arresting officer alone.
- On-duty police also collect a **police salary** (2× UBI) every payout
  tick, regardless of chase outcomes.
- Confiscated money goes to the treasury; the reward split comes out of
  the arrest.

Your **police level** (shown in the `P` of your duty tag) grows from
confiscations you've been part of.

## See also

Playing the other side? Read [Life of a criminal](/cops-criminals/criminals/).
