<script lang="ts">
	import '../app.css';

	let { children } = $props();
</script>

<div class="app">
	<header class="app-header">
		<div class="container flex items-center justify-between">
			<div class="flex items-center gap-3">
				<span class="logo">🏎️</span>
				<div class="flex-col">
					<h1 class="app-title">Tire Mod Creator</h1>
					<span class="app-subtitle text-xs">ASEAN Motor Club</span>
				</div>
			</div>
			<a
				href="https://aseanmotorclub.com"
				target="_blank"
				rel="noopener noreferrer"
				class="btn btn-ghost text-sm"
			>
				aseanmotorclub.com ↗
			</a>
		</div>
	</header>

	<main class="app-main">
		{@render children()}
	</main>

	<footer class="app-footer">
		<div class="container text-center">
			<p class="text-xs" style="color: var(--text-muted)">
				Motor Town modding tools by ASEAN Motor Club · Not affiliated with Zipline Games
			</p>
		</div>
	</footer>
</div>

<style>
	.app {
		display: flex;
		flex-direction: column;
		min-height: 100dvh;
	}
	.app-header {
		position: sticky;
		top: 0;
		z-index: 100;
		background: rgba(15, 16, 18, 0.85);
		backdrop-filter: blur(16px);
		-webkit-backdrop-filter: blur(16px);
		border-bottom: 1px solid var(--border-subtle);
		padding: var(--sp-3) 0;
	}
	.logo {
		font-size: 1.75rem;
	}
	.app-title {
		font-size: 1.125rem;
		font-weight: 700;
		color: var(--text-primary);
		line-height: 1.2;
	}
	.app-subtitle {
		color: var(--accent);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.flex-col {
		display: flex;
		flex-direction: column;
	}
	.app-main {
		flex: 1;
		padding: var(--sp-8) 0;
	}
	.app-footer {
		padding: var(--sp-6) 0;
		border-top: 1px solid var(--border-subtle);
	}
</style>
