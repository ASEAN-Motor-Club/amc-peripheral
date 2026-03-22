/**
 * API client for the Radio ASEAN backend.
 * All calls include the Discord access_token as Bearer auth.
 */

let _accessToken: string = '';

export function setAccessToken(token: string) {
	_accessToken = token;
}

async function apiFetch<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
	const headers: Record<string, string> = {
		'Content-Type': 'application/json',
		...((options.headers as Record<string, string>) || {}),
	};

	if (_accessToken) {
		headers['Authorization'] = `Bearer ${_accessToken}`;
	}

	const response = await fetch(path, {
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
	return apiFetch('/api/now-playing');
}

export function queueSong(query: string): Promise<{ ok: boolean; title: string }> {
	return apiFetch('/api/queue', {
		method: 'POST',
		body: JSON.stringify({ query }),
	});
}

export function skipTrack(): Promise<{ ok: boolean }> {
	return apiFetch('/api/skip', { method: 'POST' });
}

export function likeSong(): Promise<{ ok: boolean; song_title: string }> {
	return apiFetch('/api/like', { method: 'POST' });
}

export function dislikeSong(): Promise<{ ok: boolean; song_title: string }> {
	return apiFetch('/api/dislike', { method: 'POST' });
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
	return apiFetch(`/api/recent-requests?limit=${limit}`);
}

export interface TopSong {
	song_title: string;
	like_count: number;
}

export function getTopLiked(limit = 10): Promise<{ songs: TopSong[] }> {
	return apiFetch(`/api/top-liked?limit=${limit}`);
}

export function queueTrending(): Promise<{ ok: boolean; title: string }> {
	return apiFetch('/api/queue-trending', { method: 'POST' });
}
