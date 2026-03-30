<script lang="ts">
	interface Props {
		label: string;
		value: number;
		min: number;
		max: number;
		step: number;
		hint?: string;
		disabled?: boolean;
	}

	let { label, value = $bindable(), min, max, step, hint = '', disabled = false }: Props = $props();

	let displayValue = $derived(value.toFixed(2));

	// Compute gradient position for the track fill
	let fillPercent = $derived(((value - min) / (max - min)) * 100);

	// Color based on value intensity: low=green, mid=yellow, high=red
	function intensityColor(pct: number): string {
		if (pct < 33) return '#3ecf5a';
		if (pct < 66) return '#e8c020';
		return '#e89020';
	}

	let trackColor = $derived(intensityColor(fillPercent));
</script>

<div class="slider-group" class:disabled>
	<div class="slider-header">
		<label class="slider-label">{label}</label>
		<span class="slider-value" style="color: {trackColor}">{displayValue}</span>
	</div>

	{#if hint}
		<p class="slider-hint">{hint}</p>
	{/if}

	<div class="slider-track-wrapper">
		<input
			type="range"
			bind:value
			{min}
			{max}
			{step}
			{disabled}
			style="background: linear-gradient(to right, {trackColor} 0%, {trackColor} {fillPercent}%, var(--bg-hover) {fillPercent}%, var(--bg-hover) 100%)"
		/>
		<div class="slider-range">
			<span class="text-xs" style="color: var(--text-muted)">{min}</span>
			<span class="text-xs" style="color: var(--text-muted)">{max}</span>
		</div>
	</div>
</div>

<style>
	.slider-group {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}
	.slider-group.disabled {
		opacity: 0.4;
		pointer-events: none;
	}
	.slider-header {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
	}
	.slider-label {
		font-size: 0.8125rem;
		font-weight: 500;
		color: var(--text-secondary);
	}
	.slider-value {
		font-size: 1.125rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		transition: color var(--t-fast);
	}
	.slider-hint {
		font-size: 0.6875rem;
		color: var(--text-muted);
		margin-bottom: var(--sp-1);
	}
	.slider-track-wrapper {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.slider-range {
		display: flex;
		justify-content: space-between;
	}
</style>
