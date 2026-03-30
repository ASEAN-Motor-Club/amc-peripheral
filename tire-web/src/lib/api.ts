import type { ModInspectionResult, TireEntry } from './types';

const API_BASE = '/api/mods';

export class BuildError extends Error {
	constructor(
		message: string,
		public status: number,
	) {
		super(message);
	}
}

/** Upload a mod PAK for compatibility inspection */
export async function uploadModPak(file: File): Promise<ModInspectionResult> {
	const formData = new FormData();
	formData.append('file', file);

	const res = await fetch(`${API_BASE}/tire/upload`, {
		method: 'POST',
		body: formData,
	});

	if (!res.ok) {
		const text = await res.text().catch(() => 'Upload failed');
		throw new BuildError(text, res.status);
	}

	return res.json();
}

/** Build a tire mod PAK on the server */
export async function buildTirePak(
	packName: string,
	tires: TireEntry[],
	compatModIds: string[],
	onProgress?: (msg: string) => void,
): Promise<Blob> {
	onProgress?.('Preparing build request...');

	const config = {
		pack_name: packName,
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
		compat_mods: compatModIds,
	};

	onProgress?.('Building PAK file...');

	const res = await fetch(`${API_BASE}/tire/build`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(config),
	});

	if (!res.ok) {
		const text = await res.text().catch(() => 'Build failed');
		throw new BuildError(text, res.status);
	}

	onProgress?.('Downloading...');
	return res.blob();
}

/** Trigger a download for a blob */
export function downloadBlob(blob: Blob, filename: string): void {
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
	URL.revokeObjectURL(url);
}

/** Download a string as a file */
export function downloadText(text: string, filename: string, type = 'application/json'): void {
	const blob = new Blob([text], { type });
	downloadBlob(blob, filename);
}

/** Check API health */
export async function checkHealth(): Promise<boolean> {
	try {
		const res = await fetch(`${API_BASE}/health`);
		return res.ok;
	} catch {
		return false;
	}
}
