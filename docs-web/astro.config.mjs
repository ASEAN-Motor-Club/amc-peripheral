// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
	site: 'https://docs.aseanmotorclub.com',
	integrations: [
		starlight({
			title: 'AMC Docs',
			description: 'Documentation for the ASEAN Motor Club community servers.',
			social: [
				{
					icon: 'github',
					label: 'GitHub',
					href: 'https://github.com/ASEAN-Motor-Club',
				},
			],
			sidebar: [
				{
					label: 'Cops & Criminals',
					items: [
						// Each item here is one entry in the navigation menu.
						{ label: 'Overview', slug: 'cops-criminals' },
					],
				},
			],
		}),
	],
});
