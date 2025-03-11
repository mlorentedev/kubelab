import { ENV } from './env';

export const featureFlags = {
    enableHomelabs: ENV.FEATURE_FLAGS.ENABLE_HOMELABS,
    enableBlog: ENV.FEATURE_FLAGS.ENABLE_BLOG,
    enableContact: ENV.FEATURE_FLAGS.ENABLE_CONTACT,
};