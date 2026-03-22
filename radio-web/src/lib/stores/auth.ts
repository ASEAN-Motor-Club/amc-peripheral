/**
 * Auth store — tracks Discord user and access token.
 */
import { writable } from 'svelte/store';
import type { DiscordAuth } from '$lib/discord';

export const authStore = writable<{
	loading: boolean;
	authenticated: boolean;
	user: DiscordAuth['user'] | null;
	error: string | null;
}>({
	loading: true,
	authenticated: false,
	user: null,
	error: null,
});
