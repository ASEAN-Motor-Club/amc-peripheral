<script lang="ts">
	import { VEHICLE_TYPES, VEHICLE_TYPE_LABELS, type VehicleType } from '$lib/types';

	interface Props {
		selected: VehicleType[];
	}

	let { selected = $bindable() }: Props = $props();

	function toggle(type: VehicleType) {
		if (selected.includes(type)) {
			selected = selected.filter((t) => t !== type);
		} else {
			selected = [...selected, type];
		}
	}

	const icons: Record<VehicleType, string> = {
		Small: '🚗',
		Medium: '🚙',
		Large: '🚛',
		HeavyMachine: '🏗️',
		MotorCycle: '🏍️',
	};
</script>

<div class="type-selector">
	<span class="label text-sm">Vehicle Types</span>
	<div class="checkbox-group">
		{#each VEHICLE_TYPES as vtype}
			<label
				class="checkbox-pill"
				class:active={selected.includes(vtype)}
			>
				<input
					type="checkbox"
					checked={selected.includes(vtype)}
					onchange={() => toggle(vtype)}
				/>
				<span>{icons[vtype]}</span>
				<span>{VEHICLE_TYPE_LABELS[vtype]}</span>
			</label>
		{/each}
	</div>
</div>

<style>
	.type-selector {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}
	.label {
		color: var(--text-muted);
		font-weight: 500;
	}
</style>
