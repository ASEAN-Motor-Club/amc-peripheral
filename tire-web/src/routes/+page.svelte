<script lang="ts">
	import type { TireEntry, CompatMod } from '$lib/types';
	import { createDefaultTire, validatePackName, validateTire, exportConfig } from '$lib/validation';
	import { buildTirePak, downloadBlob, downloadText } from '$lib/api';
	import TireCard from '$lib/components/TireCard.svelte';
	import CompatPanel from '$lib/components/CompatPanel.svelte';
	import BuildStatus from '$lib/components/BuildStatus.svelte';

	let packName = $state('AMCBetterTires');
	let tires = $state<TireEntry[]>([createDefaultTire(1)]);
	let compatMods = $state<CompatMod[]>([]);

	let buildStatus = $state<'idle' | 'building' | 'success' | 'error'>('idle');
	let buildMessage = $state('');
	let buildFilename = $state('');

	let packNameError = $derived(validatePackName(packName));

	let allValid = $derived.by(() => {
		if (packNameError) return false;
		if (tires.length === 0) return false;
		return tires.every((t) => validateTire(t).length === 0);
	});

	let readyCompatMods = $derived(
		compatMods.filter((m) => m.status === 'ready').map((m) => m.mod_id),
	);

	let tireCounter = $state(2);

	function addTire() {
		tires = [...tires, createDefaultTire(tireCounter)];
		tireCounter++;
	}

	function removeTire(idx: number) {
		if (tires.length <= 1) return;
		tires = tires.filter((_, i) => i !== idx);
	}

	function updateTire(idx: number, entry: TireEntry) {
		tires = tires.map((t, i) => (i === idx ? entry : t));
	}

	async function handleBuild() {
		if (!allValid) return;

		buildStatus = 'building';
		buildMessage = 'Building your tire mod PAK...';
		buildFilename = '';

		try {
			const blob = await buildTirePak(packName, tires, readyCompatMods, (msg) => {
				buildMessage = msg;
			});

			const filename = `${packName}_P.pak`;
			downloadBlob(blob, filename);

			buildStatus = 'success';
			buildMessage = 'PAK file downloaded successfully!';
			buildFilename = filename;
		} catch (err: any) {
			buildStatus = 'error';
			buildMessage = err.message || 'Build failed. Check your configuration.';
		}
	}

	function handleExportJson() {
		const json = exportConfig(tires);
		downloadText(json, 'tire_entries.json');
	}
</script>

