/**
 * Radio state store — now-playing with polling, recent requests.
 */
import { writable } from 'svelte/store';
import type { NowPlaying, SongRequest } from '$lib/api';

export const nowPlaying = writable<NowPlaying>({ playing: false });
export const recentRequests = writable<SongRequest[]>([]);
export const isPolling = writable(false);
