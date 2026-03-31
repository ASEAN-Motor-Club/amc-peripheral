<script lang="ts">
	import '../app.css';
	import { onMount, onDestroy } from 'svelte';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import Header from '$lib/components/Header.svelte';
	import PiPPlayer from '$lib/components/PiPPlayer.svelte';
	import { authenticateWithDiscord, isInDiscordActivity, layoutMode, subscribeToLayoutMode } from '$lib/discord';
	import { setAccessToken, setApiBase } from '$lib/api';
	import { authStore } from '$lib/stores/auth';
	import { streamStatus } from '$lib/stores/radio';

	let { children } = $props();

	let streamUrl = $state('/stream');
	let audioEl: HTMLAudioElement | undefined = $state();

	// --- Auto-reconnect state ---
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let backoffMs = 2000;
	const MAX_BACKOFF_MS = 30_000;
	let wasPlaying = false; // track if user had started playback

	function scheduleReconnect() {
		if (reconnectTimer) return; // already scheduled
		streamStatus.set('reconnecting');
		console.warn(`[Radio] Stream lost — reconnecting in ${backoffMs / 1000}s...`);

		reconnectTimer = setTimeout(() => {
			reconnectTimer = null;
			reconnectStream();
		}, backoffMs);

		// Exponential backoff, capped
		backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS);
	}

	function reconnectStream() {
		if (!audioEl) return;
		// Append cache-buster so the browser doesn't serve a cached error
		const base = streamUrl.split('?')[0];
		const bustUrl = `${base}?_t=${Date.now()}`;
		console.log('[Radio] Attempting reconnect:', bustUrl);
		audioEl.src = bustUrl;
		audioEl.load();
		audioEl.play().catch(() => {
			// Autoplay may be blocked; schedule another retry
			scheduleReconnect();
		});
	}

	function resetBackoff() {
		backoffMs = 2000;
		streamStatus.set('connected');
		if (reconnectTimer) {
			clearTimeout(reconnectTimer);
			reconnectTimer = null;
		}
	}

	function handleAudioError() {
		// Only reconnect if user had started playback
		if (wasPlaying) {
			scheduleReconnect();
		}
	}

	function handleAudioStalled() {
		if (wasPlaying) {
			scheduleReconnect();
		}
	}

	function handleAudioEnded() {
		// Live streams shouldn't end — treat as disconnect
		if (wasPlaying) {
			scheduleReconnect();
		}
	}

	function handleAudioPlaying() {
		wasPlaying = true;
		resetBackoff();
	}

	function handleAudioPlay() {
		wasPlaying = true;
	}

	onMount(async () => {
		if (isInDiscordActivity()) {
			// Inside Discord Activity — use proxy path for API and stream
			setApiBase('/.proxy/radio-api/api');
			streamUrl = '/.proxy/radio-api/stream';
			try {
				const auth = await authenticateWithDiscord();
				setAccessToken(auth.access_token);
				authStore.set({
					loading: false,
					authenticated: true,
					user: auth.user,
					error: null,
				});
				// After auth, start listening for layout mode changes (full ↔ PiP)
				subscribeToLayoutMode();
			} catch (err: any) {
				console.error('[Radio] Auth error:', err);
				const errorMsg = err?.message || err?.code || (typeof err === 'string' ? err : JSON.stringify(err));
				authStore.set({
					loading: false,
					authenticated: false,
					user: null,
					error: errorMsg || 'Unknown authentication error',
				});
			}
		} else {
			// Running outside Discord (dev mode) — skip auth
			authStore.set({
				loading: false,
				authenticated: true,
				user: { id: 'dev', username: 'Developer', global_name: 'Developer', avatar: null },
				error: null,
			});
		}
	});

	onDestroy(() => {
		if (reconnectTimer) {
			clearTimeout(reconnectTimer);
			reconnectTimer = null;
		}
	});

	let auth = $state({ loading: true, authenticated: false, user: null as any, error: null as string | null });
	authStore.subscribe(v => { auth = v; });

	let currentLayout = $state(0);
	layoutMode.subscribe(v => { currentLayout = v; });

	let isPiP = $derived(currentLayout === 1);

	let currentStreamStatus = $state<'connected' | 'reconnecting' | 'error'>('connected');
	streamStatus.subscribe(v => { currentStreamStatus = v; });
