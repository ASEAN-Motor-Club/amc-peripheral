<script lang="ts">
	import { onMount } from 'svelte';
	import { queueSong, getRecentRequests, type SongRequest } from '$lib/api';
	import { recentRequests } from '$lib/stores/radio';

	let query = $state('');
	let loading = $state(false);
	let error = $state('');
	let success = $state('');
	let requests: SongRequest[] = $state([]);

	async function loadRequests() {
		try {
			const data = await getRecentRequests(15);
			requests = data.requests;
			recentRequests.set(data.requests);
		} catch {
			// Silently fail
		}
	}

	async function handleSubmit(e: Event) {
		e.preventDefault();
		if (!query.trim()) return;

		loading = true;
		error = '';
		success = '';

		try {
			const result = await queueSong(query.trim());
			success = `Queued "${result.title}"`;
			query = '';
			// Refresh requests
			await loadRequests();
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to queue song';
		} finally {
			loading = false;
		}
	}

	onMount(loadRequests);

	function timeAgo(dateStr: string): string {
		const diff = Date.now() - new Date(dateStr).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		return `${Math.floor(hrs / 24)}d ago`;
	}
</script>

<div class="queue-panel panel">
	<div class="panel-header">
		<span>📋</span>
		QUEUE
	</div>
	<div class="panel-body">
		<form class="queue-form" onsubmit={handleSubmit}>
			<input
				type="text"
				class="input"
				placeholder="Search song or paste YouTube link..."
				bind:value={query}
				disabled={loading}
			/>
			<button type="submit" class="btn btn-primary" disabled={loading || !query.trim()}>
				{#if loading}
					<span class="spinner"></span>
				{:else}
					▶ Queue
				{/if}
			</button>
		</form>

		{#if error}
			<div class="queue-msg queue-error">{error}</div>
		{/if}
		{#if success}
			<div class="queue-msg queue-success">{success}</div>
		{/if}

		<div class="divider"></div>

		<div class="queue-recent-header">
			<span class="text-xs" style="color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;">
				Recent Requests
			</span>
			<button class="btn btn-ghost text-xs" onclick={loadRequests}>↻ Refresh</button>
		</div>

		<div class="queue-list">
			{#each requests as req (req.id)}
				<div class="queue-item">
					<div class="qi-info">
						<span class="qi-title truncate">{req.song_title}</span>
						<span class="qi-meta">{req.requester_name} · {timeAgo(req.requested_at)}</span>
					</div>
				</div>
			{:else}
				<div class="queue-empty">No recent requests</div>
			{/each}
		</div>
	</div>
</div>

<style>
	.queue-form {
		display: flex;
		gap: var(--space-sm);
	}

	.queue-form .input {
		flex: 1;
	}

	.queue-msg {
		padding: var(--space-sm) var(--space-md);
		border-radius: var(--radius-sm);
		font-size: 0.8125rem;
		margin-top: var(--space-sm);
	}

	.queue-error {
		background: rgba(232, 64, 64, 0.1);
		color: var(--led-red);
		border: 1px solid rgba(232, 64, 64, 0.2);
	}

	.queue-success {
		background: rgba(62, 207, 90, 0.1);
		color: var(--led-green);
		border: 1px solid rgba(62, 207, 90, 0.2);
	}

	.queue-recent-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--space-sm);
	}

	.queue-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		max-height: 360px;
		overflow-y: auto;
	}

	.queue-item {
		display: flex;
		align-items: center;
		padding: var(--space-sm) var(--space-md);
		border-radius: var(--radius-sm);
		transition: background var(--transition-fast);
	}

	.queue-item:hover {
		background: var(--bg-elevated);
	}

	.qi-info {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
		flex: 1;
	}

	.qi-title {
		font-size: 0.875rem;
		color: var(--text-primary);
		font-weight: 500;
	}

	.qi-meta {
		font-size: 0.6875rem;
		color: var(--text-muted);
	}

	.queue-empty {
		text-align: center;
		color: var(--text-muted);
		padding: var(--space-xl);
		font-size: 0.8125rem;
	}
</style>
