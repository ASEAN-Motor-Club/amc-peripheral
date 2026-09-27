---
title: Playing a criminal
description: Illicit cargo, criminal score, wanted status, chases and jail.
sidebar:
  label: Playing a criminal
  order: 2
---

This guide is for the **criminal** side of the club's law-enforcement
system. (Running police instead? Read [Serving as
police](/justice/police/).)

Hauling **illicit cargo** (drugs and money pallets - the full list in
[Illicit Delivery](/justice/illicit-delivery/)) builds your **criminal
score**. Deliveries can trigger a random **Wanted** status, police will
chase and try to **arrest** you, and an arrest means **jail** plus
**confiscation**. Escape, and your wanted status decays - pulling it off
while cops are on duty earns an **evasion bonus** scaled by how real the
chase was.

## Criminal score

Every illicit delivery payment adds **100% of the payment** to your
criminal score. Your **criminal level** is derived from it:
`level = score / 50,000 + 1` (floored) - check the `/criminals`
leaderboard in game. The score **decays**: 48 hours of grace after your
last illicit delivery, then it halves every 7 days, and below $5,000 it
clears to zero. The full delivery picture (cargo list, boss tax, money
risk premium) lives in [Illicit Delivery](/justice/illicit-delivery/).

## Getting wanted

Delivering illicit cargo can trigger a random **Wanted** status:

- **Any delivery of $1,000,000 or more is wanted outright** - no roll,
  no mercy from cop proximity.
- Below that, the chance scales with the size of the delivery relative
  to your criminal score: big hauls on a fresh record are risky, a
  kingpin's small run is nearly safe.
- There's a **5% floor** - every illicit delivery carries at least that
  much risk.
- **Camping delivery points doesn't help police** - the closer an officer
  is when the roll happens, the lower the chance (down to the 5% floor).
  Beyond 1 km the roll runs at full odds.

When a trigger fires you get a **30-second grace period**: a private
popup asks you to switch to a suitable vehicle. You are **not** wanted
yet - no chase, no tracking. But logging out during those 30 seconds is
an unconditional arrest.

### Chance table (base odds, no cop nearby)

Real delivery window: typical 100k-500k hauls, absolute max ~1.5M.

- Delivery $1,000,000 or more: **100% wanted**, always.
- Fresh record (50k score): 10k → 7% · 50k → 35% · 100k → 67% · 300k → 95% · 500k → 98%
- 1M score: 10k → 5% · 50k → 9% · 100k → 20% · 300k → 65% · 500k → 83%
- 5M score: 10k → 5% · 50k → 6% · 100k → 9% · 300k → 34% · 500k → 57%
- 20M score: 10k → 5% · 50k → 6% · 100k → 8% · 300k → 25% · 500k → 45%
- 50M score: 10k → 5% · 50k → 6% · 100k → 7% · 300k → 23% · 500k → 42%

Heat fades as the record builds - rank protection in action: repeated
500k runs see the chance fall from 98% on a fresh record to 83% at 1M,
57% at 5M, 45% at 20M.

## While wanted

You spawn at **at least 5 stars** - and the bigger the haul that
triggered it, the higher: every full **$100,000 of the delivery payment
adds one star** ($800k delivery → 8★, $1M → 10★). Stars are a countdown
display only - they don't change any mechanic. Severity lives in your
**bounty**, set once at the trigger: **10% of your criminal score**,
frozen for the whole chase.

How wanted decays:

- **Speed matters most.** The pivot is **50 km/h**: above it your wanted
  timer grows, below it the timer decays.
- **Distance helps.** Far from any cop, hiding decays much faster than
  point-blank.
- With no pressure, the timer clears in roughly **10 minutes**.

If your wanted status runs out **while cops are on duty**, that's a
successful evasion - but the size of the reward depends on the **chase
quality**. While you're wanted, a meter builds from how close the nearest
officer is and how fast you're driving; a chase only counts if an officer
is actually within ~1 km of you. On evasion you get a bonus of **up to
10% of your score**, scaled by that meter:

- **Full chase** - officers on your tail at speed for several minutes:
  the full **+10%**.
- **Some pressure** - a genuine but short or distant chase: a few percent.
- **No chase at all** - nobody ever got close: **nothing**.

The public announcement when you evade reflects the same thing, from
"spectacular escape" down to a plain "no longer wanted".

### Time to clear while hiding (minutes, from 5★)

- Parked (0 km/h): 500 m from a cop → 10.0 · 1 km → 7.1 · 2 km → 5.4 · 3 km → 4.7 · 5 km → 4.2 · 10 km → 3.8
- Creeping (25 km/h): 500 m → 20.0 · 1 km → 14.3 · 2 km → 10.8 · 3 km → 9.5 · 5 km → 8.4 · 10 km → 7.5

Don't creep. Stop and hide, or run.

## Getting arrested

There is no handcuff mechanic - arrests happen through four paths:

- **Traffic-stop pull-over**: a police officer pulls you over. Possible
  whenever you are wanted - and even when you're not wanted but have
  criminal score, though a not-wanted arrest is **jail only** (no money
  or score loss).
- **Logging out** within 2 km of an on-duty officer.
- **Going underwater** while wanted.
- **Entering a teleport portal** while wanted - instant arrest.

Teleporting away mid-chase (`/tp`, `/tp2marker`) is currently **allowed**,
but that rule is under review.

An arrest means:

- The **bounty is confiscated** from your wallet - and the same amount is
  taken off your criminal score. Your rap sheet and your money bite
  identically.
- The money goes to the **treasury**, with the arrest reward **split
  among all on-duty police**.
- **Jail**: a real 60-second hold. Leaving the 10 m jail perimeter
  teleports you straight back.

## Other things to know

- **Modded vehicles**: getting into a modded vehicle while wanted
  despawns it. Illicit profit from a modded vehicle or on-foot delivery
  is zeroed.
- **Suspect costumes** (Butcher, Werewolf) are cosmetic only - they don't
  make you arrestable.
- **The boss tax**: on every illicit delivery, the server's highest-
  scoring player takes a cut of **5-20%**. Rivals pay the floor, fresh
  criminals pay the most - details in [Illicit
  Delivery](/justice/illicit-delivery/).
