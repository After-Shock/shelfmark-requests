import { useEffect, useSyncExternalStore } from 'react';

// Single source of truth for the colour scheme. The preference (light/dark/auto) lives in
// localStorage under 'preferred-theme' (also read by the pre-paint script in index.html);
// the resolved scheme is written to <html data-theme>, which CSS tokens and dark: variants key off.
export type ThemePreference = 'light' | 'dark' | 'auto';
const STORAGE_KEY = 'preferred-theme';

const systemDark = () => window.matchMedia('(prefers-color-scheme: dark)');

export const getThemePreference = (): ThemePreference => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    // localStorage may be unavailable in private browsing
  }
  return 'auto';
};

export const setThemePreference = (pref: ThemePreference): void => {
  try {
    localStorage.setItem(STORAGE_KEY, pref);
    localStorage.removeItem('app-theme'); // retired key from the old header toggle
  } catch {
    // ignore
  }
  const resolved = pref === 'auto' ? (systemDark().matches ? 'dark' : 'light') : pref;
  document.documentElement.setAttribute('data-theme', resolved);
};

const subscribe = (cb: () => void) => {
  const mo = new MutationObserver(cb);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  return () => mo.disconnect();
};
const getResolved = (): 'light' | 'dark' => (document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light');

/** Resolved theme ('light' | 'dark') plus a toggle that stores an explicit preference. Mount once (App). */
export const useTheme = () => {
  const theme = useSyncExternalStore(subscribe, getResolved);

  useEffect(() => {
    setThemePreference(getThemePreference());
    // Theme is applied; enable CSS transitions (index.html adds 'preload' to avoid a flash)
    requestAnimationFrame(() => document.documentElement.classList.remove('preload'));
    // Follow OS changes while the preference is 'auto'
    const mq = systemDark();
    const onChange = () => {
      if (getThemePreference() === 'auto') setThemePreference('auto');
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const toggleTheme = () => setThemePreference(theme === 'dark' ? 'light' : 'dark');

  return { theme, toggleTheme };
};
