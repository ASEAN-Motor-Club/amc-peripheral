---
title: Supply Chain Events
description: Community-wide delivery challenges with objectives and proportional rewards.
sidebar:
  label: Supply Chain Events
  order: 3
---

## Summary

Supply chain events are time-limited community challenges that incentivise large-scale cargo movement. Players earn rewards proportional to their contribution.

## 1. Event Lifecycle

Each supply chain event follows this lifecycle:

- Created from template — defines objectives, duration, and reward per item

- Active period — players contribute deliveries that match event objectives

- Ends — when the time expires or all objectives reach their ceiling

- Rewards distributed — proportional payouts based on individual contributions

## 2. Objectives

Each event contains one or more objectives with:

| Property | Description |
|---|---|
| Cargo filter | Which cargo types count towards this objective |
| Destination/source points | Specific delivery points that qualify |
| Ceiling | Maximum quantity — contributions beyond this aren't rewarded |
| Reward weight | Share of the total reward pool allocated to this objective |
| Primary flag | The primary objective determines the total reward pool size |


## 3. Reward Distribution

The total reward pool is calculated as:

This pool is split across objectives by their reward weight, then distributed proportionally to each contributor based on their share of deliveries within that objective.

## 4. Job Suppression

During active supply chain events, the job posting system automatically suppresses any delivery job templates that would conflict with the event's cargo/destination objectives. This prevents competition between regular jobs and event objectives.