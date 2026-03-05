export interface SocialLink {
  name: string;
  url: string;
  icon: string;
}

export const social: SocialLink[] = [
  { name: 'GitHub', url: 'https://github.com/mlorentedev', icon: 'github' },
  { name: 'Email', url: 'mailto:info@mlorente.dev', icon: 'mail' },
];
