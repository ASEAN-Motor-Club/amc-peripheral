---
title: Government Employee Programme
description: Contribution-based levels, income redirection, salary multiplier, and the GOV tag.
sidebar:
  label: Government Employees
  order: 2
---

## Summary

Government employees are citizens who voluntarily redirect their earnings to the Treasury. In return, they receive double UBI, a visible rank in their name tag, and progressive level advancement.

## 1. How It Works

When activated, a government employee's income from deliveries, job completions, and other activities is redirected to the Treasury Fund. The employee receives no direct payment — instead, the contribution is logged for level progression.

## 2. Activation & Duration

Government employee status lasts for 24 hours per activation. When the role is active:

- The player's name is prefixed with [GOV#] where # is their level

- All earnings are redirected to the Treasury

- UBI is doubled (active: $36K/h, AFK: $12K/h)

After 24 hours, the role expires automatically and the player reverts to normal citizen status.

## 3. Financial Mechanics

Government employee earnings follow a three-track system based on income source:

_Income handling by source_

| Income Source | Wallet | Treasury | Level Progression |
|---|---|---|---|
| Base delivery earnings | Confiscated | Redirected | ✓ Counts |
| Contract completion bonus | Confiscated | Burned | ✗ Excluded |
| Subsidy (depot restock, etc.) | Confiscated | No effect | ✓ Counts |


Subsidy treatment: When a gov employee earns a subsidy (e.g. from a depot restock), the subsidy is briefly deposited then immediately confiscated. However, since the subsidy came from the Treasury, no money is sent back — it would be circular. Instead, the subsidy value counts toward the employee's level progression as a "contribution credit".

## 4. Levels & Progression

Government employee levels are based on cumulative contributions to the treasury:

_Level Progression_

| Level | Cumulative Contributions | Tag |
|---|---|---|
| 1 | $0 – $499,999 | [GOV1] |
| 2 | $500,000 – $999,999 | [GOV2] |
| 5 | $2,000,000 – $2,499,999 | [GOV5] |
| 10 | $4,500,000 – $4,999,999 | [GOV10] |
| ∞ | No cap — levels scale infinitely | [GOVn] |


## 5. The GOV Tag

The [GOV#] tag is a protected name prefix. Only active government employees may display it. The server automatically:

- Adds the tag when the role is activated

- Removes the tag when the role expires

- Warns players who attempt to use the tag without authorisation