export interface BaseTire {
	name: string;
	label: string;
	staticMu: number;
	slidingMu: number;
	offroad: number | null;
}

export const BASE_TIRES: BaseTire[] = [
	{ name: 'BasicTire', label: 'Stock', staticMu: 1.1, slidingMu: 1.0, offroad: null },
	{ name: 'PerformanceTire', label: 'Performance', staticMu: 1.1, slidingMu: 1.0, offroad: null },
	{ name: 'DriftTire', label: 'Drift', staticMu: 1.1, slidingMu: 0.85, offroad: null },
	{ name: 'OffroadTire', label: 'Offroad', staticMu: 0.95, slidingMu: 0.9, offroad: 1.4 },
	{ name: 'HeavyDuty', label: 'Heavy Duty', staticMu: 0.97, slidingMu: 0.87, offroad: null },
];

export interface Preset {
	label: string;
	desc: string;
	icon: string;
	static_mu: number;
	sliding_mu: number;
	offroad_friction: number | null;
}

export const PRESETS: Record<string, Preset> = {
	stock: {
		label: 'Stock',
		desc: 'Factory default handling',
		icon: '🚗',
		static_mu: 1.1,
		sliding_mu: 1.0,
		offroad_friction: null,
	},
	grippy: {
		label: 'Grippy',
		desc: 'Natural high-grip, great all-around',
		icon: '✊',
		static_mu: 1.4,
		sliding_mu: 1.2,
		offroad_friction: 1.7,
	},
	racing: {
		label: 'Racing Slick',
		desc: 'Maximum road grip, terrible off-road',
		icon: '🏁',
		static_mu: 1.6,
		sliding_mu: 1.4,
		offroad_friction: null,
	},
	drift: {
		label: 'Drift',
		desc: 'Low sliding friction for controlled slides',
		icon: '💨',
		static_mu: 1.0,
		sliding_mu: 0.7,
		offroad_friction: null,
	},
	offroad: {
		label: 'Off-road Beast',
		desc: 'Dominant off-road, decent on-road',
		icon: '🌲',
		static_mu: 1.2,
		sliding_mu: 1.0,
		offroad_friction: 2.0,
	},
	police: {
		label: 'Police Pursuit',
		desc: 'AMC Police 78 spec—high grip all surfaces',
		icon: '🚓',
		static_mu: 1.8,
		sliding_mu: 1.5,
		offroad_friction: 1.6,
	},
};

/** Compute handling character: 0 = pure drift, 0.5 = balanced, 1 = ultra grip */
export function handlingScore(staticMu: number, slidingMu: number): number {
	// Ratio of sliding to static — lower ratio = more drift tendency
	const ratio = slidingMu / Math.max(staticMu, 0.5);
	// Map: ratio 0.5 = drift (0), ratio 1.0 = balanced (0.5), ratio > 1.0 = grip (up to 1.0)
	const score = (ratio - 0.5) / 0.7; // 0.5→0, 1.2→1.0
	return Math.max(0, Math.min(1, score));
}
