<script lang="ts">
	interface Props {
		title: string;
		icon: string;
		description: string;
	}

	let { title, icon, description }: Props = $props();
</script>

<div class="stub-panel panel">
	<div class="panel-header">
		<span>{icon}</span>
		{title}
	</div>
	<div class="panel-body stub-content">
		<div class="stub-icon">{icon}</div>
		<div class="stub-title">{title}</div>
		<div class="stub-desc">{description}</div>
		<div class="badge">Coming Soon</div>
	</div>
</div>

<style>
	.stub-content {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-md);
		padding: var(--space-3xl) var(--space-xl);
		text-align: center;
	}

	.stub-icon {
		font-size: 2.5rem;
		opacity: 0.3;
	}

	.stub-title {
		font-size: 1rem;
		font-weight: 600;
		color: var(--text-secondary);
	}

	.stub-desc {
		font-size: 0.8125rem;
		color: var(--text-muted);
		max-width: 280px;
		line-height: 1.5;
	}
</style>
