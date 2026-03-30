<script lang="ts">
	import type { TireEntry } from '$lib/types';
	import type { Preset } from '$lib/presets';
	import { syncDerivedFields, validateTire } from '$lib/validation';
	import PhysicsSlider from './PhysicsSlider.svelte';
	import ComparisonChart from './ComparisonChart.svelte';
	import HandlingGauge from './HandlingGauge.svelte';
	import VehicleTypeSelector from './VehicleTypeSelector.svelte';
	import PresetPicker from './PresetPicker.svelte';

	interface Props {
		entry: TireEntry;
		index: number;
		onUpdate: (entry: TireEntry) => void;
		onRemove: () => void;
	}

	let { entry, index, onUpdate, onRemove }: Props = $props();

	let collapsed = $state(false);
	let offroadEnabled = $state(entry.tire_physics.offroad_friction !== null);
	let errors = $derived(validateTire(entry));

	// Local copies for binding
	let displayName = $state(entry.tire_part.display_name[0] || '');
	let cost = $state(entry.tire_part.cost);
	let massKg = $state(entry.tire_part.mass_kg);
	let staticMu = $state(entry.tire_physics.static_mu);
	let slidingMu = $state(entry.tire_physics.sliding_mu);
	let offroadFriction = $state(entry.tire_physics.offroad_friction ?? 1.4);
	let vehicleTypes = $state(entry.tire_part.vehicle_types);

	// Sync back to parent on any change
	$effect(() => {
		const updated = syncDerivedFields({
			tire_physics: {
				...entry.tire_physics,
				static_mu: staticMu,
				sliding_mu: slidingMu,
				offroad_friction: offroadEnabled ? offroadFriction : null,
			},
			tire_part: {
				...entry.tire_part,
				display_name: [displayName],
				cost,
				mass_kg: massKg,
				vehicle_types: vehicleTypes,
			},
		});
		onUpdate(updated);
	});

	function applyPreset(preset: Preset) {
		staticMu = preset.static_mu;
		slidingMu = preset.sliding_mu;
		if (preset.offroad_friction !== null) {
			offroadEnabled = true;
			offroadFriction = preset.offroad_friction;
		} else {
			offroadEnabled = false;
		}
	}
</script>

