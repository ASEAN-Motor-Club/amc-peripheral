import type { TireEntry, TirePhysics, TirePart, VehicleType } from './types';

/** Convert a display name into a safe internal name */
export function toInternalName(displayName: string): string {
	return displayName
		.replace(/[^a-zA-Z0-9\s]/g, '')
		.trim()
		.replace(/\s+/g, '_');
}

/** Generate tire_asset_path from internal name */
export function toAssetPath(internalName: string): string {
	return `/Game/Cars/Parts/Tire/${internalName}/${internalName}`;
}

/** Generate a row_name from internal name (strip _Tire suffix if present) */
export function toRowName(internalName: string): string {
	return internalName.replace(/_Tire$/, '');
}

/** Create a default tire entry */
export function createDefaultTire(index: number): TireEntry {
	const name = `Custom_${String(index).padStart(2, '0')}_Tire`;
	const rowName = toRowName(name);
	return {
		tire_physics: {
			name,
			template: 'BasicTire_45',
			static_mu: 1.1,
			sliding_mu: 1.0,
			offroad_friction: null,
		},
		tire_part: {
			row_name: rowName,
			display_name: [`Custom Tire ${index}`],
			cost: 2000,
			mass_kg: 10,
			vehicle_types: ['Small'] as VehicleType[],
			tire_asset_path: toAssetPath(name),
		},
	};
}

/** Recalculate derived fields when display name changes */
export function syncDerivedFields(entry: TireEntry): TireEntry {
	const displayName = entry.tire_part.display_name[0] || 'Custom';
	const internalName = toInternalName(displayName) + '_Tire';
	return {
		...entry,
		tire_physics: {
			...entry.tire_physics,
			name: internalName,
		},
		tire_part: {
			...entry.tire_part,
			row_name: toRowName(internalName),
			tire_asset_path: toAssetPath(internalName),
		},
	};
}

/** Validate a pack name */
export function validatePackName(name: string): string | null {
	if (!name) return 'Pack name is required';
	if (name.length < 3) return 'At least 3 characters';
	if (name.length > 50) return 'Max 50 characters';
	if (!/^[A-Za-z0-9_]+$/.test(name)) return 'Letters, numbers, underscores only';
	return null;
}

/** Validate a single tire entry */
export function validateTire(entry: TireEntry): string[] {
	const errors: string[] = [];
	const { tire_physics: tp, tire_part: part } = entry;

	if (!tp.name || tp.name.length < 3) errors.push('Internal name too short');
	if (tp.static_mu < 0.5 || tp.static_mu > 3.0) errors.push('Static friction out of range (0.5–3.0)');
	if (tp.sliding_mu < 0.3 || tp.sliding_mu > 3.0) errors.push('Sliding friction out of range (0.3–3.0)');
	if (tp.offroad_friction !== null && (tp.offroad_friction < 0.5 || tp.offroad_friction > 3.0))
		errors.push('Offroad friction out of range (0.5–3.0)');

	if (!part.display_name[0]) errors.push('Display name is required');
	if (part.cost < 100 || part.cost > 50000) errors.push('Cost out of range ($100–$50,000)');
	if (part.mass_kg < 5 || part.mass_kg > 50) errors.push('Mass out of range (5–50 kg)');
	if (part.vehicle_types.length === 0) errors.push('Select at least one vehicle type');

	return errors;
}

/** Export tire config as JSON string (matching create_tirepack.py schema) */
export function exportConfig(tires: TireEntry[]): string {
	const config = {
		tires: tires.map((t) => ({
			tire_physics: {
				name: t.tire_physics.name,
				template: t.tire_physics.template,
				static_mu: t.tire_physics.static_mu,
				sliding_mu: t.tire_physics.sliding_mu,
				...(t.tire_physics.offroad_friction !== null
					? { offroad_friction: t.tire_physics.offroad_friction }
					: {}),
			},
			tire_part: {
				row_name: t.tire_part.row_name,
				display_name: t.tire_part.display_name,
				cost: t.tire_part.cost,
				mass_kg: t.tire_part.mass_kg,
				vehicle_types: t.tire_part.vehicle_types,
				tire_asset_path: t.tire_part.tire_asset_path,
			},
		})),
	};
	return JSON.stringify(config, null, 2);
}
