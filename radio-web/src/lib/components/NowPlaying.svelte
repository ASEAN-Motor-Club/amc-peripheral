<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getNowPlaying, type NowPlaying } from '$lib/api';
	import { nowPlaying } from '$lib/stores/radio';

	let current: NowPlaying = $state({ playing: false });
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	async function poll() {
		try {
			const data = await getNowPlaying();
			current = data;
			nowPlaying.set(data);
		} catch {
			// Silently continue polling
		}
	}

	onMount(() => {
		poll();
		pollTimer = setInterval(poll, 10000);
	});

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
	});

	// VU meter bar delays for animation variety
	const vuBars = [0, 0.15, 0.05, 0.25, 0.1, 0.2, 0.08, 0.22, 0.12, 0.18, 0.03, 0.28];
</script>

<div class="now-playing panel">
	<div class="panel-header">
		<span class="led" class:led-on={current.playing} class:led-off={!current.playing}></span>
		ON AIR
	</div>
	<div class="panel-body np-content">
		{#if current.playing}
			<div class="np-visualizer">
				{#each vuBars as delay}
					<div
						class="vu-bar"
						style="animation-delay: {delay}s; animation-duration: {0.6 + Math.random() * 0.5}s"
					></div>
				{/each}
			</div>

			<div class="np-info">
				<div class="np-title font-mono">{current.song_title}</div>
				<div class="np-meta">
					<span class="np-requester">Requested by {current.requester}</span>
					{#if current.like_count && current.like_count > 0}
						<span class="badge">❤️ {current.like_count}</span>
					{/if}
				</div>
			</div>
		{:else}
			<div class="np-off">
				<div class="np-off-icon">📻</div>
				<div class="np-off-text">No song currently playing</div>
			</div>
		{/if}
	</div>
</div>

<style>
	.now-playing {
		background: linear-gradient(135deg, var(--bg-secondary) 0%, var(--bg-tertiary) 100%);
		border-color: var(--border-accent);
	}

	.np-content {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
		padding: var(--space-xl);
	}

	.np-visualizer {
		display: flex;
		align-items: flex-end;
		gap: 3px;
		height: 48px;
		padding: var(--space-sm) 0;
	}

	.np-info {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.np-title {
		font-size: 1.125rem;
		font-weight: 600;
		color: var(--text-primary);
		line-height: 1.3;
	}

	.np-meta {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		font-size: 0.8125rem;
		color: var(--text-secondary);
	}

	.np-requester {
		color: var(--text-muted);
	}

	.np-audio {
		width: 100%;
		height: 40px;
		border-radius: var(--radius-md);
		outline: none;
	}

	.np-audio::-webkit-media-controls-panel {
		background: var(--bg-elevated);
	}

	.np-off {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-md);
		padding: var(--space-2xl);
		color: var(--text-muted);
	}

	.np-off-icon {
		font-size: 2.5rem;
		opacity: 0.5;
	}

	.np-off-text {
		font-size: 0.875rem;
	}
</style>
