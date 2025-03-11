import pino from 'pino';
import pretty from 'pino-pretty';

import * as dotenv from 'dotenv';

import { z } from 'zod';

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

const prettyStream = pretty({
  colorize: true,
  ignore: 'pid,hostname',
  messageKey: 'msg',
  singleLine: true,
});

export const logger = pino(prettyStream);

export function logFunction(level: 'info' | 'warn' | 'error', message: string, data?: any) {
  const stack = new Error().stack || '';
  const functionName = stack.split('\n')[2]?.trim().split(' ')[1] || 'unknown function';
  logger[level](`${functionName}: ${message} ${data !== undefined ? JSON.stringify(data) : ''}`);
}

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
    error.errors.forEach((err: any) => {
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
