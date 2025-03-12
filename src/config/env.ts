import * as dotenv from 'dotenv';

import { z } from 'zod';
import { logFunction } from '../utils/logging';

validateEnvironmentVariables();

export const ENV = {
  BEEHIIV: {
    API_KEY: getEnv('BEEHIIV_API_KEY'),
    PUB_ID: getEnv('BEEHIIV_PUB_ID'),
  },
  EMAIL: {
    HOST: getEnv('EMAIL_HOST'),
    PORT: getEnv('EMAIL_PORT'),
    SECURE: getEnv('EMAIL_SECURE', 'false') === 'true',
    USER: getEnv('EMAIL_USER'),
    PASS: getEnv('EMAIL_PASS'),
  },
  SITE: {
    DOMAIN: getEnv('SITE_DOMAIN'),
    URL: getEnv('SITE_URL'),
    MAIL: getEnv('SITE_MAIL'),
    TITLE: getEnv('SITE_TITLE'),
    DESCRIPTION: getEnv('SITE_DESCRIPTION'),
    KEYWORDS: getEnv('SITE_KEYWORDS'),
    AUTHOR: getEnv('SITE_AUTHOR'),
  },
  RRSS: {
    CALENDLY: getEnv('CALENDLY_URL'),
    BUY_ME_A_COFFEE: getEnv('BUY_ME_A_COFFEE_URL'),
    TWITTER: getEnv('TWITTER_URL'),
    YOUTUBE: getEnv('YOUTUBE_URL'),
    GITHUB: getEnv('GITHUB_URL'),
  },
  ANALYTICS: {
    GOOGLE_ID: getEnv('GOOGLE_ANALYTICS_ID'),
  },
  FEATURE_FLAGS: {
    ENABLE_HOMELABS: getEnv('ENABLE_HOMELABS', 'false') === 'true',
    ENABLE_BLOG: getEnv('ENABLE_BLOG', 'false') === 'true',
    ENABLE_CONTACT: getEnv('ENABLE_CONTACT', 'false') === 'true',
  },
};

const envSchema = z.object({
  BEEHIIV_API_KEY: z.string(),
  BEEHIIV_PUB_ID: z.string(),
  EMAIL_HOST: z.string(),
  EMAIL_PORT: z.string(),
  EMAIL_SECURE: z.string().optional(),
  EMAIL_USER: z.string(),
  EMAIL_PASS: z.string(),
  SITE_DOMAIN: z.string(),
  SITE_URL: z.string(),
  SITE_MAIL: z.string(),
  SITE_TITLE: z.string(),
  SITE_DESCRIPTION: z.string(),
  SITE_KEYWORDS: z.string(),
  SITE_AUTHOR: z.string(),
  CALENDLY_URL: z.string(),
  BUY_ME_A_COFFEE_URL: z.string(),
  TWITTER_URL: z.string(),
  YOUTUBE_URL: z.string(),
  GITHUB_URL: z.string(),
  GOOGLE_ANALYTICS_ID: z.string(),
});

export function validateEnvironmentVariables() {
  dotenv.config();

  try {
    envSchema.parse(process.env);
    logFunction('info', 'Environment variables are valid');
  } catch (error) {
    if (error instanceof z.ZodError) {
      handleValidationError(error);
    }
  }
}

function handleValidationError(error: z.ZodError) {
  if (error instanceof z.ZodError) {
    console.error('Validation error:', error.errors);
    console.error('Invalid environment variables:');
    error.errors.forEach((err) => {
      console.error(`- ${err.path.join('.')} is invalid: ${err.message}`);
    });
    throw new Error('Invalid environment variables');
  } else {
    console.error('Unexpected error:', error);
  }
  throw error;
}

export function getEnv(key: string, defaultValue?: string): string {
  const value = process.env[key];
  if (!value && !defaultValue) {
    throw new Error(`Environment variable ${key} is not set.`);
  }
  return value || defaultValue!;
}
