export type VehicleType = 'Small' | 'Medium' | 'Large' | 'HeavyMachine' | 'MotorCycle';

export interface TirePhysics {
	name: string;
	template: string;
	static_mu: number;
	sliding_mu: number;
	offroad_friction: number | null;
}

export interface TirePart {
	row_name: string;
	display_name: string[];
	cost: number;
	mass_kg: number;
	vehicle_types: VehicleType[];
	tire_asset_path: string;
}

export interface TireEntry {
	tire_physics: TirePhysics;
	tire_part: TirePart;
}

export interface TirePack {
	tires: TireEntry[];
}

export interface CompatMod {
	mod_id: string;
	filename: string;
	status: 'uploading' | 'inspecting' | 'ready' | 'error';
	has_vehicle_parts0: boolean;
	tire_asset_count: number;
	file_count: number;
	error?: string;
}

export interface BuildConfig {
	pack_name: string;
	tires: TireEntry[];
	compat_mods: string[];
}

export interface ModInspectionResult {
	mod_id: string;
	filename: string;
	file_count: number;
	has_vehicle_parts0: boolean;
	tire_asset_count: number;
}

export const VEHICLE_TYPES: VehicleType[] = ['Small', 'Medium', 'Large', 'HeavyMachine', 'MotorCycle'];

export const VEHICLE_TYPE_LABELS: Record<VehicleType, string> = {
	Small: 'Small',
	Medium: 'Medium',
	Large: 'Large',
	HeavyMachine: 'Heavy Machine',
	MotorCycle: 'Motorcycle',
};