</script>

<!--
  IMPORTANT: Both views are always mounted, toggled via CSS display.
  This keeps the <audio> element alive across layout mode switches
  so the stream doesn't restart when minimizing/expanding.
-->

<!-- PiP mode — compact radio player -->
<div class="pip-shell" class:hidden={!auth.authenticated || !isPiP}>
	<PiPPlayer isDj={false} />
</div>

<!-- Full mode — normal app shell -->
<div class="app-shell" class:hidden={auth.authenticated && isPiP}>
	<Sidebar />
	<div class="app-main">
		<Header />

		<!-- Stream reconnect banner -->
		{#if currentStreamStatus === 'reconnecting'}
			<div class="reconnect-banner">
				<div class="reconnect-spinner"></div>
				<span>Reconnecting to stream…</span>
			</div>
		{/if}

		<main class="app-content">
			{#if auth.loading}
				<div class="loading-screen">
					<div class="spinner" style="width: 32px; height: 32px;"></div>
					<p style="color: var(--text-muted); font-size: 0.875rem; margin-top: var(--space-lg);">
						Connecting to Discord...
					</p>
				</div>
			{:else if auth.error}
				<div class="loading-screen">
					<p style="color: var(--led-red); font-size: 0.875rem;">⚠️ {auth.error}</p>
					<p style="color: var(--text-muted); font-size: 0.8125rem; margin-top: var(--space-sm);">
						Open this as a Discord Activity to authenticate
					</p>
				</div>
			{:else}
				{@render children()}
			{/if}
		</main>
	</div>
</div>

<!-- Persistent audio player — lives at layout level, never destroyed -->
{#if auth.authenticated}
	<audio
		class="persistent-audio"
		bind:this={audioEl}
		src={streamUrl}
		preload="none"
		controls
		onerror={handleAudioError}
		onstalled={handleAudioStalled}
		onended={handleAudioEnded}
		onplaying={handleAudioPlaying}
		onplay={handleAudioPlay}
	>
		<track kind="captions" />
	</audio>
{/if}

<style>
	.hidden {
		display: none !important;
	}

	.pip-shell {
		height: 100dvh;
		width: 100vw;
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--bg-primary);
		padding: var(--space-md);
		box-sizing: border-box;
	}

	.app-shell {
		display: flex;
		height: 100dvh;
		width: 100vw;
		overflow: hidden;
	}

	.app-main {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.app-content {
		flex: 1;
		overflow-y: auto;
		padding: var(--space-xl);
	}

	.loading-screen {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
	}

	.persistent-audio {
		position: fixed;
		bottom: 8px;
		left: 50%;
		transform: translateX(-50%);
		width: min(90%, 400px);
		height: 36px;
		border-radius: var(--radius-md);
		outline: none;
		z-index: 1000;
		opacity: 0.85;
	}

	.persistent-audio::-webkit-media-controls-panel {
		background: var(--bg-elevated);
	}

	/* --- Reconnect banner --- */
	.reconnect-banner {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs) var(--space-xl);
		background: linear-gradient(90deg, rgba(255, 170, 0, 0.12), rgba(255, 170, 0, 0.04));
		border-bottom: 1px solid rgba(255, 170, 0, 0.25);
		color: #ffaa00;
		font-size: 0.75rem;
		font-family: var(--font-mono);
		letter-spacing: 0.02em;
		animation: reconnect-slide-in 0.25s ease-out;
	}

	@keyframes reconnect-slide-in {
		from {
			opacity: 0;
			transform: translateY(-100%);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	.reconnect-spinner {
		width: 12px;
		height: 12px;
		border: 2px solid rgba(255, 170, 0, 0.3);
		border-top-color: #ffaa00;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>

