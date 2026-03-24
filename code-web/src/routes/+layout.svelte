<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { isInDiscordActivity, initDiscordSdk } from '$lib/discord';

	let { children } = $props();

	let state = $state<'loading' | 'ready' | 'error'>('loading');
	let errorMsg = $state('');

	/** URL for the inner iframe pointing at the real OpenCode web UI */
	let codeUiUrl = $state('/opencode/');

	onMount(async () => {
		if (isInDiscordActivity()) {
			// Inside Discord Activity — use the proxy path for OpenCode UI
			codeUiUrl = '/.proxy/code-ui/';
			try {
				await initDiscordSdk();
				state = 'ready';
			} catch (err: any) {
				console.error('[Code] SDK init error:', err);
				errorMsg = err?.message || 'Failed to initialize Discord Activity';
				state = 'error';
			}
		} else {
			// Running outside Discord (dev mode) — show iframe directly
			state = 'ready';
		}
	});
</script>

<svelte:head>
	<title>AMC Code — OpenCode</title>
</svelte:head>

{#if state === 'loading'}
	<div class="loading-screen">
		<div class="spinner"></div>
		<p>Connecting to Discord...</p>
	</div>
{:else if state === 'error'}
	<div class="loading-screen">
		<p class="error">⚠️ {errorMsg}</p>
		<p>Open this as a Discord Activity</p>
	</div>
{:else}
	<iframe
		class="code-frame"
		src={codeUiUrl}
		title="OpenCode Web UI"
		allow="clipboard-read; clipboard-write"
	></iframe>
{/if}

<!-- Required by SvelteKit — children are empty since the iframe is the UI -->
<div style="display:none">{@render children()}</div>
