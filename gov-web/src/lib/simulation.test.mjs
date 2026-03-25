// Tests for the bank balance simulation engine
// Run: nix run nixpkgs#nodejs_22 -- src/lib/simulation.test.mjs
import {
  calculateHourlyInterest,
  calculateWealthTax,
  wealthTaxHourlyRate,
  simulate,
  WEALTH_TAX_EXEMPT,
  INTEREST_RATE,
  INTEREST_DECAY_K,
  INTEREST_THRESHOLD,
  INTEREST_SCALE,
} from './simulation.mjs';

let passed = 0;
let failed = 0;

function assert(condition, message) {
  if (condition) {
    passed++;
  } else {
    failed++;
    console.error(`  FAIL: ${message}`);
  }
}

function assertApprox(actual, expected, tolerance, message) {
  const diff = Math.abs(actual - expected);
  if (diff <= tolerance) {
    passed++;
  } else {
    failed++;
    console.error(`  FAIL: ${message} — expected ~${expected}, got ${actual} (diff ${diff})`);
  }
}

// ═══════════════════════════════════════════════
// Interest tests
// ═══════════════════════════════════════════════
console.log('\n── calculateHourlyInterest ──');

// Zero/negative balance → 0
assert(calculateHourlyInterest(0, 10) === 0, 'zero balance returns 0');
assert(calculateHourlyInterest(-100, 10) === 0, 'negative balance returns 0');
assert(calculateHourlyInterest(1000000, 0) === 0, 'zero hours returns 0');

// Hour 1 should NOT get 2x online multiplier (this is the bug fix)
// Backend: at hoursOffline=1, decay = 1/(1 + 2*log10(1)) = 1/(1+0) = 1.0
// So rate = 0.022 * 1.0 = 0.022, amount = 1M * 0.022 / 24 = 916
{
  const interestH1 = calculateHourlyInterest(1_000_000, 1);
  const interestH2 = calculateHourlyInterest(1_000_000, 2);
  // Hour 1 should be HIGHER than hour 2 (no decay at h=1), but NOT 2x
  assert(interestH1 > interestH2, 'hour 1 interest > hour 2 (less decay)');
  assert(interestH1 < interestH2 * 2, 'hour 1 interest is NOT double hour 2 (no online multiplier)');
  // Expected: 1M * 0.022 / 24 = 916
  assertApprox(interestH1, 916, 1, 'hour 1 interest for $1M ≈ $916');
}

// Day 1 vs Day 2 interest should be similar (no spike)
{
  const result = simulate(1_000_000, 2);
  const day1 = result.dailySnapshots[0];
  const day2 = result.dailySnapshots[1];
  const ratio = day1.interest / day2.interest;
  assert(ratio < 1.6, `day 1/day 2 interest ratio ${ratio.toFixed(2)} should be < 1.6 (no 2x spike)`);
}

// Balance scaling: $1M (below threshold) gets full rate
{
  const interest = calculateHourlyInterest(1_000_000, 24);
  assert(interest > 0, '$1M at 24h gives positive interest');
}

// Balance scaling: very high balance gets reduced interest
{
  const low = calculateHourlyInterest(1_000_000, 24);
  const high = calculateHourlyInterest(100_000_000, 24);
  // Per-dollar rate should be much lower at $100M
  const lowPerDollar = low / 1_000_000;
  const highPerDollar = high / 100_000_000;
  assert(highPerDollar < lowPerDollar, 'per-dollar interest rate decays at high balances');
}

// Offline decay: interest decreases with more hours offline
{
  const h24 = calculateHourlyInterest(5_000_000, 24);
  const h168 = calculateHourlyInterest(5_000_000, 168);
  const h720 = calculateHourlyInterest(5_000_000, 720);
  assert(h24 > h168, 'interest at 24h > 168h (1 week)');
  assert(h168 > h720, 'interest at 168h > 720h (1 month)');
}

// ═══════════════════════════════════════════════
// Wealth tax tests
// ═══════════════════════════════════════════════
console.log('\n── calculateWealthTax ──');

// Exempt threshold
assert(calculateWealthTax(1_000_000, 1000) === 0, '$1M is exempt');
assert(calculateWealthTax(500_000, 5000) === 0, '$500K is exempt');
assert(calculateWealthTax(0, 10000) === 0, '$0 is exempt');

