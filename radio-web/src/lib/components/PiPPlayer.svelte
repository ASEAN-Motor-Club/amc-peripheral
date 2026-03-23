<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getNowPlaying, likeSong, skipTrack, type NowPlaying } from '$lib/api';
	import { nowPlaying } from '$lib/stores/radio';
	import { authStore } from '$lib/stores/auth';

	let { isDj = false } = $props();

	let current: NowPlaying = $state({ playing: false });
	let pollTimer: ReturnType<typeof setInterval> | null = null;
	let liking = $state(false);
	let skipping = $state(false);
	let liked = $state(false);

	async function poll() {
		try {
			const data = await getNowPlaying();
			current = data;
			nowPlaying.set(data);
		} catch {
			// Silently continue polling
		}
	}

	async function handleLike() {
		if (liking || liked) return;
		liking = true;
		try {
			await likeSong();
			liked = true;
			setTimeout(() => { liked = false; }, 3000);
		} catch { /* ignore */ }
		liking = false;
	}

	async function handleSkip() {
		if (skipping) return;
		skipping = true;
		try {
			await skipTrack();
			setTimeout(poll, 2000);
		} catch { /* ignore */ }
		skipping = false;
	}

	onMount(() => {
		poll();
		pollTimer = setInterval(poll, 10000);
	});

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
	});

	const eqBars = [0, 0.12, 0.05, 0.18, 0.08];
</script>

<div class="pip-player">
	<div class="pip-left">
		<div class="pip-live">
			<span class="pip-live-dot"></span>
			LIVE
		</div>
		<div class="pip-eq">
			{#each eqBars as delay}
				<div
					class="pip-eq-bar"
					class:pip-eq-paused={!current.playing}
					style="animation-delay: {delay}s; animation-duration: {0.5 + delay * 2}s"
				></div>
			{/each}
		</div>
	</div>

	<div class="pip-center">
		{#if current.playing}
			<div class="pip-title">{current.song_title}</div>
			<div class="pip-requester">{current.requester ?? 'DJ Annie'}</div>
		{:else}
			<div class="pip-title pip-title-off">Radio ASEAN</div>
			<div class="pip-requester">Standby</div>
		{/if}
	</div>

	<div class="pip-actions">
		<button
			class="pip-btn pip-btn-like"
			class:pip-btn-active={liked}
			onclick={handleLike}
			disabled={liking || !current.playing}
			title="Like"
		>
			{liked ? '❤️' : '🤍'}
		</button>
		{#if isDj}
			<button
				class="pip-btn pip-btn-skip"
				onclick={handleSkip}
				disabled={skipping || !current.playing}
				title="Skip"
			>
				⏭
			</button>
		{/if}
	</div>
</div>

<style>
	.pip-player {
		display: flex;
		align-items: center;
		gap: var(--space-lg);
		padding: var(--space-lg) var(--space-xl);
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		height: 100%;
		box-sizing: border-box;
		overflow: hidden;
	}

	.pip-left {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-sm);
		flex-shrink: 0;
	}

	.pip-live {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: 0.625rem;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--led-red);
		font-family: var(--font-mono);
	}

	.pip-live-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--led-red);
		animation: pip-pulse 1.5s ease-in-out infinite;
	}

	@keyframes pip-pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.3; }
	}

	.pip-eq {
		display: flex;
		align-items: flex-end;
		gap: 2px;
		height: 28px;
	}

	.pip-eq-bar {
		width: 3px;
		background: var(--accent-primary);
		border-radius: 1px;
		animation: pip-eq-bounce 0.6s ease-in-out infinite alternate;
	}

	.pip-eq-paused {
		animation: none;
		height: 4px;
		opacity: 0.3;
	}

	@keyframes pip-eq-bounce {
		0% { height: 4px; }
		100% { height: 24px; }
	}

	.pip-center {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.pip-title {
		font-family: var(--font-mono);
		font-size: 0.8125rem;
		font-weight: 600;
		color: var(--text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.pip-title-off {
		color: var(--text-muted);
	}

	.pip-requester {
		font-size: 0.6875rem;
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.pip-actions {
		display: flex;
		gap: var(--space-sm);
		flex-shrink: 0;
	}

	.pip-btn {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		border: 1px solid var(--border-default);
		background: var(--bg-tertiary);
		display: flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		font-size: 0.75rem;
		transition: background 0.15s, border-color 0.15s;
		padding: 0;
	}

	.pip-btn:hover:not(:disabled) {
		background: var(--bg-elevated);
		border-color: var(--accent-primary);
	}

	.pip-btn:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}

	.pip-btn-active {
		border-color: var(--accent-primary);
		background: var(--bg-elevated);
	}

	.pip-audio {
		position: absolute;
		bottom: 4px;
		left: var(--space-xl);
		right: var(--space-xl);
		height: 28px;
		width: calc(100% - var(--space-xl) * 2);
		border-radius: var(--radius-sm);
		outline: none;
		opacity: 0.7;
	}

	.pip-audio::-webkit-media-controls-panel {
		background: var(--bg-tertiary);
	}
</style>
