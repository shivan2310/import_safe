/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: { DEFAULT: "#12203F", 700: "#1c2f57", 50: "#eef1f7" },
      },
    },
  },
  plugins: [],
};
