/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"Fira Code"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
        sans: ['"Inter var"', 'system-ui', 'sans-serif'],
      },
      colors: {
        brand: {
          50: '#eef2ff',
          100: '#dbe1f1',
          200: '#bfc9ed',
          300: '#9fb1e3',
          400: '#7d95d6',
          500: '#5b7ac8',
          600: '#4c63b6',
          700: '#3f519c',
          800: '#33417c',
          900: '#253159',
        },
      },
    },
  },
  plugins: [],
}
