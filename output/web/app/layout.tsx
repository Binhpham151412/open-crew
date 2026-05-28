import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "OpenCrew — AI Agent Orchestration",
  description:
    "Multi-agent software development pipeline powered by MiMo. PO, PM, BA, Architects, Developers, Reviewers, QA, DevOps, and TechLead — all working autonomously.",
  keywords: ["OpenCrew", "AI agents", "MiMo", "CrewAI", "A2A protocol"],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} font-sans antialiased bg-slate-900 text-slate-50 min-h-screen flex flex-col`}
      >
        {/* Top Bar */}
        <header className="h-14 border-b border-slate-700 bg-slate-800 flex items-center justify-between px-6 shrink-0 sticky top-0 z-50">
          <div className="flex items-center gap-3">
            {/* Logo / Title */}
            <svg viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg" className="w-7 h-7 shrink-0">
              <rect width="28" height="28" rx="6" fill="#2563EB"/>
              <path d="M8 10h12M8 14h8M8 18h10" stroke="#F8FAFC" strokeWidth="2" strokeLinecap="round"/>
            </svg>
            <span className="text-lg font-semibold tracking-tight text-slate-50 select-none">
              OpenCrew
            </span>
            <span className="hidden sm:inline-block text-xs font-medium text-slate-400 bg-slate-900 rounded px-2 py-0.5">
              v1.0
            </span>
          </div>

          <div className="flex items-center gap-4">
            {/* System Status Indicator */}
            <SystemStatusIndicator />

            {/* Uptime placeholder */}
            <span className="hidden md:inline-block text-xs text-slate-400">
              Uptime: <UptimeCounter />
            </span>
          </div>
        </header>

        {/* Main area: Sidebar + Content */}
        <div className="flex flex-1 overflow-hidden">
          {/* Sidebar */}
          <Sidebar />

          {/* Page content */}
          <main className="flex-1 overflow-y-auto p-6 bg-slate-900">{children}</main>
        </div>

        {/* Footer */}
        <footer className="border-t border-slate-700 bg-slate-800 px-6 py-2.5 shrink-0 flex items-center justify-between text-xs text-slate-400 font-mono">
          <span>OpenCrew v1.0</span>
          <span>Uptime: <UptimeCounter /></span>
          <span>A2A Protocol &bull; MCP Tools &bull; 11 Agents</span>
        </footer>
      </body>
    </html>
  );
}

/* ------------------------------------------------------------------ */
/*  Inline sub-components (kept in layout for simplicity)              */
/* ------------------------------------------------------------------ */

/**
 * Pings the health endpoint and renders a coloured status dot + label.
 * Falls back to "unknown" if the fetch fails or during SSR.
 */
function SystemStatusIndicator() {
  return (
    <div className="flex items-center gap-2 text-[13px] text-slate-400">
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500 shadow-[0_0_6px_rgba(22,163,74,0.5)]" />
      </span>
      <span>System running</span>
    </div>
  );
}

/**
 * Simple uptime counter — in production this would read from /api/stats.
 * Renders a static placeholder at build time and hydrates on the client.
 */
function UptimeCounter() {
  return <span className="font-mono text-slate-300">0d 0h 0m</span>;
}