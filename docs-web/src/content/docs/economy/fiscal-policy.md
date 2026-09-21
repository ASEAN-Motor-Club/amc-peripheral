---
title: Fiscal Policy
description: Wealth tax, bank interest, and the Sovereign Reserves framework.
sidebar:
  label: Fiscal Policy
  order: 2
---

## Summary

This document sets out the ASEAN Motor Club's fiscal policy for managing the money supply, including:

- A progressive wealth tax on idle bank balances, scaled by offline duration

- Bank interest with balance-dependent scaling and offline decay

- Establishment of the Sovereign Reserves Fund, with a monthly Net Investment Returns Contribution (NIRC) to the operating treasury

These measures aim to curb hyperinflation, incentivise active participation, and build long-term national reserves.

## 1. Overview

The ASEAN Motor Club economy has experienced sustained inflationary pressure over the past year, driven by high interest rates on bank deposits and a concentration of wealth in idle accounts. Without intervention, the money supply will continue to grow unchecked, eroding the purchasing power of active participants.

This policy introduces three interlocking mechanisms:

- Wealth Tax — a progressive hourly tax on offline accounts above $1,000,000, using marginal brackets

- Interest Decay — bank interest that decays with time offline, rewarding active players

- Sovereign Reserves — a locked national fund that receives wealth tax revenue, with only a controlled monthly drip to the operating treasury

## 2. Wealth Tax

### 2.1 Scope & Exemption

The wealth tax applies to all character bank accounts held at the Bank of ASEAN with a balance exceeding $1,000,000 (the exempt threshold). Characters with a null game GUID (zombie accounts) are excluded.

Tax is computed and deducted hourly, based on the number of hours the character has been offline.

### 2.2 Progressive Brackets

Tax is applied marginally across three tiers. Only the portion of balance within each bracket is taxed at that bracket's rate.

_Table 1: Wealth Tax Brackets_

| Bracket | Balance Range | k-factor |
|---|---|---|
| Exempt | $0 – $1,000,000 | 0 (not taxed) |
| Low | $1,000,000 – $20,000,000 | 0.65 |
| Mid | $20,000,000 – $100,000,000 | 1.05 |
| High | $100,000,000+ | 1.55 |


### 2.3 Rate Formula

The hourly tax rate for each bracket uses a log-plateau decay function, which ensures monotonically increasing cumulative tax over time:

The cumulative fraction lost follows k/2 · ln(1 + t/S)², which grows monotonically — there is no recovery window for long-term idleness.

### 2.4 Effective Tax Rates

_Table 2: Effective hourly rate by offline duration (High bracket, k=1.55)_

| Offline Duration | Hourly Rate | ~Daily Equivalent |
|---|---|---|
| 1 hour | 0.00003% | 0.00% |
| 24 hours (1 day) | 0.00078% | 0.02% |
| 168 hours (1 week) | 0.005% | 0.12% |
| 720 hours (1 month) | 0.015% | 0.37% |
| 2,163 hours (~90 days) | 0.025% | 0.60% |
| 8,760 hours (1 year) | 0.023% | 0.55% |


## 3. Bank Interest

### 3.1 Base Rate

Bank of ASEAN pays hourly interest on all liability (checking) accounts. The base rate is 2.2% per hour, with a 2× multiplier for online players.

_Table 3: Interest Rate Parameters_

| Parameter | Value |
|---|---|
| Base hourly rate | 2.2% |
| Online multiplier | 2.0× |
| Balance scaling threshold | $10,000,000 |
| Balance scaling constant | $40,000,000 |
| Offline decay k | 2.0 |


### 3.2 Balance Scaling

For balances above the $10M threshold, interest is scaled down using an exponential decay:

This creates a natural ceiling (~$170M) where interest earned approaches zero, preventing unlimited compounding.

_Table 4: Effective interest rate by balance (online player)_

| Balance | Scale Factor | Effective Hourly Rate |
|---|---|---|
| $1,000,000 | 100% | 4.40% |
| $10,000,000 | 100% | 4.40% |
| $30,000,000 | 60.65% | 2.67% |
| $50,000,000 | 36.79% | 1.62% |
| $100,000,000 | 10.54% | 0.46% |
| $170,000,000 | 1.83% | 0.08% |


### 3.3 Offline Decay

When a player is offline, their interest rate decays using a log-plateau formula with k=2.0. The longer they are offline, the less interest they earn — eventually approaching zero.

## 4. Sovereign Reserves Fund

### 4.1 Purpose

Inspired by Singapore's GIC and Temasek sovereign wealth funds, the ASEAN Motor Club maintains a Sovereign Reserves Fund — a locked government asset account that accumulates wealth tax revenue.

