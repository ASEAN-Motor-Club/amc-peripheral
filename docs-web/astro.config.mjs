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
					label: 'Economy & Treasury',
					items: [
						{ label: 'Overview', slug: 'economy' },
						{ label: 'Fiscal Policy', slug: 'economy/fiscal-policy' },
					],
				},
				{
					label: 'Jobs & Industry',
					items: [
						{ label: 'Delivery Jobs', slug: 'jobs/delivery-jobs' },
						{ label: 'Subsidies', slug: 'jobs/subsidies' },
						{ label: 'Supply Chain Events', slug: 'jobs/supply-chain' },
					],
				},
				{
					label: 'Welfare',
					items: [
						{ label: 'Universal Basic Income', slug: 'welfare/ubi' },
						{ label: 'Government Employees', slug: 'welfare/gov-employees' },
					],
				},
				{
					label: 'Money & Banking',
					items: [
						{ label: 'Bank Interest', slug: 'banking/interest' },
						{ label: 'Loans', slug: 'banking/loans' },
						{ label: 'Credit Score', slug: 'banking/credit-score' },
					],
				},
				{
					label: 'Law & Order',
					items: [
						{ label: 'Overview', slug: 'justice' },
						{ label: 'Money Laundering', slug: 'justice/money-laundering' },
						{ label: 'Playing a criminal', slug: 'justice/criminals' },
						{ label: 'Serving as police', slug: 'justice/police' },
					],
				},
				{
					label: 'Reference',
					items: [
						{ label: 'Mods & Downloads', slug: 'mods' },
						{ label: 'Reports & Statistics', slug: 'reports' },
						{ label: 'Q1 2026 Economic Activity', slug: 'reports/q1-2026-economic-activity' },
					],
				},
			],
		}),
	],
});
