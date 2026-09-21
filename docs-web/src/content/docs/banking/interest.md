---
title: Bank Interest
description: Hourly interest on checking accounts — rates, balance scaling, offline decay.
sidebar:
  label: Bank Interest
  order: 1
---

## Summary

The Bank of ASEAN pays hourly interest on all checking accounts. The rate depends on whether the account holder is online, their balance size, and how long they've been offline.

## 1. Base Rate

The base interest rate is 2.2% per hour. Online players receive a 2× multiplier, doubling their effective rate to 4.4%.

_Interest Rate Parameters_

| Parameter | Value |
|---|---|
| Base hourly rate | 2.2% |
| Online multiplier | 2.0× |
| Effective online rate | 4.4% |


## 2. Balance Scaling

For accounts above $10,000,000, interest is scaled down exponentially:

_Effective interest by balance (online)_

| Balance | Scale Factor | Effective Hourly Rate |
|---|---|---|
| $1,000,000 | 100% | 4.40% |
| $10,000,000 | 100% | 4.40% |
| $30,000,000 | 60.65% | 2.67% |
| $50,000,000 | 36.79% | 1.62% |
| $100,000,000 | 10.54% | 0.46% |
| $170,000,000 | 1.83% | 0.08% |


## 3. Offline Decay

When a player goes offline, their interest rate decays over time using the same log-plateau formula as the wealth tax (with k=2.0). The longer they're offline, the less interest they earn — eventually approaching zero.

See Fiscal Policy: Bank Interest for the complete formula and projection tables.