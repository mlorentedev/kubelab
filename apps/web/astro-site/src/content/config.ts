import { glob } from 'astro/loaders';
import { defineCollection, z } from 'astro:content';

const projects = defineCollection({
  loader: glob({ base: './src/content/projects', pattern: '**/*.{md,mdx}' }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    pubDate: z.coerce.date(),
    updatedDate: z.coerce.date().optional(),
    heroImage: z.string().optional(),
    pdf_url: z.string().optional(),
    video_url: z.string().optional(),
    lang: z.string().optional(),
    githubRepo: z.string().optional(),
    tags: z.array(z.string()).default([]),
    level: z.enum(['beginner', 'intermediate', 'advanced']).optional(),
  }),
});

const resources = defineCollection({
  schema: z.object({
    title: z.string(),
    description: z.string(),
    pubDate: z.coerce.date(),
    resourceId: z.string(),
    fileId: z.string(),
    tags: z.array(z.string()).default([]),
    buttonText: z.string().default('📩 MÁNDAMELO'),
  }),
});

export const collections = {
  projects: projects,
  resources: resources,
};
