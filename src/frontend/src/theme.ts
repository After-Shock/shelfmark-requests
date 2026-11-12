// Brand colours for inline styles. Values are CSS variables defined in styles.css;
// in classNames prefer the Tailwind tokens (bg-accent, hover:bg-accent-hover, bg-primary, ...).
export const theme = {
  primary: {
    purple: 'var(--primary-color)',
    purpleDark: 'var(--primary-dark)',
    turquoise: 'var(--accent)',
    turquoiseDark: 'var(--accent-hover)',
    turquoiseLight: 'var(--accent-light)',
  },
  button: {
    primary: 'var(--primary-color)',
    primaryHover: 'var(--primary-hover)',
    secondary: 'var(--accent)',
    secondaryHover: 'var(--accent-hover)',
  },
};
