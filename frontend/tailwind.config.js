/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['system-ui', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', '"Cascadia Code"', '"SF Mono"', 'Consolas', 'monospace'],
      },
      colors: {
        // Single warm accent — honey / "on air". Remapped from the old generic
        // blue so every existing `primary-*` utility adopts the new identity.
        primary: {
          50: '#FBF4E7',
          100: '#F5E3C4',
          200: '#EBC98C',
          300: '#E0AE55',
          400: '#D6982F',
          500: '#C67E15',
          600: '#AC6D12',
          700: '#8C570F',
          800: '#6E440C',
          900: '#513209',
        },
        accent: {
          DEFAULT: '#C67E15',
          bright: '#E1932B',
        },
        // Cool indigo-slate neutrals that sit against the warm accent.
        ink: {
          50: '#F5F6F9',
          100: '#EDEEF2',
          200: '#E1E3EA',
          300: '#CFD2DC',
          400: '#9096A6',
          500: '#5C6070',
          600: '#40444F',
          700: '#2A2E3B',
          800: '#1E212C',
          900: '#12131A',
        },
      },
    },
  },
  plugins: [],
}
