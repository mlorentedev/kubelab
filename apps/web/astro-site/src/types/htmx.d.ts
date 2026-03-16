// src/htmx.d.ts
interface HtmxConfig {
  boosted: boolean;
  historyCacheSize: number;
  refreshOnHistoryMiss: boolean;
  defaultSwapStyle: string;
  defaultSwapDelay: number;
  defaultSettleDelay: number;
  includeIndicatorStyles: boolean;
  indicatorClass: string;
  requestClass: string;
  addedClass: string;
  settlingClass: string;
  swappingClass: string;
  allowEval: boolean;
  allowScriptTags: boolean;
  inlineScriptNonce: string;
  attributesToSettle: string[];
  useTemplateFragments: boolean;
  wsConnectionDelay: number;
  wsBinaryType: string;
  disableSelector: string;
  withCredentials: boolean;
  timeout: number;
  scrollBehavior: 'auto' | 'smooth';
  defaultFocusScroll: boolean;
  getCacheBusterParam: boolean;
  globalViewTransitions: boolean;
  methodsThatUseUrlParams: string[];
  selfRequestsOnly: boolean;
  ignoreTitle: boolean;
  scrollIntoViewOnBoost: boolean;
  triggerSpecsCache: any;
  responseAttrsToInherit: string[];
}

interface HtmxExtensions {
  [key: string]: any;
}

interface HtmxInternals {
  processNode: (elt: Element) => void;
  filterValues: (arr: any[], transformer: (value: any) => any) => any[];
  getInputValues: (elt: Element, triggeringEvent?: Event) => any;
  getTarget: (elt: Element) => Element;
  getScrollLeft: () => number;
  getScrollTop: () => number;
  makeFragment: (html: string) => DocumentFragment;
  takeClass: (sourceElt: Element, targetElt: Element) => void;
  triggerEvent: (elt: Element, eventName: string, details?: any) => boolean;
  tempBeacon: { [name: string]: any };
}

interface Htmx {
  on: (eventName: string, querySelector: string, listener: (evt: Event) => void) => void;
  off: (eventName: string, querySelector: string, listener: (evt: Event) => void) => void;
  trigger: (elt: Element | string, eventName: string, details?: any) => void;
  ajax: (verb: string, path: string, args?: any) => void;
  find: (elt: Element | string, selector: string) => Element | null;
  findAll: (elt: Element | string, selector: string) => Element[];
  closest: (elt: Element | string, selector: string) => Element | null;
  remove: (elt: Element | string) => void;
  addClass: (elt: Element | string, className: string) => void;
  removeClass: (elt: Element | string, className: string) => void;
  toggleClass: (elt: Element | string, className: string) => void;
  takeClass: (elt: Element | string, className: string) => void;
  defineExtension: (name: string, extension: any) => void;
  removeExtension: (name: string) => void;
  logAll: () => void;
  logger: any;
  config: HtmxConfig;
  _: HtmxInternals;
  createEventSource: (url: string) => EventSource;
  createWebSocket: (url: string) => WebSocket;
  process: (elt?: Element) => void;
  processNode: (node: Element) => void;
  version: string;
  internalEval: (str: string) => any;
  onLoad: (callback: (elt: Element) => void) => void;
  historyEnabled: boolean;
  createHistoryElement: (id: string) => Element;
  setHistoryData: (id: string) => void;
  getHistoryElement: () => Element;
  pushUrlIntoHistory: (url: string) => void;
  boosted: boolean;
  refresh: (elt: Element) => void;
  extensions: HtmxExtensions;
}

declare global {
  interface Window {
    htmx: Htmx;
  }
  const htmx: Htmx;
}

export {};