<div class="container">
	<div class="page-content">

		<!-- Pack Name -->
		<div class="pack-name-section animate-in">
			<label class="field-label" for="pack-name">Pack Name</label>
			<div class="pack-name-row">
				<input
					id="pack-name"
					class="input"
					type="text"
					bind:value={packName}
					placeholder="e.g. AMCBetterTires"
				/>
				<span class="pack-suffix text-sm">_P.pak</span>
			</div>
			{#if packNameError}
				<span class="field-error text-xs">{packNameError}</span>
			{/if}
		</div>

		<!-- Mod Compatibility -->
		<CompatPanel bind:mods={compatMods} />

		<!-- Tire Cards -->
		<div class="tires-section">
			<div class="section-header">
				<h2>Tires</h2>
				<button class="btn btn-secondary" onclick={addTire}>
					<span>+</span> Add Tire
				</button>
			</div>

			<div class="tire-list">
				{#each tires as tire, i (i)}
					<TireCard
						entry={tire}
						index={i}
						onUpdate={(updated) => updateTire(i, updated)}
						onRemove={() => removeTire(i)}
					/>
				{/each}
			</div>
		</div>

		<!-- Build Section -->
		<div class="build-section card animate-in">
			<div class="card-header">
				<span style="font-size: 1rem">📦</span>
				<span class="flex-1">Build & Download</span>
			</div>
			<div class="card-body">
				<!-- Summary table -->
				<div class="summary">
					<table class="summary-table">
						<thead>
							<tr>
								<th>Tire</th>
								<th>Static Mu</th>
								<th>Sliding Mu</th>
								<th>Off-road</th>
								<th>Cost</th>
								<th>Vehicles</th>
							</tr>
						</thead>
						<tbody>
							{#each tires as t}
								<tr>
									<td class="tire-name-cell">{t.tire_part.display_name[0] || '—'}</td>
									<td class="num">{t.tire_physics.static_mu.toFixed(2)}</td>
									<td class="num">{t.tire_physics.sliding_mu.toFixed(2)}</td>
									<td class="num">
										{t.tire_physics.offroad_friction?.toFixed(2) ?? '—'}
									</td>
									<td class="num">${t.tire_part.cost.toLocaleString()}</td>
									<td class="types">
										{t.tire_part.vehicle_types.join(', ')}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				{#if compatMods.length > 0}
					<div class="compat-chain text-sm">
						<span class="chain-label">Build chain:</span>
						{#each compatMods.filter(m => m.status === 'ready') as mod, i}
							<span class="chain-mod">{mod.filename}</span>
							<span class="chain-arrow">→</span>
						{/each}
						<span class="chain-you">Your Tires ({tires.length})</span>
					</div>
				{/if}

				<BuildStatus status={buildStatus} message={buildMessage} filename={buildFilename} />

				<div class="build-actions">
					<button
						class="btn btn-primary btn-lg"
						disabled={!allValid || buildStatus === 'building'}
						onclick={handleBuild}
					>
						{#if buildStatus === 'building'}
							<div class="spinner" style="width: 16px; height: 16px; border-width: 2px"></div>
							Building...
						{:else}
							🔨 Build & Download .pak
						{/if}
					</button>

					<button class="btn btn-secondary" onclick={handleExportJson}>
						📄 Export JSON
					</button>
				</div>

				<details class="cli-help">
					<summary class="text-sm" style="cursor: pointer; color: var(--text-muted)">
						🖥️ CLI usage (for advanced users)
					</summary>
					<div class="cli-content">
						<p class="text-sm" style="color: var(--text-secondary); margin: var(--sp-2) 0">
							Download the JSON config and build locally with:
						</p>
						<pre class="code-block"><code>nix develop --command bash -c '
python3 scripts/create_tirepack.py \
  --config tire_entries.json \
  --output {packName || 'MyTires'}_P.pak{#each compatMods.filter(m => m.status === 'ready') as mod} \
  --compat-mod {mod.filename}{/each}
'</code></pre>
					</div>
				</details>
			</div>
		</div>
	</div>
</div>

<style>
	.page-content {
		display: flex;
		flex-direction: column;
		gap: var(--sp-6);
	}

	/* Pack Name */
	.pack-name-section {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}
	.field-label {
		font-size: 0.8125rem;
		font-weight: 500;
		color: var(--text-muted);
	}
	.pack-name-row {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
	}
	.pack-name-row .input {
		max-width: 300px;
	}
	.pack-suffix {
		color: var(--text-muted);
		font-weight: 500;
	}
	.field-error {
		color: var(--red);
	}

	/* Tires */
	.tires-section {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
	}
	.section-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.tire-list {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
	}

	/* Build */
	.build-section {
		animation-delay: 200ms;
	}
	.summary {
		overflow-x: auto;
		margin-bottom: var(--sp-4);
	}
	.summary-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.8125rem;
	}
	.summary-table th {
		text-align: left;
		padding: var(--sp-2) var(--sp-3);
		color: var(--text-muted);
		font-weight: 600;
		text-transform: uppercase;
		font-size: 0.6875rem;
		letter-spacing: 0.04em;
		border-bottom: 1px solid var(--border-default);
	}
	.summary-table td {
		padding: var(--sp-2) var(--sp-3);
		border-bottom: 1px solid var(--border-subtle);
		color: var(--text-secondary);
	}
	.tire-name-cell {
		font-weight: 500;
		color: var(--text-primary) !important;
	}
	.num {
		font-variant-numeric: tabular-nums;
		font-weight: 500;
	}
	.types {
		font-size: 0.75rem;
	}

	/* Compat chain */
	.compat-chain {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--sp-2);
		padding: var(--sp-3);
		background: var(--bg-elevated);
		border-radius: var(--r-sm);
		margin-bottom: var(--sp-4);
	}
	.chain-label {
		color: var(--text-muted);
		font-weight: 500;
	}
	.chain-mod {
		color: var(--text-secondary);
		background: var(--bg-primary);
		padding: 1px 8px;
		border-radius: var(--r-sm);
	}
	.chain-arrow {
		color: var(--text-muted);
	}
	.chain-you {
		color: var(--accent);
		font-weight: 600;
	}

	/* Build actions */
	.build-actions {
		display: flex;
		gap: var(--sp-3);
		margin-top: var(--sp-4);
	}

	/* CLI help */
	.cli-help {
		margin-top: var(--sp-4);
		padding: var(--sp-3);
		background: var(--bg-elevated);
		border-radius: var(--r-sm);
		border: 1px solid var(--border-subtle);
	}
	.code-block {
		background: var(--bg-deepest);
		padding: var(--sp-3);
		border-radius: var(--r-sm);
		overflow-x: auto;
		font-family: 'SF Mono', 'Fira Code', monospace;
		font-size: 0.75rem;
		color: var(--text-secondary);
		line-height: 1.6;
	}
</style>
