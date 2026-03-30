<script lang="ts">
	import type { CompatMod } from '$lib/types';

	interface Props {
		mod: CompatMod;
		index: number;
		onRemove: () => void;
		onDragStart: (e: DragEvent) => void;
		onDragOver: (e: DragEvent) => void;
		onDragEnd: (e: DragEvent) => void;
		onDrop: (e: DragEvent) => void;
	}

	let { mod, index, onRemove, onDragStart, onDragOver, onDragEnd, onDrop }: Props = $props();

	let statusIcon = $derived.by(() => {
		switch (mod.status) {
			case 'uploading': return '⏳';
			case 'inspecting': return '🔍';
			case 'ready': return mod.has_vehicle_parts0 ? '✓' : '⚠';
			case 'error': return '✕';
		}
	});

	let statusClass = $derived.by(() => {
		if (mod.status === 'error') return 'badge-error';
		if (mod.status === 'ready' && mod.has_vehicle_parts0) return 'badge-success';
		if (mod.status === 'ready' && !mod.has_vehicle_parts0) return 'badge-warning';
		return '';
	});
</script>

<div
	class="mod-card"
	class:error={mod.status === 'error'}
	draggable="true"
	ondragstart={onDragStart}
	ondragover={onDragOver}
	ondragend={onDragEnd}
	ondrop={onDrop}
	role="listitem"
>
	<div class="drag-handle" title="Drag to reorder">
		<span class="grip">⠿</span>
	</div>

	<span class="mod-priority">{index + 1}</span>

	<div class="mod-info flex-1">
		<span class="mod-name truncate">{mod.filename}</span>
		{#if mod.status === 'ready'}
			<span class="mod-detail text-xs">
				{#if mod.has_vehicle_parts0}
					{mod.tire_asset_count} tire asset{mod.tire_asset_count !== 1 ? 's' : ''} · {mod.file_count} files
				{:else}
					No VehicleParts0 found
				{/if}
			</span>
		{:else if mod.status === 'uploading'}
			<span class="mod-detail text-xs">Uploading...</span>
		{:else if mod.status === 'inspecting'}
			<span class="mod-detail text-xs">Inspecting PAK...</span>
		{:else if mod.status === 'error'}
			<span class="mod-detail text-xs error-text">{mod.error || 'Failed'}</span>
		{/if}
	</div>

	<span class="badge {statusClass}">{statusIcon}</span>

	<button
		class="btn btn-ghost btn-remove"
		onclick={onRemove}
		title="Remove"
	>✕</button>
</div>

<style>
	.mod-card {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		padding: var(--sp-2) var(--sp-3);
		background: var(--bg-elevated);
		border: 1px solid var(--border-subtle);
		border-radius: var(--r-md);
		cursor: grab;
		transition: all var(--t-fast);
		user-select: none;
	}
	.mod-card:hover {
		border-color: var(--border-accent);
		background: var(--bg-hover);
	}
	.mod-card:active {
		cursor: grabbing;
		box-shadow: var(--shadow-md);
	}
	.mod-card.error {
		border-color: rgba(232, 64, 64, 0.25);
	}
	.drag-handle {
		display: flex;
		align-items: center;
		color: var(--text-muted);
		font-size: 1.25rem;
		cursor: grab;
	}
	.grip {
		line-height: 1;
	}
	.mod-priority {
		width: 20px;
		height: 20px;
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--bg-primary);
		color: var(--text-secondary);
		border-radius: var(--r-full);
		font-size: 0.6875rem;
		font-weight: 700;
		flex-shrink: 0;
	}
	.mod-info {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.mod-name {
		font-size: 0.8125rem;
		font-weight: 500;
		color: var(--text-primary);
	}
	.mod-detail {
		color: var(--text-muted);
	}
	.error-text {
		color: var(--red);
	}
	.btn-remove {
		padding: var(--sp-1);
		font-size: 0.75rem;
		flex-shrink: 0;
	}
</style>