<div class="tire-card card card-glass animate-in" style="animation-delay: {index * 80}ms">
	<div class="card-header" role="button" tabindex="0" onclick={() => collapsed = !collapsed} onkeydown={(e) => e.key === 'Enter' && (collapsed = !collapsed)}>
		<span class="tire-number">{index + 1}</span>
		<span class="tire-title flex-1 truncate">
			{displayName || 'Untitled Tire'}
		</span>
		{#if errors.length > 0}
			<span class="badge badge-error">{errors.length} issue{errors.length > 1 ? 's' : ''}</span>
		{/if}
		<button class="btn btn-ghost btn-icon" onclick={(e) => { e.stopPropagation(); onRemove(); }} title="Remove tire">✕</button>
		<span class="collapse-icon" class:rotated={!collapsed}>▾</span>
	</div>

	{#if !collapsed}
		<div class="card-body">
			<div class="tire-grid">
				<!-- Left: Config -->
				<div class="tire-config">
					<!-- Identity -->
					<div class="field-group">
						<label class="field-label text-sm" for="name-{index}">Display Name</label>
						<input
							id="name-{index}"
							class="input"
							type="text"
							bind:value={displayName}
							placeholder="e.g. AMC Racing Tire"
						/>
						<span class="field-hint text-xs">Internal: {entry.tire_physics.name || '...'}</span>
					</div>

					<div class="field-row">
						<div class="field-group">
							<label class="field-label text-sm" for="cost-{index}">Cost ($)</label>
							<input
								id="cost-{index}"
								class="input input-sm"
								type="number"
								bind:value={cost}
								min="100"
								max="50000"
								step="100"
							/>
						</div>
						<div class="field-group">
							<label class="field-label text-sm" for="mass-{index}">Mass (kg)</label>
							<input
								id="mass-{index}"
								class="input input-sm"
								type="number"
								bind:value={massKg}
								min="5"
								max="50"
								step="1"
							/>
						</div>
					</div>

					<VehicleTypeSelector bind:selected={vehicleTypes} />

					<PresetPicker onApply={applyPreset} />

					<!-- Physics Sliders -->
					<div class="sliders">
						<PhysicsSlider
							label="Static Friction (Mu)"
							bind:value={staticMu}
							min={0.5}
							max={3.0}
							step={0.05}
							hint="Grip at rest — higher = better traction from standstill"
						/>

						<PhysicsSlider
							label="Sliding Friction (Mu)"
							bind:value={slidingMu}
							min={0.3}
							max={3.0}
							step={0.05}
							hint="Grip while skidding — lower = easier to drift"
						/>

						<div class="offroad-toggle">
							<label class="checkbox-pill" class:active={offroadEnabled}>
								<input
									type="checkbox"
									bind:checked={offroadEnabled}
								/>
								<span>🌲</span>
								<span>Off-road Friction</span>
							</label>
						</div>

						{#if offroadEnabled}
							<PhysicsSlider
								label="Off-road Friction"
								bind:value={offroadFriction}
								min={0.5}
								max={3.0}
								step={0.05}
								hint="Grip on dirt/grass — only set for off-road capable tires"
							/>
						{/if}
					</div>
				</div>

				<!-- Right: Visualization -->
				<div class="tire-viz">
					<HandlingGauge {staticMu} {slidingMu} />
					<ComparisonChart {staticMu} {slidingMu} offroadFriction={offroadEnabled ? offroadFriction : null} />
				</div>
			</div>

			{#if errors.length > 0}
				<div class="errors">
					{#each errors as err}
						<span class="error-item text-sm">⚠ {err}</span>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.tire-card {
		transition: box-shadow var(--t-normal);
	}
	.tire-card:hover {
		box-shadow: var(--shadow-md);
	}
	.tire-number {
		width: 24px;
		height: 24px;
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--accent-glow);
		color: var(--accent);
		border-radius: var(--r-full);
		font-size: 0.75rem;
		font-weight: 700;
		flex-shrink: 0;
	}
	.tire-title {
		font-weight: 600;
		color: var(--text-primary);
	}
	.btn-icon {
		width: 28px;
		height: 28px;
		padding: 0;
		font-size: 0.875rem;
		border-radius: var(--r-sm);
		flex-shrink: 0;
	}
	.collapse-icon {
		color: var(--text-muted);
		font-size: 0.75rem;
		transition: transform var(--t-normal);
	}
	.collapse-icon.rotated {
		transform: rotate(0deg);
	}
	.collapse-icon:not(.rotated) {
		transform: rotate(-90deg);
	}
	.card-header {
		cursor: pointer;
		user-select: none;
	}
	.card-header:hover {
		background: var(--bg-hover);
	}
	.tire-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--sp-6);
	}
	@media (max-width: 768px) {
		.tire-grid {
			grid-template-columns: 1fr;
		}
	}
	.tire-config {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
	}
	.tire-viz {
		display: flex;
		flex-direction: column;
		gap: var(--sp-6);
	}
	.field-group {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}
	.field-label {
		color: var(--text-muted);
		font-weight: 500;
	}
	.field-hint {
		color: var(--text-muted);
	}
	.field-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--sp-3);
	}
	.sliders {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
	}
	.offroad-toggle {
		display: flex;
	}
	.errors {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		margin-top: var(--sp-3);
		padding: var(--sp-3);
		background: rgba(232, 64, 64, 0.05);
		border: 1px solid rgba(232, 64, 64, 0.15);
		border-radius: var(--r-sm);
	}
	.error-item {
		color: var(--red);
	}
</style>
