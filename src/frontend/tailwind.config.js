/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0E1117",
        surface: "#161B22",
        border: "#30363D",
        primary: "#3b82f6",
        text: "#C9D1D9",
        heading: "#E6EDF3",
        danger: "#da3633",
        success: "#2ea043"
      }
    },
  },
  plugins: [],
}
