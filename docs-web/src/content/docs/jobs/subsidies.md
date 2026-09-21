---
title: Subsidies
description: Cargo, wrecker and passenger subsidies, and treasury cap logic.
sidebar:
  label: Subsidies
  order: 2
---

## Summary

The government provides subsidies to incentivise specific economic activities. Subsidies are funded from the Treasury Fund and scale with treasury health.

## 1. Cargo Subsidies

Cargo subsidies are configured through Subsidy Rules — each rule defines:

- Cargo filter — which cargo types qualify (or "any cargo" for universal rules)

- Source/destination filters — specific areas or delivery points

- Reward type — percentage of payment or flat amount

- On-time requirement — some subsidies require timely delivery

- Priority — when multiple rules match, the highest priority wins

## 2. Wrecker Subsidies

Tow truck operators receive subsidies for providing roadside assistance:

_Wrecker Subsidy Rates_

| Scenario | Base Bonus | Payment Bonus |
|---|---|---|
| Flipped Vehicle | $2,000 | 100% of payment |
| Other Tow Requests | $2,000 | 50% of payment |


Additionally, tow requests include a body damage bonus of up to 55% of base payment. Keeping the towed vehicle's body intact earns the maximum bonus.

## 3. Passenger Subsidies

Passenger transport services receive the following subsidies:

_Passenger Subsidy Rates_

| Service | Base Bonus | Payment Bonus |
|---|---|---|
| Taxi | $2,000 | 50% of payment |
| Ambulance | $2,000 | 50% of payment |


## 4. Treasury Cap

All subsidies are subject to a treasury health check:

When the treasury contains $50M or more, subsidies are paid in full. Below that, they scale linearly down to zero.