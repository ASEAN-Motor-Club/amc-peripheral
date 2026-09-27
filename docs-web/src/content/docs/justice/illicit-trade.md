---
title: Illicit Trade
description: The drug cargo economy - criminal score, the boss tax and the /criminals leaderboard.
sidebar:
  label: Illicit Trade
  order: 1
---

Hauling illicit cargo is the criminal side of the club's law-enforcement
system. The trade runs on **drugs**: ganja, coca and cocaine products,
moonshine - with money pallets as just one cargo among them. Every illicit
delivery builds your **criminal score**, the single measure of your
criminal career.

This page covers the trade itself and the score. See [Playing a
criminal](/justice/criminals/) for wanted status, chases and jail, and
[Serving as police](/justice/police/) for the other side of the law.

## Illicit cargo

These cargo types are illicit and build your score on delivery:

- **Ganja line**: Ganja, Ganja Pallet
- **Coca line**: Coca Leaves Pallet, Coca Paste, Cocaine, Cocaine Base,
  Cocaine Bricks, Cocaine Packets, Cocaine Bags, Liquid Cocaine
- **Moonshine line**: Moonshine, Moonshine Bottles
- **Money line**: Money, Money Pallet

Every illicit payment credits your score in full. Legal cargo never
touches the score and keeps its subsidies.

**Money cargo pays extra when police are on duty** - a risk premium of
50% of the payment per on-duty officer, up to +250% at five officers.
Carrying cash with cops around is well compensated, and that is exactly
where the wanted-trigger risk lives too.

## Criminal score

- Every illicit delivery payment adds **100% of the payment** to your
  criminal score.
- Your **criminal level** is derived live: `level = score / 50,000 + 1`
  (floored). Check the **`/criminals` leaderboard** in game - the top 10
  players by score, with the server-wide boss marked on rank 1.
- On arrest the confiscated **bounty is deducted from your score**
  alongside your wallet - your rap sheet and your money fall together.

## Score decay

The score is a progression stat, and it rots if you stop hauling:

- **48-hour grace** after your last illicit delivery - nothing decays.
- Then the score **halves every 7 days** (real time, including offline).
- Below the **$5,000 floor** the score clears to zero - a clean slate.

## The boss tax

On **every illicit delivery**, the server's highest-scoring player (the
boss) takes a cut of your payment:

- The cut is **5-20%**, and it shrinks as you climb toward the boss: the
  closer your level is to the boss's, the closer you pay to the **5%
  floor**. Fresh criminals pay the most, up to the **20% cap**. Rivals
  get protected - the boss taxes the newcomers, not his nearest
  competition.
- It's transferred **through the bank** into the boss's checking account,
  so it works while they're offline.
- You receive a **private popup** - no public announcement.

## Evasion bonus

Losing a pursuit the hard way pays: if your wanted status decays to zero
**while cops are on duty** (not during a no-cop amnesty), you earn a
bonus of **up to 10% of your score**, scaled by how real the chase was.
See [Playing a criminal](/justice/criminals/) for how chase quality is
measured.
