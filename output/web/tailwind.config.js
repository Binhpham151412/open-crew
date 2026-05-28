/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Core semantic colors
        primary: {
          DEFAULT: "#2563EB",
          50: "#EFF6FF",
          100: "#DBEAFE",
          200: "#BFDBFE",
          300: "#93C5FD",
          400: "#60A5FA",
          500: "#3B82F6",
          600: "#2563EB",
          700: "#1D4ED8",
          800: "#1E40AF",
          900: "#1E3A8A",
          950: "#172554",
        },
        success: {
          DEFAULT: "#16A34A",
          50: "#F0FDF4",
          100: "#DCFCE7",
          200: "#BBF7D0",
          300: "#86EFAC",
          400: "#4ADE80",
          500: "#22C55E",
          600: "#16A34A",
          700: "#15803D",
          800: "#166534",
          900: "#14532D",
          950: "#052E16",
        },
        warning: {
          DEFAULT: "#D97706",
          50: "#FFFBEB",
          100: "#FEF3C7",
          200: "#FDE68A",
          300: "#FCD34D",
          400: "#FBBF24",
          500: "#F59E0B",
          600: "#D97706",
          700: "#B45309",
          800: "#92400E",
          900: "#78350F",
          950: "#451A03",
        },
        danger: {
          DEFAULT: "#DC2626",
          50: "#FEF2F2",
          100: "#FEE2E2",
          200: "#FECACA",
          300: "#FCA5A5",
          400: "#F87171",
          500: "#EF4444",
          600: "#DC2626",
          700: "#B91C1C",
          800: "#991B1B",
          900: "#7F1D1D",
          950: "#450A0A",
        },
        // Surface / background palette (dark mode default)
        bg: "#0F172A",
        surface: "#1E293B",
        text: "#F8FAFC",
        muted: "#94A3B8",
        // Slate overrides for shadcn/ui compatibility
        border: "#334155",
        input: "#334155",
        ring: "#2563EB",
        background: "#0F172A",
        foreground: "#F8FAFC",
        card: {
          DEFAULT: "#1E293B",
          foreground: "#F8FAFC",
        },
        popover: {
          DEFAULT: "#1E293B",
          foreground: "#F8FAFC",
        },
        secondary: {
          DEFAULT: "#1E293B",
          foreground: "#F8FAFC",
        },
        accent: {
          DEFAULT: "#334155",
          foreground: "#F8FAFC",
        },
        destructive: {
          DEFAULT: "#DC2626",
          foreground: "#F8FAFC",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        heading: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "SF Mono", "Menlo", "Consolas", "Liberation Mono", "monospace"],
      },
      fontSize: {
        "heading-1": ["1.875rem", { lineHeight: "2.25rem", fontWeight: "600" }],
        "heading-2": ["1.5rem", { lineHeight: "2rem", fontWeight: "600" }],
        "heading-3": ["1.25rem", { lineHeight: "1.75rem", fontWeight: "600" }],
        "heading-4": ["1.125rem", { lineHeight: "1.75rem", fontWeight: "600" }],
        body: ["0.875rem", { lineHeight: "1.25rem", fontWeight: "400" }],
        "body-lg": ["1rem", { lineHeight: "1.5rem", fontWeight: "400" }],
        "body-sm": ["0.8125rem", { lineHeight: "1.125rem", fontWeight: "400" }],
        caption: ["0.75rem", { lineHeight: "1rem", fontWeight: "400" }],
      },
      spacing: {
        // 4px grid system: 4, 8, 12, 16, 24, 32, 48
        4.5: "1.125rem",
        13: "3.25rem",
        15: "3.75rem",
        18: "4.5rem",
        88: "22rem",
        "sidebar": "16rem",
        "sidebar-collapsed": "4rem",
      },
      borderRadius: {
        card: "0.5rem",     // 8px — cards
        button: "0.25rem",  // 4px — buttons, inputs
        lg: "0.5rem",
        md: "calc(0.5rem - 2px)",
        sm: "calc(0.5rem - 4px)",
      },
      boxShadow: {
        "card": "0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)",
        "card-hover": "0 4px 6px -1px rgb(0 0 0 / 0.15), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
        "glow-primary": "0 0 12px 2px rgb(37 99 235 / 0.25)",
        "glow-success": "0 0 12px 2px rgb(22 163 74 / 0.25)",
        "glow-warning": "0 0 12px 2px rgb(217 119 6 / 0.25)",
        "glow-danger": "0 0 12px 2px rgb(220 38 38 / 0.25)",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.2s ease-out",
        "fade-out": "fadeOut 0.2s ease-in",
        "slide-in-right": "slideInRight 0.3s ease-out",
        "slide-in-up": "slideInUp 0.3s ease-out",
        "spin-slow": "spin 3s linear infinite",
        "status-ping": "statusPing 1.5s cubic-bezier(0, 0, 0.2, 1) infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        fadeOut: {
          "0%": { opacity: "1" },
          "100%": { opacity: "0" },
        },
        slideInRight: {
          "0%": { transform: "translateX(100%)", opacity: "0" },
          "100%": { transform: "translateX(0)", opacity: "1" },
        },
        slideInUp: {
          "0%": { transform: "translateY(10px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        statusPing: {
          "75%, 100%": { transform: "scale(2)", opacity: "0" },
        },
      },
      transitionDuration: {
        250: "250ms",
      },
      transitionTimingFunction: {
        "bounce-in": "cubic-bezier(0.68, -0.55, 0.265, 1.55)",
      },
      backdropBlur: {
        xs: "2px",
      },
      containers: {
        "2xs": "16rem",
      },
    },
  },
  plugins: [
    require("@tailwindcss/container-queries"),
    require("tailwindcss-animate"),
    // Custom plugin for design-system utilities
    function ({ addUtilities, theme }) {
      const colors = theme("colors");

      addUtilities({
        // Status dot utilities
        ".status-online": {
          backgroundColor: typeof colors.success === "object" ? colors.success.DEFAULT : colors.success,
          boxShadow: `0 0 6px 1px ${typeof colors.success === "object" ? colors.success.DEFAULT : colors.success}66`,
        },
        ".status-offline": {
          backgroundColor: typeof colors.muted === "string" ? colors.muted : "#94A3B8",
        },
        ".status-working": {
          backgroundColor: typeof colors.warning === "object" ? colors.warning.DEFAULT : colors.warning,
          boxShadow: `0 0 6px 1px ${typeof colors.warning === "object" ? colors.warning.DEFAULT : colors.warning}66`,
          animation: "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        },
        ".status-error": {
          backgroundColor: typeof colors.danger === "object" ? colors.danger.DEFAULT : colors.danger,
          boxShadow: `0 0 6px 1px ${typeof colors.danger === "object" ? colors.danger.DEFAULT : colors.danger}66`,
        },
        // Log level color utilities
        ".log-info": {
          color: typeof colors.primary === "object" ? colors.primary[400] : "#60A5FA",
        },
        ".log-warn": {
          color: typeof colors.warning === "object" ? colors.warning[400] : "#FBBF24",
        },
        ".log-error": {
          color: typeof colors.danger === "object" ? colors.danger[400] : "#F87171",
        },
        ".log-debug": {
          color: typeof colors.muted === "string" ? colors.muted : "#94A3B8",
        },
        // Scrollbar styling for dark theme
        ".scrollbar-thin": {
          scrollbarWidth: "thin",
          scrollbarColor: `${typeof colors.border === "string" ? colors.border : "#334155"} transparent",
          "&::-webkit-scrollbar": {
            width: "6px",
            height: "6px",
          },
          "&::-webkit-scrollbar-track": {
            background: "transparent",
          },
          "&::-webkit-scrollbar-thumb": {
            backgroundColor: typeof colors.border === "string" ? colors.border : "#334155",
            borderRadius: "3px",
          },
          "&::-webkit-scrollbar-thumb:hover": {
            backgroundColor: typeof colors.muted === "string" ? colors.muted : "#94A3B8",
          },
        },
        // Glass morphism card
        ".glass": {
          backgroundColor: "rgba(30, 41, 59, 0.8)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(51, 65, 85, 0.5)",
        },
        // Mono text for code/logs
        ".font-log": {
          fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace",
          fontSize: "0.8125rem",
          lineHeight: "1.25rem",
        },
      });
    },
  ],
};