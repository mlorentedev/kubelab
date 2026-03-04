export interface SocialLink {
  name: string;
  url: string;
  icon: string;
}

export const social: SocialLink[] = [
  { name: 'GitHub', url: 'https://github.com/mlorentedev', icon: 'github' },
  { name: 'LinkedIn', url: 'https://linkedin.com/in/manuellorente', icon: 'linkedin' },
  { name: 'X', url: 'https://x.com/mlorentedev', icon: 'x' },
  { name: 'YouTube', url: 'https://youtube.com/@cubernautas', icon: 'youtube' },
  { name: 'Cal.com', url: 'https://cal.com/mlorentedev', icon: 'calendar' },
  { name: 'Email', url: 'mailto:hello@mlorente.dev', icon: 'mail' },
];
