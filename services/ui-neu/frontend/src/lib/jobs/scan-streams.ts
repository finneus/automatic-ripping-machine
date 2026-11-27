// What a scanned title carries, as short lines for the track tables: its playlist, picture, audio and subtitles.
// Same-length variants of a film (one per language group on many UHDs) differ only in these, so the operator needs
// them to choose which one to rip.
import type { ScanStream, ScanTitle } from '$lib/types/api.gen';

export interface TitleDetails {
	/** MakeMKV's source of the title: a playlist (`00800.mpls`) or a bare clip. */
	source: string | null;
	/** The first video stream: codec and frame size. */
	video: string | null;
	audio: string[];
	subtitles: string[];
	chapters: number | null;
	/** The clip ids a playlist plays, as MakeMKV lists them. */
	segments: string | null;
}

/** The scanned titles of a job's metadata, or none when it holds no scan. */
export function scanTitlesOf(metadata: unknown): ScanTitle[] {
	if (!metadata || typeof metadata !== 'object') return [];
	const scan = (metadata as { scan_result?: unknown }).scan_result;
	if (!scan || typeof scan !== 'object') return [];
	const titles = (scan as { titles?: unknown }).titles;
	return Array.isArray(titles) ? (titles as ScanTitle[]) : [];
}

/** The scanned title a track was made from (a video track's index is its title's index). */
export function scanTitleAt(titles: ScanTitle[], index: number): ScanTitle | undefined {
	return titles.find((t) => t.index === index);
}

function joined(parts: (string | null | undefined)[]): string {
	return parts.filter((p) => p).join(' ');
}

/** `deu TrueHD 7.1`, marked when it is a commentary. */
export function audioLabel(stream: ScanStream): string {
	const label = joined([stream.language, stream.codec, stream.channels]) || '?';
	return stream.commentary ? `${label} (commentary)` : label;
}

/** `deu`, marked when it is forced. */
export function subtitleLabel(stream: ScanStream): string {
	const label = stream.language || '?';
	return stream.forced ? `${label} (forced)` : label;
}

function streamsOf(title: ScanTitle, kind: ScanStream['kind']): ScanStream[] {
	return (title.streams ?? []).filter((s) => s.kind === kind);
}

/** A title's details; a scan from before streams were recorded still lists its audio languages. */
export function titleDetails(title: ScanTitle): TitleDetails {
	const video = streamsOf(title, 'video')[0];
	const audio = streamsOf(title, 'audio');
	return {
		source: title.source_name ?? null,
		video: video ? joined([video.codec, video.resolution]) || null : null,
		audio: audio.length ? audio.map(audioLabel) : (title.audio_languages ?? []),
		subtitles: streamsOf(title, 'subtitle').map(subtitleLabel),
		chapters: title.chapter_count ?? null,
		segments: title.segment_map ?? null
	};
}
