export const env = {
  SITE: {
    TITLE: import.meta.env.PUBLIC_SITE_TITLE,
    DESCRIPTION: import.meta.env.PUBLIC_SITE_DESCRIPTION,
    DOMAIN: import.meta.env.PUBLIC_SITE_DOMAIN,
    URL: import.meta.env.PUBLIC_SITE_URL,
    MAIL: import.meta.env.PUBLIC_SITE_MAIL,
    AUTHOR: import.meta.env.PUBLIC_SITE_AUTHOR,
    KEYWORDS: import.meta.env.PUBLIC_SITE_KEYWORDS,
  },
  RRSS: {
    TWITTER: import.meta.env.PUBLIC_TWITTER_URL,
    YOUTUBE: import.meta.env.PUBLIC_YOUTUBE_URL,
    GITHUB: import.meta.env.PUBLIC_GITHUB_URL,
    CALENDLY: import.meta.env.PUBLIC_CALENDLY_URL,
    BUY_ME_A_COFFEE: import.meta.env.PUBLIC_BUY_ME_A_COFFEE_URL,
  },
  ANALYTICS: {
    GOOGLE_ID: import.meta.env.PUBLIC_GOOGLE_ANALYTICS_ID,
  },
  FEATURE_FLAGS: {
    ENABLE_HOMELABS: import.meta.env.PUBLIC_ENABLE_HOMELABS,
    ENABLE_BLOG: import.meta.env.PUBLIC_ENABLE_BLOG,
    ENABLE_CONTACT: import.meta.env.PUBLIC_ENABLE_CONTACT,
  },
  API: {
    BACKEND_URL: import.meta.env.BACKEND_URL,
  },
};
