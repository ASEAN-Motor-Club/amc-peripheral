/**
 * Discord Embedded App SDK integration.
 * Handles SDK initialization, authorization, and authentication.
 */
import { DiscordSDK } from '@discord/embedded-app-sdk';

const CLIENT_ID = import.meta.env.PUBLIC_DISCORD_CLIENT_ID;

export const discordSdk = new DiscordSDK(CLIENT_ID);

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
 * Run the full Discord Activity auth flow:
 * 1. Wait for SDK ready
 * 2. Authorize (get code)
 * 3. Exchange code for access_token via our backend
 * 4. Authenticate with Discord client
 */
export async function authenticateWithDiscord(): Promise<DiscordAuth> {
	await discordSdk.ready();

	// Step 1: Get authorization code from Discord client
	const { code } = await discordSdk.commands.authorize({
		client_id: CLIENT_ID,
		response_type: 'code',
		state: '',
		prompt: 'none',
		scope: ['identify', 'guilds', 'guilds.members.read'],
	});

	// Step 2: Exchange code for access_token via our backend
	const response = await fetch('/api/token', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ code }),
	});

	if (!response.ok) {
		throw new Error('Token exchange failed');
	}

	const { access_token } = await response.json();

	// Step 3: Authenticate with Discord client
	const auth = await discordSdk.commands.authenticate({ access_token });
	if (!auth) {
		throw new Error('Discord authentication failed');
	}

	return {
		access_token,
		user: auth.user as DiscordAuth['user'],
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
