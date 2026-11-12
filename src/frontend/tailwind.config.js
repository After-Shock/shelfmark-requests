/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      // Brand tokens live as CSS variables in src/styles.css
      colors: {
        primary: { DEFAULT: 'var(--primary-color)', hover: 'var(--primary-hover)' },
        accent: {
          DEFAULT: 'rgb(var(--accent-rgb) / <alpha-value>)',
          hover: 'var(--accent-hover)',
          light: 'var(--accent-light)',
          muted: 'var(--accent-muted)',
          'muted-strong': 'var(--accent-muted-strong)',
        },
      },
    },
  },
  plugins: [],
}
