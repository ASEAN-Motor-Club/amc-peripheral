/**
 * Discord Embedded App SDK integration.
 * Handles SDK initialization, authorization, and authentication.
 *
 * IMPORTANT: The DiscordSDK must be instantiated lazily (not at module level)
 * because it requires Discord iframe query params (frame_id, instance_id, platform)
 * which are only present when running inside a Discord Activity.
 */
import { DiscordSDK } from '@discord/embedded-app-sdk';

const CLIENT_ID = import.meta.env.VITE_DISCORD_CLIENT_ID;

let discordSdk: DiscordSDK | null = null;

export interface DiscordAuth {
	access_token: string;
	user: {
		id: string;
		username: string;
		global_name: string | null;
		avatar: string | null;
	};
}

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
 * Run the full Discord Activity auth flow:
 * 1. Create SDK instance (lazy)
 * 2. Wait for SDK ready
 * 3. Authorize (get code)
 * 4. Exchange code for access_token via our backend
 * 5. Authenticate with Discord client
 */
export async function authenticateWithDiscord(): Promise<DiscordAuth> {
	// Lazy instantiation — only create SDK when actually inside Discord
	discordSdk = new DiscordSDK(CLIENT_ID);

	console.log('[Radio] SDK created, waiting for ready...');
	await discordSdk.ready();
	console.log('[Radio] SDK ready, authorizing...');

	// Step 1: Get authorization code from Discord client
	const { code } = await discordSdk.commands.authorize({
		client_id: CLIENT_ID,
		response_type: 'code',
		state: '',
		prompt: 'none',
		scope: ['identify', 'guilds'],
	});
	console.log('[Radio] Got auth code, exchanging for token...');

	// Step 2: Exchange code for access_token via our backend
	const response = await fetch('/.proxy/radio-api/api/token', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ code }),
	});

	if (!response.ok) {
		const errData = await response.json().catch(() => ({}));
		console.error('[Radio] Token exchange failed:', response.status, errData);
		throw new Error(`Token exchange failed: ${response.status}`);
	}

	const { access_token } = await response.json();
	console.log('[Radio] Got access_token, authenticating with Discord...');

	// Step 3: Authenticate with Discord client
	const auth = await discordSdk.commands.authenticate({ access_token });
	if (!auth) {
		throw new Error('Discord authentication failed');
	}

	console.log('[Radio] Authenticated as', auth.user.username);
	return {
		access_token,
		user: auth.user as DiscordAuth['user'],
	};
}
