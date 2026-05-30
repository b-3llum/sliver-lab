/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0d10",
        panel: "#11151a",
        panel2: "#161b22",
        border: "#1f262e",
        muted: "#5b6672",
        text: "#d7dde3",
        accent: "#22c55e",
        accent2: "#38bdf8",
        warn: "#f59e0b",
        danger: "#ef4444",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
