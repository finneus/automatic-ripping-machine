import { describe, it, expect, afterEach } from 'vitest';
import { renderComponent, screen, cleanup } from '$lib/testing/render';
import TrackSourceDetails from '../TrackSourceDetails.svelte';
import type { ScanStream, ScanTitle } from '$lib/types/api.gen';

afterEach(cleanup);

const full = {
	index: 3,
	duration_seconds: 8286,
	chapter_count: 26,
	source_name: '00800.mpls',
	segment_map: '55,56',
	streams: [
		{ kind: 'video', codec: 'HEVC', resolution: '3840x2160' },
		{ kind: 'audio', language: 'eng', codec: 'TrueHD', channels: '7.1' },
		{ kind: 'audio', language: 'deu', codec: 'DD+', channels: '5.1' },
		{ kind: 'subtitle', language: 'deu', forced: true }
	] as ScanStream[]
} as ScanTitle;

describe('TrackSourceDetails', () => {
	it('lists every detail of the title', () => {
		renderComponent(TrackSourceDetails, { props: { title: full } });
		const rows = [...screen.getByTestId('track-source-details').querySelectorAll('div')].map((row) => [
			row.querySelector('dt')?.textContent,
			row.querySelector('dd')?.textContent
		]);
		expect(rows).toEqual([
			['Source', '00800.mpls'],
			['Video', 'HEVC 3840x2160'],
			['Audio', 'eng TrueHD 7.1, deu DD+ 5.1'],
			['Subtitles', 'deu (forced)'],
			['Chapters', '26'],
			['Segments', '55,56']
		]);
	});

	it('leaves out what the scan does not know', () => {
		renderComponent(TrackSourceDetails, { props: { title: { index: 0, duration_seconds: 60 } as ScanTitle } });
		expect(screen.getByTestId('track-source-details').querySelectorAll('div')).toHaveLength(0);
	});
});
