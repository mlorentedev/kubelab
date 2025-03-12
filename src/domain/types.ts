/* eslint-disable @typescript-eslint/no-explicit-any */
export enum Tag {
  NewSubscriber = 'new',
  ExistingSubscriber = 'existing',
}

export type ResourceTitles = {
  [key: string]: string;
};

export enum SubscriptionSource {
  LandingPage = 'landing_page',
  LeadMagnet = 'lead_magnet',
  Newsletter = 'newsletter',
}

export enum SubscriptionTag {
  NewSubscriber = 'new',
  ExistingSubscriber = 'existing',
}

export interface ApiResponse {
  message: string;
  already_subscribed?: boolean;
}

export interface GetSubscriber {
  id: string;
  email: string;
  tags: string[];
  [key: string]: any;
}

export interface CreateSubscriber {
  id: string;
  email: string;
  [key: string]: any;
}

export interface SubscriptionResult {
  success: boolean;
  message: string;
  subscriberId?: string;
  alreadySubscribed?: boolean;
}

export interface ResourceRequest {
  email: string;
  resourceId: string;
  fileId: string;
  tags?: string[];
  utmSource?: SubscriptionSource;
}
