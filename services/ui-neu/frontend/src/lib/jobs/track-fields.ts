import type { TrackView } from '$lib/types/api.gen';
import { formatBytes } from '../utils/format';
import { isPostRipStatus } from './status-groups';

// The include checkbox's hint, shared by every track table.
export const INCLUDE_TRACK_HINT =
	'Include this track in transcode output. With one track kept, only that track is ripped; otherwise the disc rips in full.';

const TRACK_KIND_LABELS: Record<string, string> = {
	video_title: 'Video',
	audio_track: 'Audio',
	data_dump: 'Data',
	disc_backup: 'Disc backup'
};

export function trackKindLabel(kind: string | null | undefined): string {
	if (!kind) return '-';
	return TRACK_KIND_LABELS[kind] ?? kind;
}

// True when any track is an episode, has an episode number, or has no role on
// a TV job.
export function isSeriesTrackList(tracks: readonly TrackView[], mediaType: string | null | undefined): boolean {
	return tracks.some((t) => t.role === 'episode' || t.episode_number != null || (t.role == null && mediaType === 'tv'));
}

// Tracks whose episode or role the user set by hand (switching to Movie drops them).
export function handSetTrackCount(tracks: readonly TrackView[]): number {
	return tracks.filter((t) => ['episode_number', 'role'].some((k) => t.identity_provenance?.[k] === 'manual')).length;
}

// Actual size once ripped; otherwise the scan-time estimate prefixed with ~.
export function trackSizeLabel(track: TrackView): string {
	if (track.size_bytes != null) return formatBytes(track.size_bytes);
	if (track.expected_size_bytes != null) return `~${formatBytes(track.expected_size_bytes)}`;
	return '-';
}

// An excluded track the rip never read: with one track kept the rip reads only that one, so after the rip an
// excluded track is still queued. It shows as not ripped rather than as work still to do.
export function isUnrippedExclusion(track: Pick<TrackView, 'excluded' | 'status'>, jobStatus: string): boolean {
	return track.excluded === true && track.status === 'queued' && isPostRipStatus(jobStatus);
}