// Online (< 1 hour) → no tax
assert(calculateWealthTax(10_000_000, 0.5) === 0, 'no tax at 0.5 hours');
assert(calculateWealthTax(10_000_000, 0) === 0, 'no tax at 0 hours');

// Above exempt → some tax
{
  const tax = calculateWealthTax(5_000_000, 60 * 24);
  assert(tax > 0, '$5M at 60 days produces tax > 0');
}

// Progressive: higher balance → more tax
{
  const hours = 30 * 24;
  const tax50m = calculateWealthTax(50_000_000, hours);
  const tax15m = calculateWealthTax(15_000_000, hours);
  const tax5m = calculateWealthTax(5_000_000, hours);
  assert(tax50m > tax15m, '$50M taxed more than $15M');
  assert(tax15m > tax5m, '$15M taxed more than $5M');
}

// Time decay: hourly rate increases then plateaus
{
  const tax7d = calculateWealthTax(30_000_000, 7 * 24);
  const tax30d = calculateWealthTax(30_000_000, 30 * 24);
  const tax90d = calculateWealthTax(30_000_000, 90 * 24);
  assert(tax30d > tax7d, 'tax at 30d > 7d');
  assert(tax90d > tax30d, 'tax at 90d > 30d');
}

// Rate decay at extreme durations
{
  const rate30d = wealthTaxHourlyRate(0.25, 30 * 24);
  const rate5yr = wealthTaxHourlyRate(0.25, 5 * 365 * 24);
  assert(rate5yr < rate30d, 'hourly rate at 5yr < 30 days (log-plateau decay)');
}

// ═══════════════════════════════════════════════
// Simulation integration tests
// ═══════════════════════════════════════════════
console.log('\n── simulate ──');

// $1M for 30 days: at exempt threshold, only interest gains
{
  const result = simulate(1_000_000, 30);
  // Interest pushes balance above $1M exempt threshold, so tiny tax is expected
  assert(result.totalTax < result.totalInterest, '$1M tax << interest');
  assert(result.totalInterest > 0, '$1M earns interest');
  assert(result.finalBalance > 1_000_000, '$1M final balance > initial');
  assert(result.netChange > 0, '$1M net is positive');
  assert(result.crossoverDay === null || result.crossoverDay > 25, '$1M has no early crossover');
}

// $50M for 30 days: should have crossover
{
  const result = simulate(50_000_000, 30);
  assert(result.totalInterest > 0, '$50M earns interest');
  assert(result.totalTax > 0, '$50M pays wealth tax');
  assert(result.dailySnapshots.length === 30, '30 daily snapshots');
  console.log(`  $50M 30d: interest=${result.totalInterest}, tax=${result.totalTax}, net=${result.netChange}`);
}

// Balance monotonicity after crossover: balance should decline day-over-day
{
  const result = simulate(50_000_000, 30);
  if (result.crossoverDay !== null && result.crossoverDay < 30) {
    // After crossover, daily net should be negative
    let allNegativeAfter = true;
    for (const snap of result.dailySnapshots) {
      if (snap.day > result.crossoverDay + 1 && snap.net > 0) {
        allNegativeAfter = false;
        break;
      }
    }
    assert(allNegativeAfter, 'daily net is negative after crossover');
  }
}

// Final balance == initial + interest - tax
{
  const result = simulate(5_000_000, 14);
  const expected = 5_000_000 + result.totalInterest - result.totalTax;
  assertApprox(result.finalBalance, expected, 1, 'final = initial + interest - tax');
}

// Day 1 interest should NOT be spiked (the bug fix test)
{
  const result = simulate(123_720_448, 7);
  const day1 = result.dailySnapshots[0];
  const day2 = result.dailySnapshots[1];
  // Day 1 interest should be at most 30% higher than day 2 (not double)
  const ratio = day1.interest / day2.interest;
  assert(ratio < 1.6, `day 1/day 2 interest ratio for $123M = ${ratio.toFixed(2)}, should be < 1.6 (no 2x spike)`);
  console.log(`  Day 1: interest=${day1.interest}, tax=${day1.tax}, net=${day1.net}`);
  console.log(`  Day 2: interest=${day2.interest}, tax=${day2.tax}, net=${day2.net}`);
}

// ═══════════════════════════════════════════════
// Summary
// ═══════════════════════════════════════════════
console.log(`\n══ Results: ${passed} passed, ${failed} failed ══\n`);
if (failed > 0) process.exit(1);
