<script lang="ts">
	// What a scanned title carries (playlist, picture, audio, subtitles, chapters, segments), shown under its track
	// so the operator can tell same-length variants of the film apart before choosing one.
	import { titleDetails } from '$lib/jobs/scan-streams';
	import type { ScanTitle } from '$lib/types/api.gen';

	interface Props {
		title: ScanTitle;
	}

	let { title }: Props = $props();
	let details = $derived(titleDetails(title));
</script>

<dl class="track-source-details" data-testid="track-source-details">
	{#if details.source}
		<div><dt>Source</dt><dd class="mono">{details.source}</dd></div>
	{/if}
	{#if details.video}
		<div><dt>Video</dt><dd>{details.video}</dd></div>
	{/if}
	{#if details.audio.length}
		<div><dt>Audio</dt><dd>{details.audio.join(' · ')}</dd></div>
	{/if}
	{#if details.subtitles.length}
		<div><dt>Subtitles</dt><dd>{details.subtitles.join(' · ')}</dd></div>
	{/if}
	{#if details.chapters != null}
		<div><dt>Chapters</dt><dd>{details.chapters}</dd></div>
	{/if}
	{#if details.segments}
		<div><dt>Segments</dt><dd class="mono">{details.segments}</dd></div>
	{/if}
</dl>

<style>
	.track-source-details {
		margin-top: 0.25rem;
		font-size: 0.75rem;
		line-height: 1.1rem;
		color: var(--color-text-secondary);
	}
	.track-source-details div {
		display: flex;
		gap: 0.375rem;
	}
	.track-source-details dt {
		flex: none;
		width: 4.5rem;
		color: var(--color-text-faint);
	}
	.track-source-details dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
</style>
