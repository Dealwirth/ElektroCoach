/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Helles, dezentes Farbschema mit Elektro-Akzent.
        brand: {
          50: "#eef7ff",
          100: "#d9edff",
          200: "#bce0ff",
          300: "#8ecdff",
          400: "#59b0ff",
          500: "#338fff",
          600: "#1b6ff5",
          700: "#1458e1",
          800: "#1748b6",
          900: "#19408f",
          950: "#142857",
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
          50: "#f7f8fa",
          100: "#eef0f4",
          200: "#d9dde5",
          300: "#b8bfcd",
          400: "#8f9aae",
          500: "#6b778f",
          600: "#525c72",
          700: "#3f4759",
          800: "#2b3141",
          900: "#1c2130",
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
