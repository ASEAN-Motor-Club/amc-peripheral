<script lang="ts">
	import { page } from '$app/state';

	const navItems = [
		{ href: '/', icon: '🏠', label: 'Dashboard' },
		{ href: '/queue', icon: '📋', label: 'Queue' },
		{ href: '/playlists', icon: '📁', label: 'Playlists' },
		{ href: '/talkshows', icon: '🎙️', label: 'Talkshows' },
		{ href: '/stats', icon: '📊', label: 'Stats' },
		{ href: '/news', icon: '📰', label: 'News' },
		{ href: '/settings', icon: '⚙️', label: 'Settings' },
	];
</script>

<nav class="sidebar">
	<div class="sidebar-brand">
		<div class="brand-icon">📻</div>
		<div class="brand-text">
			<span class="brand-name">Radio ASEAN</span>
			<span class="brand-sub">Studio Console</span>
		</div>
	</div>

	<div class="divider"></div>

	<div class="sidebar-nav">
		{#each navItems as item}
			<a
				href={item.href}
				class="nav-item"
				class:active={page.url.pathname === item.href}
			>
				<span class="nav-icon">{item.icon}</span>
				<span class="nav-label">{item.label}</span>
			</a>
		{/each}
	</div>

	<div class="sidebar-footer">
		<div class="studio-status">
			<span class="led led-on"></span>
			<span class="text-xs" style="color: var(--text-muted);">LIVE</span>
		</div>
	</div>
</nav>

<style>
	.sidebar {
		width: var(--sidebar-width);
		height: 100dvh;
		background: var(--bg-tertiary);
		border-right: 1px solid var(--border-subtle);
		display: flex;
		flex-direction: column;
		padding: var(--space-md);
		flex-shrink: 0;
	}

	.sidebar-brand {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		padding: var(--space-sm) var(--space-xs);
	}

	.brand-icon {
		font-size: 1.5rem;
	}

	.brand-text {
		display: flex;
		flex-direction: column;
	}

	.brand-name {
		font-size: 0.875rem;
		font-weight: 700;
		color: var(--text-primary);
	}

	.brand-sub {
		font-size: 0.625rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}

	.sidebar-nav {
		display: flex;
		flex-direction: column;
		gap: 2px;
		flex: 1;
	}

	.nav-item {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		padding: var(--space-sm) var(--space-md);
		border-radius: var(--radius-md);
		color: var(--text-secondary);
		text-decoration: none;
		font-size: 0.875rem;
		font-weight: 500;
		transition: all var(--transition-fast);
		position: relative;
	}

	.nav-item:hover {
		background: var(--accent-subtle);
		color: var(--text-primary);
		text-decoration: none;
	}

	.nav-item.active {
		background: var(--accent-subtle);
		color: var(--accent);
		border-left: 3px solid var(--accent);
		padding-left: calc(var(--space-md) - 3px);
	}

	.nav-icon {
		font-size: 1rem;
		width: 20px;
		text-align: center;
	}

	.nav-label {
		flex: 1;
	}

	.sidebar-footer {
		padding: var(--space-sm) 0;
	}

	.studio-status {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-sm) var(--space-md);
	}
</style>
