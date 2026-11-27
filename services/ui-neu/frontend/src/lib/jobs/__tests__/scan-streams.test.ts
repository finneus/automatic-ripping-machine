import { describe, expect, it } from 'vitest';
import { audioLabel, scanTitleAt, scanTitlesOf, subtitleLabel, titleDetails } from '$lib/jobs/scan-streams';
import type { ScanStream, ScanTitle } from '$lib/types/api.gen';

const audio = (over: Partial<ScanStream>): ScanStream => ({ kind: 'audio', ...over }) as ScanStream;

const variant: ScanTitle = {
	index: 3,
	duration_seconds: 8286,
	chapter_count: 26,
	source_name: '00800.mpls',
	segment_map: '55,56',
	audio_languages: ['eng', 'deu'],
	streams: [
		{ kind: 'video', codec: 'HEVC', resolution: '3840x2160' },
		{ kind: 'audio', language: 'eng', codec: 'TrueHD', channels: '7.1' },
		{ kind: 'audio', language: 'deu', codec: 'DD+', channels: '5.1' },
		{ kind: 'subtitle', language: 'deu', forced: true },
		{ kind: 'subtitle', language: 'eng' }
	] as ScanStream[]
} as ScanTitle;

describe('scanTitlesOf', () => {
	it('reads the scanned titles from job metadata', () => {
		expect(scanTitlesOf({ scan_result: { titles: [variant] } })).toEqual([variant]);
	});

	it('is empty without metadata, a scan or a title list', () => {
		expect(scanTitlesOf(null)).toEqual([]);
		expect(scanTitlesOf('x')).toEqual([]);
		expect(scanTitlesOf({})).toEqual([]);
		expect(scanTitlesOf({ scan_result: 'x' })).toEqual([]);
		expect(scanTitlesOf({ scan_result: { titles: 'x' } })).toEqual([]);
	});
});

describe('scanTitleAt', () => {
	it('finds the title with the track index, not the list position', () => {
		expect(scanTitleAt([{ ...variant, index: 0 }, variant], 3)).toBe(variant);
		expect(scanTitleAt([variant], 9)).toBeUndefined();
	});
});

describe('labels', () => {
	it('names an audio stream by language, codec and channels, and marks a commentary', () => {
		expect(audioLabel(audio({ language: 'eng', codec: 'TrueHD', channels: '7.1' }))).toBe('eng TrueHD 7.1');
		expect(audioLabel(audio({ language: 'eng', codec: 'AC3', commentary: true }))).toBe('eng AC3 (commentary)');
		expect(audioLabel(audio({}))).toBe('?');
	});

	it('names a subtitle by language and marks a forced one', () => {
		expect(subtitleLabel({ kind: 'subtitle', language: 'deu', forced: true } as ScanStream)).toBe('deu (forced)');
		expect(subtitleLabel({ kind: 'subtitle' } as ScanStream)).toBe('?');
	});
});

describe('titleDetails', () => {
	it('lists source, picture, audio, subtitles, chapters and segments', () => {
		expect(titleDetails(variant)).toEqual({
			source: '00800.mpls',
			video: 'HEVC 3840x2160',
			audio: ['eng TrueHD 7.1', 'deu DD+ 5.1'],
			subtitles: ['deu (forced)', 'eng'],
			chapters: 26,
			segments: '55,56'
		});
	});

	it('falls back to the audio languages for a scan without streams', () => {
		const old = { index: 0, duration_seconds: 60, audio_languages: ['eng'] } as ScanTitle;
		expect(titleDetails(old)).toEqual({
			source: null,
			video: null,
			audio: ['eng'],
			subtitles: [],
			chapters: null,
			segments: null
		});
		expect(titleDetails({ index: 0, duration_seconds: 60 } as ScanTitle).audio).toEqual([]);
	});

	it('leaves the picture out when the video stream reports nothing', () => {
		const bare = { ...variant, streams: [{ kind: 'video' }] as ScanStream[] };
		expect(titleDetails(bare).video).toBeNull();
	});
});
