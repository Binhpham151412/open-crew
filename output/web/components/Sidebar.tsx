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

  useEffect(() => {
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

  return (
    <aside
      className={`
        shrink-0 bg-slate-800 border-r border-slate-700
        flex flex-col transition-[width] duration-200 ease-in-out
        overflow-hidden select-none
      `}
      style={{ width: collapsed ? 64 : 240 }}
      aria-label="Sidebar navigation"
    >
      {/* ---- Main nav ---- */}
      <nav className="flex-1 py-4 flex flex-col gap-0.5 overflow-y-auto overflow-x-hidden">
        <NavGroup
          label="Main"
          items={mainItems}
          collapsed={collapsed}
          isActive={isActive}
        />

        {/* Divider */}
        <div className="my-2 mx-4 border-t border-slate-700" />

        <NavGroup
          label="System"
          items={systemItems}
          collapsed={collapsed}
          isActive={isActive}
        />
      </nav>

      {/* ---- Collapse toggle ---- */}
      <div className="px-5 pb-4 pt-1">
        <button
          type="button"
          onClick={toggleCollapsed}
          className={`
            no-underline flex items-center gap-3 w-full rounded-md px-3 py-2
            text-sm font-medium text-slate-400
            hover:bg-slate-800/60 hover:text-slate-200
            transition-colors duration-150
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
          `}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronRight className="h-[18px] w-[18px] shrink-0" />
          ) : (
            <>
              <ChevronLeft className="h-[18px] w-[18px] shrink-0" />
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
  label,
  items,
  collapsed,
  isActive,
}: {
  label: string;
  items: NavItem[];
  collapsed: boolean;
  isActive: (href: string) => boolean;
}) {
  return (
    <div className="px-3">
      {/* Section label — hidden when collapsed */}
      {!collapsed && (
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 px-3 pb-1 mb-0.5">
          {label}
        </div>
      )}

      {items.map((item) => {
        const active = isActive(item.href);
        const Icon = item.icon;

        return (
          <Link
            key={item.href}
            href={item.href}
            data-nav-item="true"
            className={`
              no-underline group relative flex items-center gap-3 rounded-md px-3 py-2
              text-sm font-medium transition-colors duration-150
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
              ${
                active
                  ? "bg-blue-600/90 text-white"
                  : "text-slate-300 hover:bg-slate-700/50 hover:text-slate-50"
              }
            `}
            aria-current={active ? "page" : undefined}
            title={collapsed ? item.label : undefined}
          >
            {/* Active indicator bar */}
            {active && (
              <span
                className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-white"
                aria-hidden="true"
              />
            )}

            <Icon
              className={`
                h-[18px] w-[18px] shrink-0 transition-colors duration-150
                ${
                  active
                    ? "text-white opacity-100"
                    : "text-slate-400 opacity-80 group-hover:opacity-100 group-hover:text-slate-200"
                }
              `}
            />

            {/* Label — hidden when collapsed */}
            {!collapsed && (
              <span
                className={`truncate ${
                  active
                    ? "text-white"
                    : "text-slate-300 group-hover:text-slate-50"
                }`}
              >
                {item.label}
              </span>
            )}

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
    </div>
  );
}
