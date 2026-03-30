<script lang="ts">
	interface Props {
		status: 'idle' | 'building' | 'success' | 'error';
		message: string;
		filename?: string;
	}

	let { status, message, filename = '' }: Props = $props();
</script>

{#if status !== 'idle'}
	<div class="build-status" class:success={status === 'success'} class:error={status === 'error'}>
		{#if status === 'building'}
			<div class="spinner"></div>
		{:else if status === 'success'}
			<span class="status-icon">✓</span>
		{:else}
			<span class="status-icon error-icon">✕</span>
		{/if}

		<div class="status-info">
			<span class="status-message text-sm">{message}</span>
			{#if filename}
				<span class="status-filename text-xs">{filename}</span>
			{/if}
		</div>
	</div>
{/if}

<style>
	.build-status {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		padding: var(--sp-3) var(--sp-4);
		background: var(--accent-subtle);
		border: 1px solid var(--border-accent);
		border-radius: var(--r-md);
		animation: fade-up 0.3s ease both;
	}
	.build-status.success {
		background: rgba(62, 207, 90, 0.08);
		border-color: rgba(62, 207, 90, 0.25);
	}
	.build-status.error {
		background: rgba(232, 64, 64, 0.08);
		border-color: rgba(232, 64, 64, 0.25);
	}
	.status-icon {
		width: 24px;
		height: 24px;
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--green);
		color: #fff;
		border-radius: var(--r-full);
		font-size: 0.75rem;
		font-weight: 700;
		flex-shrink: 0;
	}
	.error-icon {
		background: var(--red);
	}
	.status-info {
		display: flex;
		flex-direction: column;
	}
	.status-message {
		color: var(--text-primary);
		font-weight: 500;
	}
	.status-filename {
		color: var(--text-muted);
	}
</style>
