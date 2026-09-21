---
title: Delivery Jobs
description: How government delivery jobs are posted, scaled, and funded.
sidebar:
  label: Delivery Jobs
  order: 1
---

## Summary

The government posts delivery contracts that reward players for moving cargo between delivery points. Jobs are posted automatically using an adaptive system that responds to player activity and treasury health.

## 1. How Jobs Work

Delivery jobs are created from templates — predefined contracts specifying cargo type, source/destination points, quantity, and base bonus. The system automatically selects templates and posts them as active jobs, considering:

- Current number of active jobs vs available slots

- Supply chain event conflicts (jobs won't compete with active events)

- Source storage availability (enough cargo at the pickup point)

- Destination capacity (room at the delivery point)

## 2. Adaptive Posting

The number of job slots scales dynamically based on:

_Job Slot Calculation_

| Factor | Method |
|---|---|
| Player count | log₂(1 + players) base curve |
| Success rate (24h) | Adaptive multiplier (0.5× – 2.0×) |
| Treasury health | Sigmoid multiplier (0× – 2.0×) |


## 3. Completion Bonuses

Each job has a completion bonus distributed proportionally to all contributors based on their delivery quantity. Bonuses are influenced by:

- Treasury multiplier — higher treasury means higher bonuses (0.5× – 2.0× range)

- Random variance — ±30% randomisation on each posting

- Template base — each template defines a base bonus amount

## 4. Government Funding

Job bonuses are funded through two mechanisms:

| Mechanism | Description |
|---|---|
| Ministry Budget | When a Minister is in office, bonuses are escrowed from the Ministry's allocated budget. If the budget runs out, no new Ministry-funded jobs are posted. |
| Treasury Direct | During a "government shutdown" (no active Minister), jobs are funded directly from the Treasury Fund with a 50% penalty on expiration. |


## 5. Job Expiration

When a job expires without being completed:

- Ministry-funded jobs: escrowed funds are returned to the Ministry budget

- Treasury-funded jobs: a 50% penalty of the completion bonus is deducted from the Treasury

- The template's success score decays by 30%, making it less likely to be posted again soon