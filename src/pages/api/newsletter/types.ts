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