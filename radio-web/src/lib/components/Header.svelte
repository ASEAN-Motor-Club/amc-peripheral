<script lang="ts">
	import { authStore } from '$lib/stores/auth';

	let auth = $state({ loading: true, authenticated: false, user: null as any, error: null as string | null });
	authStore.subscribe(v => { auth = v; });

	function getAvatarUrl(user: { id: string; avatar: string | null }): string {
		if (user.avatar) {
			return `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png?size=32`;
		}
		return '';
	}
</script>

<header class="header">
	<div class="header-left">
		<h1 class="header-title font-mono">RADIO ASEAN</h1>
		<span class="header-separator">·</span>
		<span class="header-subtitle">DJ Control Panel</span>
	</div>

	<div class="header-right">
		<a href="https://www.aseanmotorclub.com/radio" target="_blank" rel="noopener" class="stream-link btn btn-ghost text-xs">
			🔊 Listen Live
		</a>

		{#if auth.authenticated && auth.user}
			<div class="user-info">
				{#if auth.user.avatar}
					<img class="user-avatar" src={getAvatarUrl(auth.user)} alt={auth.user.username} />
				{:else}
					<div class="user-avatar user-avatar-fallback">
						{(auth.user.global_name || auth.user.username).charAt(0).toUpperCase()}
					</div>
				{/if}
				<span class="user-name text-sm">{auth.user.global_name || auth.user.username}</span>
			</div>
		{/if}
	</div>
</header>

<style>
	.header {
		height: var(--header-height);
		background: var(--bg-secondary);
		border-bottom: 1px solid var(--border-subtle);
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 var(--space-xl);
		flex-shrink: 0;
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.header-title {
		font-size: 0.8125rem;
		font-weight: 600;
		color: var(--accent);
		letter-spacing: 0.1em;
	}

	.header-separator {
		color: var(--text-muted);
	}

	.header-subtitle {
		font-size: 0.75rem;
		color: var(--text-muted);
	}

	.header-right {
		display: flex;
		align-items: center;
		gap: var(--space-lg);
	}

	.stream-link {
		text-decoration: none;
	}

	.user-info {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.user-avatar {
		width: 28px;
		height: 28px;
		border-radius: 50%;
		object-fit: cover;
	}

	.user-avatar-fallback {
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--accent);
		color: #000;
		font-size: 0.75rem;
		font-weight: 700;
	}

	.user-name {
		color: var(--text-secondary);
	}
</style>
