export enum Tag {
    NewSubscriber = "new",
    ExistingSubscriber = "existing",
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
  
  export interface ApiResponse {
    message: string;
    already_subscribed?: boolean;
  }

  // Add this type definition near the top
export type Resource = {
  id: string;
  title: string;
  description: string;
  fileId: string;
  tags: string[];
};

export type ResourceMap = {
  [key: string]: Resource;
};