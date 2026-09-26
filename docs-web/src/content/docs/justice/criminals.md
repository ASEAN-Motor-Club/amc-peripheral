---
title: Playing a criminal
description: Illicit cargo, criminal score, wanted status, chases and jail.
sidebar:
  label: Playing a criminal
  order: 1
---

This guide is for the **criminal** side of the club's law-enforcement
system. (Running police instead? Read [Serving as
police](/justice/police/).)

Hauling **illicit cargo** (money pallets, moonshine, cocaine, ganja and
friends) builds your **criminal score**. Deliveries can trigger a random
**Wanted** status, police will chase and try to **arrest** you, and an
arrest means **jail** plus **confiscation**. Escape, and your wanted
status decays — pulling it off while cops are on duty earns an
**evasion bonus** scaled by how real the chase was.

## Criminal score

Every illicit delivery payment adds **100% of the payment** to your
criminal score. Your **criminal level** is derived from it:
`level = score / 50,000 + 1` (floored). Level shows your rank among
criminals — check the `/criminals` leaderboard in game.

Score **decays over time**: 48 hours after your last illicit delivery
nothing happens, then the score halves every 7 days, down to a $5,000
floor — below that it clears to zero and you have a clean slate.

## Getting wanted

Delivering illicit cargo can trigger a **random Wanted** status:

- The chance grows with the size of the delivery **relative to your
  criminal score** — big hauls on a fresh record are risky, a kingpin's
  small run is nearly safe.
- The chance sits between a **5% floor** on every illicit delivery and a
  **50% ceiling** for huge hauls relative to history.
- **Camping delivery points doesn't help police** — the closer an officer
  is when the roll happens, the lower the chance (down to the 5% floor).

When a trigger fires you get a **30-second grace period**: a private
popup asks you to switch to a suitable vehicle. You are **not** wanted
yet — no chase, no tracking. But logging out during those 30 seconds is
an unconditional arrest.

### Chance table (base odds, before cop attenuation)

Real delivery window: typical 100k–500k hauls, absolute max ~1.5M.

| Score \ delivery | 10k | 50k | 100k | 300k | 500k | 1M | 1.5M |
|---|---|---|---|---|---|---|---|
| fresh (<100k) | 9.5 | 38.1 | 46.3 | 49.6 | 49.8 | 50.0 | 50.0 |
| 1M | 5.2 | 8.6 | 16.7 | 39.2 | 45.4 | 48.8 | 49.4 |
| 5M | 5.0 | 5.4 | 6.4 | 14.9 | 24.8 | 39.1 | 44.4 |
| 20M (kingpin) | 5.0 | 5.0 | 5.2 | 6.5 | 9.0 | 17.7 | 26.1 |
| 50M | 5.0 | 5.0 | 5.0 | 5.4 | 6.1 | 9.1 | 13.2 |


Heat fades as the record builds — that's the rank protection at work:
repeated 100k runs see the chance fall 46% → 41% → 27% → 17% → 10% as
your score grows.

## While wanted

You spawn at **at least 5 stars** — and the bigger the haul that
triggered it, the higher: every full **$100,000 of the delivery payment
adds one star** ($800k delivery → 8★, $1M → 10★). Stars are a countdown
display only — they don't change any mechanic. Severity lives in your
**bounty**, which is set once at the trigger: **10% of your criminal
score**, and it stays frozen for the whole chase.

How wanted decays:

- **Speed matters most.** Driving keeps heat up; keeping your speed under
  ~50 km/h decays the wanted timer fastest.
- **Distance helps.** Far from any cop, hiding decays much faster than
  point-blank.
- With no pressure, the timer clears in roughly **10 minutes**.

If your wanted status runs out **while cops are on duty**, that's a
successful evasion — but the size of the reward depends on the **chase
quality**. While you're wanted, a meter builds from how close the nearest
officer is and how fast you're driving; a chase only counts if an officer
is actually within ~1 km of you. On evasion you get a bonus of **up to
10% of your score**, scaled by that meter:

- **Full chase** — officers on your tail at speed for several minutes:
  the full **+10%**.
- **Some pressure** — a genuine but short or distant chase: a few percent.
- **No chase at all** — nobody ever got close: **nothing**.

The public announcement when you evade reflects the same thing, from
"spectacular escape" down to a plain "no longer wanted".

### Time to clear while hiding (minutes, from 5★)

| Hide speed | ≤500 m from a cop | 1 km | 2 km | 3 km | 5 km | 10 km |
|---|---|---|---|---|---|---|
| 0 km/h | 10.0 | 7.1 | 5.4 | 4.7 | 4.2 | 3.8 |
| 25 km/h | 20.0 | 14.3 | 10.8 | 9.5 | 8.4 | 7.5 |
| 45 km/h (creep) | 100.0 | 71.4 | 53.8 | 47.4 | 41.9 | 37.7 |


Creeping at 45 km/h stays terrible at every distance — don't creep, stop
and hide, or run. (The table assumes the 5★ minimum; bigger hauls start
with more heat on the clock, so their times scale up proportionally.)

## Getting arrested

There is no handcuff mechanic — arrests happen through four paths:

- **Traffic-stop pull-over**: a police officer pulls you over. Possible
  whenever you are wanted — and even when you're not wanted but have
  criminal score, though a not-wanted arrest is **jail only** (no money
  or score loss).
- **Logging out** within 2 km of an on-duty officer.
- **Going underwater** while wanted.
- **Entering a teleport portal** while wanted — instant arrest.

Teleporting away mid-chase (`/tp`, `/tp2marker`) is currently **allowed**,
but that rule is under review.

An arrest means:

- The **bounty is confiscated** from your wallet — and the same amount is
  taken off your criminal score. Your rap sheet and your money bite
  identically.
- The money goes to the **treasury**, with the arrest reward **split
  among all on-duty police**.
- **Jail**: a real 60-second hold. Leaving the jail perimeter teleports
  you straight back.

## Other things to know

- **Modded vehicles**: getting into a modded vehicle while wanted
  despawns it. Illicit profit from a modded vehicle or on-foot delivery
  is zeroed.
- **Suspect costumes** (Butcher, Werewolf) are cosmetic only — they don't
  make you arrestable.
- **The boss tax**: on every illicit delivery, the highest-scoring player
  on the server takes a cut of **5–25%** (progressive — the closer your
  level is to the boss's, the more you pay). It's transferred through the
  bank, works while they're offline, and arrives as a private popup.
