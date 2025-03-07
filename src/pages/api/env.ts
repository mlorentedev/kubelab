import { validateEnvironmentVariables, getEnv } from './utils';

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
};
