---
title: Money Laundering & Criminal Faction
description: Illicit cargo, criminal score, the boss tax and the /criminals leaderboard.
sidebar:
  label: Money Laundering
  order: 1
---

Delivering illicit cargo builds your **criminal score** — the single
measure of your criminal career. This page covers the score itself and
the money side; see [Playing a criminal](/justice/criminals/) for the
wanted-status, chase and arrest mechanics.

## Illicit cargo

These cargo types are illicit and build your score on delivery:

- Money and Money Pallet
- Ganja and Ganja Pallet
- Coca Leaves Pallet, Coca Paste, Cocaine Bricks
- Cocaine
- Moonshine

Deliveries are grouped by cargo type; every illicit payment credits your
score in full. Legal cargo never touches the score and keeps its
subsidies.

## Criminal score

- Every illicit delivery payment adds **100% of the payment** to your
  criminal score.
- Your **criminal level** is derived live: `level = score / 50,000 + 1`
  (floored). Check the **`/criminals` leaderboard** in game — the top 10
  players by score, with the server-wide boss marked on rank 1.
- On arrest the confiscated **bounty is deducted from your score**
  alongside your wallet — your rap sheet and your money fall together.

## Score decay

The score is a progression stat, and it rots if you stop hauling:

- **48-hour grace** after your last illicit delivery — nothing decays.
- Then the score **halves every 7 days** (real time, including offline).
- Below the **$5,000 floor** the score clears to zero — a clean slate.

## The boss tax

On **every illicit delivery**, the highest-scoring player on the server
(the boss) takes a cut of your payment:

- The cut is **5–25%**, progressive: the closer your level is to the
  boss's, the more you pay (`cut = 5% + 20% × (your level / boss level)²`,
  clamped).
- It's transferred **through the bank** into the boss's checking account,
  so it works while they're offline.
- You receive a **private popup** — no public announcement.

## Evasion bonus

Losing a pursuit the hard way pays: if your wanted status decays to zero
**while cops are on duty** (not during a no-cop amnesty), you earn a
bonus of **10% of your score**.
