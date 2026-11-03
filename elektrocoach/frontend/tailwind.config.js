/** @type {import('tailwindcss').Config} */
export default {
  // Dunkle Betriebsart folgt der Klasse `dark` am Wurzelelement. Diese Klasse
  // wird aus der Home-Assistant-Einstellung abgeleitet (siehe src/theme.ts),
  // nicht aus der Betriebssystem-Einstellung des Browsers.
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Die Grundfarben (Flächen, Text, Rahmen) liegen als CSS-Variablen vor.
        // Dadurch folgen alle vorhandenen Klassen (bg-white, text-ink-900 …)
        // automatisch der hellen oder dunklen Betriebsart, ohne dass jede
        // Stelle einzeln angepasst werden muss. Die Werte stehen in index.css.
        white: "rgb(var(--c-white) / <alpha-value>)",
        // Helles, dezentes Farbschema mit Elektro-Akzent.
        brand: {
          50: "rgb(var(--c-brand-50) / <alpha-value>)",
          100: "rgb(var(--c-brand-100) / <alpha-value>)",
          200: "rgb(var(--c-brand-200) / <alpha-value>)",
          300: "rgb(var(--c-brand-300) / <alpha-value>)",
          400: "rgb(var(--c-brand-400) / <alpha-value>)",
          500: "rgb(var(--c-brand-500) / <alpha-value>)",
          600: "rgb(var(--c-brand-600) / <alpha-value>)",
          700: "rgb(var(--c-brand-700) / <alpha-value>)",
          800: "rgb(var(--c-brand-800) / <alpha-value>)",
          900: "rgb(var(--c-brand-900) / <alpha-value>)",
          950: "rgb(var(--c-brand-950) / <alpha-value>)",
        },
        accent: {
          50: "#fff8ed",
          100: "#ffefd4",
          200: "#ffdba8",
          300: "#ffc070",
          400: "#ff9b37",
          500: "#ff7d10",
          600: "#f05f06",
          700: "#c74607",
          800: "#9e370e",
          900: "#7f2f0f",
        },
        ink: {
          50: "rgb(var(--c-ink-50) / <alpha-value>)",
          100: "rgb(var(--c-ink-100) / <alpha-value>)",
          200: "rgb(var(--c-ink-200) / <alpha-value>)",
          300: "rgb(var(--c-ink-300) / <alpha-value>)",
          400: "rgb(var(--c-ink-400) / <alpha-value>)",
          500: "rgb(var(--c-ink-500) / <alpha-value>)",
          600: "rgb(var(--c-ink-600) / <alpha-value>)",
          700: "rgb(var(--c-ink-700) / <alpha-value>)",
          800: "rgb(var(--c-ink-800) / <alpha-value>)",
          900: "rgb(var(--c-ink-900) / <alpha-value>)",
        },
        success: "#12a150",
        warning: "#d97706",
        danger: "#dc2626",
      },
      fontFamily: {
        sans: [
          "Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto",
          "Helvetica Neue", "Arial", "sans-serif",
        ],
        mono: ["JetBrains Mono", "SFMono-Regular", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.06)",
        lift: "0 8px 24px rgba(16,24,40,0.10)",
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.125rem",
      },
    },
  },
  plugins: [],
};
