import { ui, defaultLang, type Lang } from './ui';

export function getLangFromUrl(url: URL): Lang {
  const [, lang] = url.pathname.split('/');
  if (lang in ui) return lang as Lang;
  return defaultLang;
}

export function getLocale(currentLocale: string | undefined): Lang {
  if (currentLocale && currentLocale in ui) return currentLocale as Lang;
  return defaultLang;
}

export function useTranslations(lang: Lang) {
  return function t(key: keyof (typeof ui)[typeof defaultLang]) {
    return ui[lang]?.[key] ?? ui[defaultLang][key];
  };
}

export function useTranslatedPath(lang: Lang) {
  return function translatePath(path: string, l: Lang = lang) {
    return l === defaultLang ? path : `/${l}${path}`;
  };
}

export function getDateLocale(lang: Lang): string {
  return lang === 'es' ? 'es-ES' : 'en-US';
}

export function switchLangUrl(url: URL, targetLang: Lang): string {
  const currentLang = getLangFromUrl(url);
  const pathname = url.pathname;

  if (currentLang === defaultLang) {
    return targetLang === defaultLang ? pathname : `/${targetLang}${pathname}`;
  }

  const withoutLang = pathname.replace(`/${currentLang}`, '') || '/';
  return targetLang === defaultLang ? withoutLang : `/${targetLang}${withoutLang}`;
}
