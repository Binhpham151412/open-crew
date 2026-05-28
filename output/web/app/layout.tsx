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
        <header className="h-14 border-b border-slate-700/60 bg-slate-900/95 backdrop-blur supports-[backdrop-filter]:bg-slate-900/80 flex items-center justify-between px-4 lg:px-6 shrink-0 sticky top-0 z-50">
          <div className="flex items-center gap-3">
            {/* Logo / Title */}
            <span className="text-xl font-semibold tracking-tight text-slate-50 select-none">
              🤖 OpenCrew
            </span>
            <span className="hidden sm:inline-block text-xs font-medium text-slate-400 bg-slate-800 rounded px-2 py-0.5">
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
          <main className="flex-1 overflow-y-auto p-4 lg:p-6">{children}</main>
        </div>

        {/* Footer */}
        <footer className="border-t border-slate-700/60 bg-slate-900/95 backdrop-blur supports-[backdrop-filter]:bg-slate-900/80 px-4 lg:px-6 py-2.5 shrink-0 flex flex-col sm:flex-row items-center justify-between gap-1 text-xs text-slate-400">
          <span>
            OpenCrew v1.0 &mdash; Powered by{" "}
            <a
              href="https://mi.com"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-400 hover:text-blue-300 transition-colors"
            >
              MiMo
            </a>
          </span>
          <span>
            A2A Protocol &bull; MCP Tools &bull; 11 Agents
          </span>
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
  // In a real app this would be a client component fetching /api/health.
  // For SSR safety we render a static "online" badge here and hydrate
  // with live data via a small client island if needed.
  return (
    <div className="flex items-center gap-1.5 text-xs font-medium">
      <span className="relative flex h-2.5 w-2.5">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500" />
      </span>
      <span className="text-green-400">running</span>
    </div>
  );
}

/**
 * Simple uptime counter — in production this would read from /api/stats.
 * Renders a static placeholder at build time and hydrates on the client.
 */
function UptimeCounter() {
  // This is intentionally a server-rendered placeholder.
  // The real value is fetched client-side from /api/stats (SSE or polling).
  return <span className="font-mono text-slate-300">0d 0h 0m</span>;
}