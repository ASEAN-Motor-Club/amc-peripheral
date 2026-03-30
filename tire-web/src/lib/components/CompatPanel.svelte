<script lang="ts">
	import type { CompatMod } from '$lib/types';
	import { uploadModPak } from '$lib/api';
	import ModCard from './ModCard.svelte';

	interface Props {
		mods: CompatMod[];
	}

	let { mods = $bindable() }: Props = $props();

	let dragover = $state(false);
	let dragIndex = $state<number | null>(null);
	let fileInput: HTMLInputElement;

	async function handleFiles(files: FileList | null) {
		if (!files) return;
		for (const file of files) {
			if (!file.name.endsWith('.pak')) continue;

			const tempId = crypto.randomUUID();
			const newMod: CompatMod = {
				mod_id: tempId,
				filename: file.name,
				status: 'uploading',
				has_vehicle_parts0: false,
				tire_asset_count: 0,
				file_count: 0,
			};
			mods = [...mods, newMod];

			try {
				// Update to inspecting
				mods = mods.map((m) =>
					m.mod_id === tempId ? { ...m, status: 'inspecting' as const } : m,
				);

				const result = await uploadModPak(file);

				mods = mods.map((m) =>
					m.mod_id === tempId
						? {
								...m,
								mod_id: result.mod_id,
								status: 'ready' as const,
								has_vehicle_parts0: result.has_vehicle_parts0,
								tire_asset_count: result.tire_asset_count,
								file_count: result.file_count,
							}
						: m,
				);
			} catch (err: any) {
				mods = mods.map((m) =>
					m.mod_id === tempId
						? { ...m, status: 'error' as const, error: err.message }
						: m,
				);
			}
		}
	}

	function handleDrop(e: DragEvent) {
		e.preventDefault();
		dragover = false;
		handleFiles(e.dataTransfer?.files ?? null);
	}

	function removeMod(idx: number) {
		mods = mods.filter((_, i) => i !== idx);
	}

	// Drag-reorder logic
	function onItemDragStart(e: DragEvent, idx: number) {
		dragIndex = idx;
		if (e.dataTransfer) {
			e.dataTransfer.effectAllowed = 'move';
		}
	}

	function onItemDragOver(e: DragEvent, idx: number) {
		e.preventDefault();
		if (dragIndex === null || dragIndex === idx) return;

		const reordered = [...mods];
		const [moved] = reordered.splice(dragIndex, 1);
		reordered.splice(idx, 0, moved);
		mods = reordered;
		dragIndex = idx;
	}

	function onItemDragEnd() {
		dragIndex = null;
	}
</script>

<div class="compat-panel card">
	<div class="card-header">
		<span style="font-size: 1rem">🔧</span>
		<span class="flex-1">Mod Compatibility</span>
		{#if mods.length > 0}
			<span class="badge">{mods.length} mod{mods.length > 1 ? 's' : ''}</span>
		{/if}
	</div>

	<div class="card-body">
		<p class="hint text-sm">
			Upload other tire mod <code>.pak</code> files to build on top of them.
			Your tire mod will include their tire data, preventing conflicts.
		</p>

		{#if mods.length > 0}
			<div class="mod-list" role="list">
				{#each mods as mod, i}
					<ModCard
						{mod}
						index={i}
						onRemove={() => removeMod(i)}
						onDragStart={(e) => onItemDragStart(e, i)}
						onDragOver={(e) => onItemDragOver(e, i)}
						onDragEnd={onItemDragEnd}
						onDrop={(e) => e.preventDefault()}
					/>
				{/each}
			</div>

			<p class="priority-hint text-xs">
				⬆ Drag to reorder. Last mod's VehicleParts0 is used as the base.
				All listed mods must still be installed in your game.
			</p>
		{/if}

		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="drop-zone"
			class:dragover
			ondragover={(e) => { e.preventDefault(); dragover = true; }}
			ondragleave={() => { dragover = false; }}
			ondrop={handleDrop}
			onclick={() => fileInput?.click()}
			onkeydown={(e) => e.key === 'Enter' && fileInput?.click()}
			tabindex="0"
			role="button"
		>
			<input
				bind:this={fileInput}
				type="file"
				accept=".pak"
				multiple
				style="display: none"
				onchange={(e) => handleFiles(e.currentTarget.files)}
			/>
			<span class="drop-icon">📦</span>
			<span class="drop-text text-sm">Drop .pak files here or click to browse</span>
		</div>
	</div>
</div>

<style>
	.compat-panel {
		animation: fade-up 0.4s var(--t-slow) both;
	}
	.hint {
		color: var(--text-secondary);
		margin-bottom: var(--sp-3);
	}
	.hint code {
		background: var(--bg-elevated);
		padding: 1px 4px;
		border-radius: var(--r-sm);
		font-size: 0.8125rem;
	}
	.mod-list {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		margin-bottom: var(--sp-3);
	}
	.priority-hint {
		color: var(--text-muted);
		margin-bottom: var(--sp-3);
	}
	.drop-zone {
		padding: var(--sp-6);
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-2);
	}
	.drop-icon {
		font-size: 1.5rem;
	}
	.drop-text {
		color: var(--text-muted);
	}
</style>
