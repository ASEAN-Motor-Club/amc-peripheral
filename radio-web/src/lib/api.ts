/**
 * API client for the Radio ASEAN backend.
 * All calls include the Discord access_token as Bearer auth.
 *
 * When inside a Discord Activity, API requests go through the Discord proxy
 * at /.proxy/radio-api/api/*. In dev mode (direct browser), they go to /api/*.
 */

let _accessToken: string = '';
let _apiBase: string = '/api';

export function setAccessToken(token: string) {
	_accessToken = token;
}

export function setApiBase(base: string) {
	_apiBase = base;
}

async function apiFetch<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
	const headers: Record<string, string> = {
		'Content-Type': 'application/json',
		...((options.headers as Record<string, string>) || {}),
	};

	if (_accessToken) {
		headers['Authorization'] = `Bearer ${_accessToken}`;
	}

	const url = `${_apiBase}${path}`;
	const response = await fetch(url, {
		...options,
		headers,
	});

	const data = await response.json();

	if (!response.ok) {
		throw new Error(data.error || `API error ${response.status}`);
	}

	return data as T;
}

// --- Phase 1 endpoints ---

export interface NowPlaying {
	playing: boolean;
	song_title?: string;
	folder?: string;
	requester?: string;
	like_count?: number;
}

export function getNowPlaying(): Promise<NowPlaying> {
	return apiFetch('/now-playing');
}

export function queueSong(query: string): Promise<{ ok: boolean; title: string }> {
	return apiFetch('/queue', {
		method: 'POST',
		body: JSON.stringify({ query }),
	});
}

export function skipTrack(): Promise<{ ok: boolean }> {
	return apiFetch('/skip', { method: 'POST' });
}

export function likeSong(): Promise<{ ok: boolean; song_title: string }> {
	return apiFetch('/like', { method: 'POST' });
}

export function dislikeSong(): Promise<{ ok: boolean; song_title: string }> {
	return apiFetch('/dislike', { method: 'POST' });
}

export interface SongRequest {
	id: number;
	discord_id: string | null;
	song_title: string;
	song_url: string | null;
	requester_name: string;
	requested_at: string;
}

export function getRecentRequests(limit = 20): Promise<{ requests: SongRequest[] }> {
	return apiFetch(`/recent-requests?limit=${limit}`);
}

export interface TopSong {
	song_title: string;
	like_count: number;
}

export function getTopLiked(limit = 10): Promise<{ songs: TopSong[] }> {
	return apiFetch(`/top-liked?limit=${limit}`);
}

export function queueTrending(): Promise<{ ok: boolean; title: string }> {
	return apiFetch('/queue-trending', { method: 'POST' });
}
