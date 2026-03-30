<script lang="ts">
	import { handlingScore } from '$lib/presets';

	interface Props {
		staticMu: number;
		slidingMu: number;
	}

	let { staticMu, slidingMu }: Props = $props();

	let score = $derived(handlingScore(staticMu, slidingMu));
	let position = $derived(score * 100);

	let character = $derived.by(() => {
		if (score < 0.25) return { label: 'Drifty', color: 'var(--cyan)' };
		if (score < 0.45) return { label: 'Loose', color: 'var(--cyan)' };
		if (score < 0.55) return { label: 'Balanced', color: 'var(--yellow)' };
		if (score < 0.75) return { label: 'Grippy', color: 'var(--accent)' };
		return { label: 'Glued', color: 'var(--red)' };
	});
</script>

<div class="gauge">
	<div class="gauge-header">
		<span class="gauge-title text-sm">Handling</span>
		<span class="gauge-character text-sm" style="color: {character.color}">{character.label}</span>
	</div>

	<div class="gauge-track">
		<div class="gauge-gradient"></div>
		<div class="gauge-marker" style="left: {position}%">
			<div class="gauge-dot" style="background: {character.color}"></div>
		</div>
	</div>

	<div class="gauge-labels">
		<span class="text-xs">💨 Drift</span>
		<span class="text-xs">⚖️ Balanced</span>
		<span class="text-xs">✊ Glued</span>
	</div>
</div>

<style>
	.gauge {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}
	.gauge-header {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
	}
	.gauge-title {
		color: var(--text-muted);
		font-weight: 500;
	}
	.gauge-character {
		font-weight: 700;
		transition: color var(--t-normal);
	}
	.gauge-track {
		position: relative;
		height: 8px;
		border-radius: var(--r-full);
		overflow: visible;
	}
	.gauge-gradient {
		width: 100%;
		height: 100%;
		border-radius: var(--r-full);
		background: linear-gradient(
			to right,
			var(--cyan) 0%,
			var(--yellow) 50%,
			var(--accent) 75%,
			var(--red) 100%
		);
		opacity: 0.6;
	}
	.gauge-marker {
		position: absolute;
		top: 50%;
		transform: translate(-50%, -50%);
		transition: left 0.5s cubic-bezier(0.16, 1, 0.3, 1);
	}
	.gauge-dot {
		width: 16px;
		height: 16px;
		border-radius: 50%;
		border: 2px solid var(--bg-primary);
		box-shadow: 0 0 8px rgba(0, 0, 0, 0.5);
		transition: background var(--t-normal);
	}
	.gauge-labels {
		display: flex;
		justify-content: space-between;
		color: var(--text-muted);
	}
</style>
