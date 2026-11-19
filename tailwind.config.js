/** Build-time Tailwind config (previously inlined for the CDN runtime). Run `npm run vendor`. */
module.exports = {
  content: ['./static/index.html', './static/parts/*.html', './static/js/*.js'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter Variable"', '"Segoe UI Variable Text"', '"Segoe UI"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono Variable"', '"Cascadia Mono"', 'Consolas', 'monospace'],
      },
      // the theme's colours are variables (static/styles.css :root, set by applyTheme in static/js/core.js)
      colors: {
        apple: {
          bg: 'rgb(var(--bg-rgb) / <alpha-value>)',
          sidebar: 'rgb(var(--sidebar-rgb) / <alpha-value>)',
          card: 'rgb(var(--card-rgb) / <alpha-value>)',
          elevated: 'rgb(var(--elevated-rgb) / <alpha-value>)',
          border: 'rgba(255, 255, 255, 0.08)',
          blue: 'rgb(var(--accent-rgb) / <alpha-value>)',
          blueHover: 'rgb(var(--accent-lo-rgb) / <alpha-value>)',
          red: '#FF453A',
          green: '#30D158',
          amber: '#FF9F0A',
          label: '#F5F5F7',
          secondary: '#98989D',
          tertiary: '#8A8A90',  // readable small text on the dark cards (was #636366, 2.6:1)
        },
      },
    },
  },
};
