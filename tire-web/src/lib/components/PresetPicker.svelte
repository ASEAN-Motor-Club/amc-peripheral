<script lang="ts">
	import { PRESETS, type Preset } from '$lib/presets';
	import type { TirePhysics } from '$lib/types';

	interface Props {
		onApply: (preset: Preset) => void;
	}

	let { onApply }: Props = $props();

	let activeKey = $state<string | null>(null);

	function apply(key: string, preset: Preset) {
		activeKey = key;
		onApply(preset);
		// Flash effect
		setTimeout(() => { activeKey = null; }, 400);
	}
</script>

<div class="preset-picker">
	<span class="label text-sm">Quick Presets</span>
	<div class="presets">
		{#each Object.entries(PRESETS) as [key, preset]}
			<button
				class="preset-btn"
				class:flash={activeKey === key}
				onclick={() => apply(key, preset)}
				title={preset.desc}
			>
				<span class="preset-icon">{preset.icon}</span>
				<span class="preset-label">{preset.label}</span>
			</button>
		{/each}
	</div>
</div>

<style>
	.preset-picker {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}
	.label {
		color: var(--text-muted);
		font-weight: 500;
	}
	.presets {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-2);
	}
	.preset-btn {
		display: flex;
		align-items: center;
		gap: var(--sp-1);
		padding: var(--sp-1) var(--sp-3);
		background: var(--bg-elevated);
		border: 1px solid var(--border-default);
		border-radius: var(--r-full);
		color: var(--text-secondary);
		font-size: 0.8125rem;
		cursor: pointer;
		transition: all var(--t-fast);
		user-select: none;
	}
	.preset-btn:hover {
		border-color: var(--border-accent);
		background: var(--accent-subtle);
		color: var(--accent);
	}
	.preset-btn.flash {
		border-color: var(--accent);
		background: var(--accent-glow);
		color: var(--accent);
		box-shadow: var(--shadow-glow);
	}
	.preset-icon {
		font-size: 1rem;
	}
	.preset-label {
		font-weight: 500;
	}
</style>