The reserves serve three purposes:

- Liquidity destruction — money taxed from idle accounts is removed from the active money supply

- Long-term stability — reserves provide a shock absorber for the economy

- Community metric — reserves represent national prosperity, visible to all citizens

### 4.2 Fund Structure

_Table 5: Government Accounts_

| Account | Type | Purpose |
|---|---|---|
| Treasury Fund | Operating (ASSET) | Day-to-day spending: job bonuses, subsidies, Ministry budget |
| Sovereign Reserves | Locked (ASSET) | Receives wealth tax. Not directly spendable. |


### 4.3 NIRC — Net Investment Returns Contribution

Following Singapore's constitutional framework, a controlled portion of reserves is transferred to the operating treasury as the NIRC:

This transfer runs as a daily automated process at 00:05 server time.

_Table 6: NIRC Projections (based on ~$16M/day wealth tax inflow)_

| Timeline | Estimated Reserves | Monthly NIRC | Daily NIRC |
|---|---|---|---|
| Month 1 | $480,000,000 | $24,000,000 | $800,000 |
| Month 3 | $1,200,000,000 | $60,000,000 | $2,000,000 |
| Month 6 | $2,100,000,000 | $105,000,000 | $3,500,000 |
| Year 1 | $3,500,000,000 | $175,000,000 | $5,833,000 |


## 5. Flow of Funds

The following diagram illustrates the complete monetary flow in the ASEAN Motor Club economy:

5.1 Government Employee Revenue Government employees are a significant source of treasury revenue. When a gov employee completes deliveries, their base earnings are confiscated from their wallet and redirected directly to the Treasury Fund. Contract completion bonuses are burned (destroyed from circulation without entering the treasury), serving as an automatic money sink.

For full details on the three-track income system, see Government Employee Programme: Financial Mechanics.

## 6. Economic Impact Assessment

### 6.1 Comparison: Active vs Idle Players

_Table 7: 30-day net balance change by player behaviour ($10M starting balance)_

| Player Type | Interest Earned | Wealth Tax Paid | Net Change |
|---|---|---|---|
| Daily active (1h+/day) | +$3,168,000 | -$5,400 | +$3,162,600 |
| Weekly active (1h/week) | +$1,584,000 | -$37,800 | +$1,546,200 |
| Idle 30 days | +$1,213,496 | -$260,112 | +$953,384 |
| Idle 90 days | +$3,204,487 | -$1,597,596 | +$1,606,891 |
| Idle 365 days | +$11,379,579 | -$9,196,040 | +$2,183,539 |


For detailed analysis including balance tier impact, tax vs interest crossover modelling, and projected revenue based on real account data, see Fiscal Policy Analysis.

## 7. Technical Reference

_Table 9: All fiscal policy constants_

| Constant | Value | Description |
|---|---|---|
| INTEREST_RATE | 0.022 | Base hourly interest rate (2.2%) |
| ONLINE_INTEREST_MULTIPLIER | 2.0 | Bonus multiplier for online players |
| INTEREST_THRESHOLD | 10,000,000 | Balance above which interest is scaled down |
| INTEREST_SCALE | 40,000,000 | Exponential decay scale constant |
| INTEREST_DECAY_K | 2.0 | Offline interest decay factor |
| WEALTH_TAX_EXEMPT | 1,000,000 | Balance exempt from wealth tax |
| WEALTH_TAX_S | 2,163 | Log-plateau time scale (hours, ~90 days) |
| NIRC_MONTHLY_RATE | 0.05 | 5% of reserves drips to treasury per month |
| Job | Schedule | Description |
|---|---|---|
| Bank Interest | Every hour, minute 0 | Applies interest to all eligible accounts |
| Wealth Tax | Every hour, minute 0, second 30 | Applies progressive tax to offline accounts >$1M |
| NIRC Transfer | Daily at 00:05 | Transfers 5%/30 of Sovereign Reserves to Treasury Fund |
| Credit Score | Daily at 00:15 | Evaluates all character credit scores |


### Wealth Tax Entry

| Account | Debit | Credit |
|---|---|---|
| Player Checking (Liability, Bank) | tax_amount | — |
| Sovereign Reserves (Asset, Government) | — | tax_amount |


Debit on a liability account reduces the player's balance. Credit on an asset account increases reserves.

### NIRC Transfer Entry

| Account | Debit | Credit |
|---|---|---|
| Treasury Fund (Asset, Government) | nirc_amount | — |
| Sovereign Reserves (Asset, Government) | — | nirc_amount |


Credit reduces reserves, debit increases operating treasury.

### Related

- Treasury Dashboard

- Fiscal Analysis

- Balance Calculator