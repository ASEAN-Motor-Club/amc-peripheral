// Bank balance simulation engine
// Ports exact formulas from amc_finance/services.py
// Used by both the calculator page and tests

// ── Constants (exact match of amc_finance/services.py) ──
export const INTEREST_RATE = 0.022;
export const INTEREST_DECAY_K = 2.0;
export const INTEREST_THRESHOLD = 10_000_000;
export const INTEREST_SCALE = 40_000_000;

export const WEALTH_TAX_EXEMPT = 1_000_000;
export const WEALTH_TAX_S = 2163;
export const WEALTH_TAX_BRACKETS = [
  [1_000_000,   20_000_000,   0.65],
  [20_000_000,  100_000_000,  1.05],
  [100_000_000, Infinity,     1.55],
];

// ── Port of calculate_hourly_interest (offline-only variant) ──
// The backend's ONLINE_INTEREST_MULTIPLIER (2x for hoursOffline <= 1) is
// deliberately excluded here — this calculator simulates offline players only.
export function calculateHourlyInterest(balance, hoursOffline) {
  if (balance <= 0 || hoursOffline <= 0) return 0;

  let rate = INTEREST_RATE;
  // Smooth logarithmic decay: rate × 1/(1 + k·log₁₀(hours))
  const decay = 1.0 / (1.0 + INTEREST_DECAY_K * Math.log10(hoursOffline));
  rate *= decay;

  // Balance-based fall-off: full interest up to threshold, then exp decay
  const excess = Math.max(0, balance - INTEREST_THRESHOLD);
  const balanceMultiplier = Math.exp(-excess / INTEREST_SCALE);

  const amount = (balance * rate * balanceMultiplier) / 24;
  return Math.max(Math.floor(amount), 0);
}

// ── Port of wealth_tax_hourly_rate ──
export function wealthTaxHourlyRate(k, tHours) {
  if (tHours <= 0) return 0;
  const x = 1 + tHours / WEALTH_TAX_S;
  return (k * Math.log(x)) / (WEALTH_TAX_S * x);
}

// ── Port of calculate_wealth_tax ──
export function calculateWealthTax(balance, hoursOffline) {
  if (balance <= WEALTH_TAX_EXEMPT || hoursOffline < 1) return 0;

  let tax = 0;
  let prev = WEALTH_TAX_EXEMPT;
  for (const [floor, ceiling, k] of WEALTH_TAX_BRACKETS) {
    if (balance <= prev) break;
    const taxable = Math.min(balance, ceiling) - prev;
    if (taxable > 0) {
      tax += taxable * wealthTaxHourlyRate(k, hoursOffline);
    }
    prev = ceiling;
  }
  return Math.max(Math.floor(tax), 0);
}

// ── Main simulation ──
export function simulate(initialBalance, days) {
  const totalHours = days * 24;
  let balance = initialBalance;
  let totalInterest = 0;
  let totalTax = 0;
  let crossoverDay = null;

  const dailySnapshots = [];
  let dayInterest = 0;
  let dayTax = 0;

  for (let h = 1; h <= totalHours; h++) {
    // Interest
    const interest = calculateHourlyInterest(balance, h);
    balance += interest;
    totalInterest += interest;
    dayInterest += interest;

    // Wealth tax — mirror backend guard: only tax if tax <= balance - exempt
    const tax = calculateWealthTax(balance, h);
    if (tax > 0 && tax <= balance - WEALTH_TAX_EXEMPT) {
      balance -= tax;
      totalTax += tax;
      dayTax += tax;
    }

    // Crossover detection: first hour where tax > interest
    if (crossoverDay === null && tax > interest && tax > 0) {
      crossoverDay = Math.ceil(h / 24);
    }

    // End of day snapshot
    if (h % 24 === 0) {
      const day = h / 24;
      dailySnapshots.push({
        day,
        balance: Math.round(balance),
        interest: dayInterest,
        tax: dayTax,
        net: dayInterest - dayTax,
      });
      dayInterest = 0;
      dayTax = 0;
    }
  }

  return {
    totalInterest,
    totalTax,
    finalBalance: Math.round(balance),
    netChange: totalInterest - totalTax,
    dailySnapshots,
    crossoverDay,
  };
}
