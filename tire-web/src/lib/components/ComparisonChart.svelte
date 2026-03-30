<script lang="ts">
	import { BASE_TIRES, type BaseTire } from '$lib/presets';

	interface Props {
		staticMu: number;
		slidingMu: number;
		offroadFriction: number | null;
	}

	let { staticMu, slidingMu, offroadFriction }: Props = $props();

	const MAX_MU = 3.0;

	interface ChartRow {
		label: string;
		value: number;
		color: string;
		maxValue: number;
	}

	// Build comparison rows: base tires + user's tire
	let rows = $derived.by(() => {
		const userRows: ChartRow[] = [
			{ label: 'Static Friction', value: staticMu, color: 'var(--accent)', maxValue: MAX_MU },
			{ label: 'Sliding Friction', value: slidingMu, color: 'var(--cyan)', maxValue: MAX_MU },
		];
		if (offroadFriction !== null) {
			userRows.push({
				label: 'Off-road',
				value: offroadFriction,
				color: 'var(--green)',
				maxValue: MAX_MU,
			});
		}
		return userRows;
	});

	// Show base game tires for comparison
	let comparisonTires = $derived.by(() => {
		return BASE_TIRES.map((t) => ({
			name: t.label,
			staticMu: t.staticMu,
			slidingMu: t.slidingMu,
			offroad: t.offroad,
		}));
	});

	function barWidth(value: number): string {
		return `${(value / MAX_MU) * 100}%`;
	}
</script>

<div class="chart">
	<div class="chart-section">
		<h4 class="chart-title">Your Tire</h4>
		{#each rows as row}
			<div class="chart-row">
				<span class="chart-label text-sm">{row.label}</span>
				<div class="chart-bar-track">
					<div
						class="chart-bar"
						style="width: {barWidth(row.value)}; background: {row.color}"
					></div>
				</div>
				<span class="chart-value text-sm" style="color: {row.color}">{row.value.toFixed(2)}</span>
			</div>
		{/each}
	</div>

	<div class="chart-divider"></div>

	<div class="chart-section">
		<h4 class="chart-title">Base Game</h4>
		{#each comparisonTires as tire}
			<div class="chart-row-group">
				<span class="chart-tire-name text-xs">{tire.name}</span>
				<div class="chart-row mini">
					<div class="chart-bar-track mini">
						<div
							class="chart-bar"
							style="width: {barWidth(tire.staticMu)}; background: var(--accent); opacity: 0.5"
						></div>
					</div>
					<div class="chart-bar-track mini">
						<div
							class="chart-bar"
							style="width: {barWidth(tire.slidingMu)}; background: var(--cyan); opacity: 0.5"
						></div>
					</div>
					{#if tire.offroad}
						<div class="chart-bar-track mini">
							<div
								class="chart-bar"
								style="width: {barWidth(tire.offroad)}; background: var(--green); opacity: 0.5"
							></div>
						</div>
					{/if}
				</div>
			</div>
		{/each}
	</div>
</div>

<style>
	.chart {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
	}
	.chart-section {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}
	.chart-title {
		font-size: 0.6875rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-muted);
	}
	.chart-row {
		display: grid;
		grid-template-columns: 110px 1fr 44px;
		align-items: center;
		gap: var(--sp-2);
	}
	.chart-label {
		color: var(--text-secondary);
		white-space: nowrap;
	}
	.chart-value {
		text-align: right;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.chart-bar-track {
		height: 8px;
		background: var(--bg-hover);
		border-radius: var(--r-full);
		overflow: hidden;
	}
	.chart-bar-track.mini {
		height: 4px;
	}
	.chart-bar {
		height: 100%;
		border-radius: var(--r-full);
		transition: width 0.5s cubic-bezier(0.16, 1, 0.3, 1);
	}
	.chart-divider {
		height: 1px;
		background: var(--border-subtle);
	}
	.chart-row-group {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.chart-tire-name {
		color: var(--text-muted);
	}
	.chart-row.mini {
		display: flex;
		gap: var(--sp-1);
	}
</style>
