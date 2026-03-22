<script lang="ts">
	import NowPlaying from '$lib/components/NowPlaying.svelte';
	import QueuePanel from '$lib/components/QueuePanel.svelte';
	import QuickActions from '$lib/components/QuickActions.svelte';
</script>

<svelte:head>
	<title>Radio ASEAN — Studio</title>
</svelte:head>

<div class="dashboard">
	<div class="dash-left">
		<NowPlaying />
		<QuickActions />
	</div>
	<div class="dash-right">
		<QueuePanel />
	</div>
</div>

<style>
	.dashboard {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-xl);
		height: 100%;
	}

	.dash-left {
		display: flex;
		flex-direction: column;
		gap: var(--space-xl);
	}

	.dash-right {
		display: flex;
		flex-direction: column;
		gap: var(--space-xl);
	}

	@media (max-width: 900px) {
		.dashboard {
			grid-template-columns: 1fr;
		}
	}
</style>
