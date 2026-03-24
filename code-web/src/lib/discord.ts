/**
 * Discord Embedded App SDK integration — minimal version.
 *
 * Only initializes the SDK and waits for ready().
 * No OAuth flow — auth is handled by GitHub OAuth2 proxy
 * on the underlying OpenCode web UI.
 *
 * IMPORTANT: The DiscordSDK must be instantiated lazily (not at module level)
 * because it requires Discord iframe query params (frame_id, instance_id, platform)
 * which are only present when running inside a Discord Activity.
 */
import { DiscordSDK } from '@discord/embedded-app-sdk';
import { PUBLIC_DISCORD_CLIENT_ID } from '$env/static/public';

let discordSdk: DiscordSDK | null = null;

/**
 * Check if we're running inside a Discord Activity iframe.
 * Falls back gracefully for standalone browser testing.
 */
export function isInDiscordActivity(): boolean {
	try {
		return window.self !== window.top;
	} catch {
		return true;
	}
}

/**
 * Initialize the Discord SDK — just the ready handshake.
 * No authorization or authentication needed since we use
 * GitHub OAuth on the underlying OpenCode web UI.
 */
export async function initDiscordSdk(): Promise<void> {
	discordSdk = new DiscordSDK(PUBLIC_DISCORD_CLIENT_ID);

	console.log('[Code] SDK created, waiting for ready...');
	await discordSdk.ready();
	console.log('[Code] SDK ready');
}
