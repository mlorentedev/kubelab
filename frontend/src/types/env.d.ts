/// <reference types="astro/client" />

interface ImportMetaEnv {
  readonly PUBLIC_SITE_TITLE: string;
  readonly PUBLIC_SITE_DESCRIPTION: string;
  readonly PUBLIC_SITE_DOMAIN: string;
  readonly PUBLIC_SITE_URL: string;
  readonly PUBLIC_SITE_MAIL: string;
  readonly PUBLIC_SITE_AUTHOR: string;
  readonly PUBLIC_SITE_KEYWORDS: string;

  readonly PUBLIC_TWITTER_URL: string;
  readonly PUBLIC_YOUTUBE_URL: string;
  readonly PUBLIC_GITHUB_URL: string;
  readonly PUBLIC_CALENDLY_URL: string;
  readonly PUBLIC_BUY_ME_A_COFFEE_URL: string;

  readonly PUBLIC_GOOGLE_ANALYTICS_ID: string;

  readonly PUBLIC_ENABLE_HOMELABS: boolean;
  readonly PUBLIC_ENABLE_BLOG: boolean;
  readonly PUBLIC_ENABLE_CONTACT: boolean;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
