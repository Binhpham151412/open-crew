"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  ListTodo,
  Bot,
  Settings,
  ScrollText,
  Info,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NavItem {
  label: string;
  href: string;
  icon: React.ElementType;
  group: "main" | "system";
}

// ---------------------------------------------------------------------------
// Navigation definition
// ---------------------------------------------------------------------------

const navItems: NavItem[] = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard, group: "main" },
  { label: "Tasks", href: "/tasks", icon: ListTodo, group: "main" },
  { label: "Agents", href: "/agents", icon: Bot, group: "main" },
  { label: "Config", href: "/config", icon: Settings, group: "main" },
  { label: "Logs", href: "/logs", icon: ScrollText, group: "system" },
  { label: "About", href: "/about", icon: Info, group: "system" },
];

// ---------------------------------------------------------------------------
// localStorage key
// ---------------------------------------------------------------------------

const STORAGE_KEY = "opencrew:sidebar:collapsed";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Sidebar() {
  const pathname = usePathname();

  // ---------- collapse state (persisted) ----------
  const [collapsed, setCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored !== null) {
        setCollapsed(stored === "true");
      }
    } catch {
      // localStorage unavailable — default to expanded
    }
  }, []);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, String(next));
      } catch {
        // ignore
      }
      return next;
    });
  }, []);

  // ---------- helpers ----------
  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  // ---------- render groups ----------
  const mainItems = navItems.filter((i) => i.group === "main");
  const systemItems = navItems.filter((i) => i.group === "system");

  // Avoid hydration mismatch: render nothing until mounted
  if (!mounted) {
    return (
      <aside
        className="shrink-0 bg-slate-900 border-r border-slate-700/60 flex flex-col"
        style={{ width: 240 }}
        aria-label="Sidebar navigation"
      />
    );
  }

  return (
    <aside
      className={`
        shrink-0 bg-slate-900 border-r border-slate-700/60
        flex flex-col transition-[width] duration-200 ease-in-out
        overflow-hidden select-none
      `}
      style={{ width: collapsed ? 64 : 240 }}
      aria-label="Sidebar navigation"
    >
      {/* ---- Main nav ---- */}
      <nav className="flex-1 py-3 px-2 flex flex-col gap-0.5 overflow-y-auto overflow-x-hidden">
        <NavGroup
          items={mainItems}
          collapsed={collapsed}
          isActive={isActive}
        />

        {/* Divider */}
        <div className="my-2 mx-2 border-t border-slate-700/60" />

        <NavGroup
          items={systemItems}
          collapsed={collapsed}
          isActive={isActive}
        />
      </nav>

      {/* ---- Collapse toggle ---- */}
      <div className="px-2 pb-3 pt-1">
        <button
          type="button"
          onClick={toggleCollapsed}
          className={`
            flex items-center gap-3 w-full rounded-md px-3 py-2
            text-sm font-medium text-slate-400
            hover:bg-slate-800 hover:text-slate-200
            transition-colors duration-150
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
          `}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronRight className="h-5 w-5 shrink-0" />
          ) : (
            <>
              <ChevronLeft className="h-5 w-5 shrink-0" />
              <span className="truncate">Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// NavGroup — renders a list of NavItems
// ---------------------------------------------------------------------------

function NavGroup({
  items,
  collapsed,
  isActive,
}: {
  items: NavItem[];
  collapsed: boolean;
  isActive: (href: string) => boolean;
}) {
  return (
    <>
      {items.map((item) => {
        const active = isActive(item.href);
        const Icon = item.icon;

        return (
          <Link
            key={item.href}
            href={item.href}
            className={`
              group relative flex items-center gap-3 rounded-md px-3 py-2
              text-sm font-medium transition-colors duration-150
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
              ${
                active
                  ? "bg-blue-600/15 text-blue-400"
                  : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              }
            `}
            aria-current={active ? "page" : undefined}
            title={collapsed ? item.label : undefined}
          >
            {/* Active indicator bar */}
            {active && (
              <span
                className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-blue-500"
                aria-hidden="true"
              />
            )}

            <Icon
              className={`
                h-5 w-5 shrink-0 transition-colors duration-150
                ${
                  active
                    ? "text-blue-400"
                    : "text-slate-500 group-hover:text-slate-300"
                }
              `}
            />

            {/* Label — hidden when collapsed */}
            {!collapsed && <span className="truncate">{item.label}</span>}

            {/* Tooltip when collapsed */}
            {collapsed && (
              <span
                className="
                  pointer-events-none absolute left-full ml-3 z-50
                  rounded-md bg-slate-800 border border-slate-700
                  px-2.5 py-1.5 text-xs font-medium text-slate-200
                  shadow-lg whitespace-nowrap
                  opacity-0 scale-95
                  group-hover:opacity-100 group-hover:scale-100
                  transition-all duration-150
                "
                role="tooltip"
              >
                {item.label}
              </span>
            )}
          </Link>
        );
      })}
    </>
  );
}