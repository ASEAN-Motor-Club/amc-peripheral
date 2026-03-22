<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import Header from '$lib/components/Header.svelte';
	import { authenticateWithDiscord, isInDiscordActivity } from '$lib/discord';
	import { setAccessToken, setApiBase } from '$lib/api';
	import { authStore } from '$lib/stores/auth';

	let { children } = $props();

	onMount(async () => {
		if (isInDiscordActivity()) {
			// Inside Discord Activity — use proxy path for API
			setApiBase('/.proxy/radio-api/api');
			try {
				const auth = await authenticateWithDiscord();
				setAccessToken(auth.access_token);
				authStore.set({
					loading: false,
					authenticated: true,
					user: auth.user,
					error: null,
				});
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
</script>

<div class="app-shell">
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

<style>
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
</style>
