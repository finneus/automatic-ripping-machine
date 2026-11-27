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
		const box = screen.getByTestId('track-source-details');
		expect(box).toHaveTextContent('Source00800.mpls');
		expect(box).toHaveTextContent('VideoHEVC 3840x2160');
		expect(box).toHaveTextContent('Audioeng TrueHD 7.1 · deu DD+ 5.1');
		expect(box).toHaveTextContent('Subtitlesdeu (forced)');
		expect(box).toHaveTextContent('Chapters26');
		expect(box).toHaveTextContent('Segments55,56');
	});

	it('leaves out what the scan does not know', () => {
		renderComponent(TrackSourceDetails, { props: { title: { index: 0, duration_seconds: 60 } as ScanTitle } });
		expect(screen.getByTestId('track-source-details')).toBeEmptyDOMElement();
	});
});
