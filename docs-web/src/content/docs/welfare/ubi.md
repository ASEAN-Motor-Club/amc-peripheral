---
title: Universal Basic Income
description: UBI rates, driver level scaling, eligibility and loan auto-repayment.
sidebar:
  label: Universal Basic Income
  order: 1
---

## Summary

Every eligible online citizen receives a regular income payment from the government. The amount depends on activity level, driver level, and government employment status.

## 1. Payment Rates

UBI is distributed every 20 minutes to all eligible online players. The table below shows the equivalent hourly rate (paid in 3 instalments):

_UBI Payment Schedule_

| Status | Per Payment | Hourly Total | Note |
|---|---|---|---|
| Active player | $6,000 | $18,000 | Currently driving or doing activities |
| AFK player | $2,000 | $6,000 | Online but idle |
| Government employee (active) | $12,000 | $36,000 | 2× standard rate; logged as Government Salary |
| Government employee (AFK) | $4,000 | $12,000 | 2× AFK rate; logged as Government Salary |


## 2. Eligibility

To receive UBI a citizen must:

- Have a driver level of 1 or above — level 0 players are excluded.

- Not have opted out of UBI (reject_ubi flag).

## 3. Driver Level Scaling

UBI payments scale with the recipient's driver level up to a cap of level 400. The formula is:

## 4. Loan Auto-Repayment

If a UBI recipient has an outstanding loan at Bank of ASEAN, the lesser of the UBI payment or the remaining loan balance is automatically deducted as repayment before the remainder is deposited.

## 5. Distribution Frequency

UBI runs as a scheduled task every 20 minutes. The system checks all online players and distributes payments in bulk. Payments are logged as Universal Basic Income (or Government Salary for government employees) in the financial ledger.