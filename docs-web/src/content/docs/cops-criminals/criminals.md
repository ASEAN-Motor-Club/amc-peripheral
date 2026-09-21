---
title: Life of a criminal
description: Illicit cargo, criminal score, wanted status, chases and jail.
sidebar:
  order: 2
---

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

## While wanted

You always spawn at **5 stars**. Stars are a countdown display only —
they don't change any mechanic. Severity lives in your **bounty**, which
is set once at the trigger: **10% of your criminal score**, and it stays
frozen for the whole chase.

How wanted decays:

- **Speed matters most.** Driving keeps heat up; keeping your speed under
  ~50 km/h decays the wanted timer fastest.
- **Distance helps.** Far from any cop, hiding decays much faster than
  point-blank.
- With no pressure, the timer clears in roughly **10 minutes**.

If your wanted status runs out **while cops are on duty**, that's a
successful evasion: you get a **bonus of 10% of your score** added to it.

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
