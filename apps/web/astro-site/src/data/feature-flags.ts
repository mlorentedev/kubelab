import { env } from '../data/env';

export const featureFlags = {
  enableHomelabs: env.FEATURE_FLAGS.ENABLE_HOMELABS,
  enableBlog: env.FEATURE_FLAGS.ENABLE_BLOG,
  enableContact: env.FEATURE_FLAGS.ENABLE_CONTACT,
};
