<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import Header from '$lib/components/Header.svelte';
	import PiPPlayer from '$lib/components/PiPPlayer.svelte';
	import { authenticateWithDiscord, isInDiscordActivity, layoutMode, subscribeToLayoutMode } from '$lib/discord';
	import { setAccessToken, setApiBase } from '$lib/api';
	import { authStore } from '$lib/stores/auth';

	let { children } = $props();

	let streamUrl = $state('/stream');

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

	let auth = $state({ loading: true, authenticated: false, user: null as any, error: null as string | null });
	authStore.subscribe(v => { auth = v; });

	let currentLayout = $state(0);
	layoutMode.subscribe(v => { currentLayout = v; });

	let isPiP = $derived(currentLayout === 1);
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
	<audio class="persistent-audio" src={streamUrl} preload="none" controls>
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
</style>
