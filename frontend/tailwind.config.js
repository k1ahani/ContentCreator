/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Vazirmatn", "Tahoma", "Segoe UI", "sans-serif"],
        mono: ["Consolas", "monospace"],
      },
      colors: {
        brand: {
          50: "#f0f5ff",
          100: "#dce8ff",
          200: "#b9d1ff",
          300: "#8bb0ff",
          400: "#5c86ff",
          500: "#3b63f5",
          600: "#2a47d6",
          700: "#2338ab",
          800: "#212f87",
          900: "#1f2a6b",
        },
      },
    },
  },
  plugins: [],
};
