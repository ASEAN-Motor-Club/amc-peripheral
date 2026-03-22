<script lang="ts">
	import { skipTrack, likeSong, dislikeSong, queueTrending } from '$lib/api';

	let skipLoading = $state(false);
	let likeLoading = $state(false);
	let dislikeLoading = $state(false);
	let trendingLoading = $state(false);
	let feedback = $state('');

	function showFeedback(msg: string) {
		feedback = msg;
		setTimeout(() => { feedback = ''; }, 3000);
	}

	async function handleSkip() {
		skipLoading = true;
		try {
			await skipTrack();
			showFeedback('⏭ Skipped');
		} catch (e) {
			showFeedback('Failed to skip');
		} finally {
			skipLoading = false;
		}
	}

	async function handleLike() {
		likeLoading = true;
		try {
			const res = await likeSong();
			showFeedback(`❤️ Liked "${res.song_title}"`);
		} catch (e) {
			showFeedback('Failed to like');
		} finally {
			likeLoading = false;
		}
	}

	async function handleDislike() {
		dislikeLoading = true;
		try {
			await dislikeSong();
			showFeedback('👎 Disliked');
		} catch (e) {
			showFeedback('Failed to dislike');
		} finally {
			dislikeLoading = false;
		}
	}

	async function handleTrending() {
		trendingLoading = true;
		try {
			const res = await queueTrending();
			showFeedback(`🎲 Trending: "${res.title}"`);
		} catch (e) {
			showFeedback('Failed to queue');
		} finally {
			trendingLoading = false;
		}
	}
</script>

<div class="quick-actions panel">
	<div class="panel-header">
		<span>🎛️</span>
		CONTROLS
	</div>
	<div class="panel-body actions-grid">
		<button class="btn btn-secondary action-btn" onclick={handleSkip} disabled={skipLoading}>
			<span class="action-icon">⏭</span>
			<span>Skip</span>
		</button>

		<button class="btn btn-secondary action-btn" onclick={handleLike} disabled={likeLoading}>
			<span class="action-icon">❤️</span>
			<span>Like</span>
		</button>

		<button class="btn btn-secondary action-btn" onclick={handleDislike} disabled={dislikeLoading}>
			<span class="action-icon">👎</span>
			<span>Dislike</span>
		</button>

		<button class="btn btn-secondary action-btn" onclick={handleTrending} disabled={trendingLoading}>
			<span class="action-icon">🎲</span>
			<span>Trending</span>
		</button>

		{#if feedback}
			<div class="action-feedback">{feedback}</div>
		{/if}
	</div>
</div>

<style>
	.actions-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-sm);
	}

	.action-btn {
		flex-direction: column;
		padding: var(--space-md) var(--space-sm);
		gap: var(--space-xs);
		height: auto;
	}

	.action-icon {
		font-size: 1.25rem;
	}

	.action-feedback {
		grid-column: 1 / -1;
		text-align: center;
		font-size: 0.75rem;
		color: var(--accent);
		padding: var(--space-xs);
		animation: fadeIn 0.2s ease;
	}

	@keyframes fadeIn {
		from { opacity: 0; transform: translateY(-4px); }
		to { opacity: 1; transform: translateY(0); }
	}
</style>
