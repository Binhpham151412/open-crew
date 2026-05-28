"""UIUX Reviewer — MCP tool implementations.

Provides a ``get_tools()`` factory that returns a dict of tool_name → callable.
Tools wrap GitHub MCP and OpenDesign MCP client calls, plus local analysis
utilities for WCAG 2.1 AA accessibility, responsive design, and UX validation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import structlog
from shared.mcp_client import MCPClient

log = structlog.get_logger("uiux_reviewer.tools")

# ---------------------------------------------------------------------------
# Severity / finding types (matching reviewer rules from PLAN.md)
# ---------------------------------------------------------------------------

VIOLATION = "VIOLATION"
SUGGESTION = "SUGGESTION"
OPINION = "OPINION"

# WCAG 2.1 AA required contrast ratios
CONTRAST_RATIO_NORMAL = 4.5
CONTRAST_RATIO_LARGE = 3.0  # ≥ 18pt or ≥ 14pt bold

# Minimum touch target size in CSS pixels (WCAG 2.5.8)
TOUCH_TARGET_MIN_PX = 44

# Breakpoints commonly used with Tailwind CSS
RESPONSIVE_BREAKPOINTS = {
    "sm": 640,
    "md": 768,
    "lg": 1024,
    "xl": 1280,
    "2xl": 1536,
}


# ---------------------------------------------------------------------------
# Lightweight hex ↔ RGB helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert a hex colour string (#RRGGBB or #RGB) to (R, G, B)."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 8 and len(h) != 6:
        raise ValueError(f"Invalid hex colour: {hex_color}")
    # Handle #RRGGBBAA — ignore alpha for luminance calc
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r, g, b


def _relative_luminance(r: int, g: int, b: int) -> float:
    """WCAG 2.1 relative luminance formula."""
    channels = []
    for c in (r, g, b):
        s = c / 255.0
        channels.append(s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(hex1: str, hex2: str) -> float:
    """Calculate WCAG contrast ratio between two hex colours."""
    l1 = _relative_luminance(*_hex_to_rgb(hex1))
    l2 = _relative_luminance(*_hex_to_rgb(hex2))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# Colour extraction heuristics
# ---------------------------------------------------------------------------

# Matches Tailwind arbitrary values like bg-[#ff0000] and standard hex in CSS/TSX
_HEX_PATTERN = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")

# Tailwind text-*/bg-* class → approximate hex mapping (subset for analysis)
_TAILWIND_COLOR_MAP: Dict[str, str] = {
    "text-slate-50": "#f8fafc",
    "text-slate-100": "#f1f5f9",
    "text-slate-200": "#e2e8f0",
    "text-slate-300": "#cbd5e1",
    "text-slate-400": "#94a3b8",
    "text-slate-500": "#64748b",
    "text-slate-600": "#475569",
    "text-slate-700": "#334155",
    "text-slate-800": "#1e293b",
    "text-slate-900": "#0f172a",
    "text-white": "#ffffff",
    "text-black": "#000000",
    "bg-slate-50": "#f8fafc",
    "bg-slate-100": "#f1f5f9",
    "bg-slate-200": "#e2e8f0",
    "bg-slate-800": "#1e293b",
    "bg-slate-900": "#0f172a",
    "bg-white": "#ffffff",
    "bg-black": "#000000",
}


def _extract_colours_from_source(source: str) -> List[Tuple[str, str]]:
    """Heuristically extract (text_color, bg_color) pairs from source code.

    Returns pairs found in the same component/class context.
    This is a best-effort heuristic — not a full CSS cascade analyser.
    """
    pairs: List[Tuple[str, str]] = []
    hex_colors = _HEX_PATTERN.findall(source)
    text_hex = [c for c in hex_colors if _is_likely_text_color(c, source)]
    bg_hex = [c for c in hex_colors if _is_likely_bg_color(c, source)]

    # Also look for Tailwind class pairs
    for tw_class, hex_val in _TAILWIND_COLOR_MAP.items():
        if tw_class.startswith("text-") and tw_class in source:
            for bg_tw, bg_hex_val in _TAILWIND_COLOR_MAP.items():
                if bg_tw.startswith("bg-") and bg_tw in source:
                    pairs.append((hex_val, bg_hex_val))

    # Cross-match explicit hex colours
    for t in text_hex:
        for b in bg_hex:
            pairs.append((t, b))

    return pairs


def _is_likely_text_color(hex_color: str, source: str) -> bool:
    """Heuristic: is this hex used as a text/foreground colour?"""
    # Look for nearby Tailwind text- classes or CSS color: declarations
    idx = source.find(hex_color)
    context = source[max(0, idx - 80) : idx + len(hex_color) + 80]
    return any(
        kw in context.lower()
        for kw in ["color:", "text-", "foreground", "fill="]
    )


def _is_likely_bg_color(hex_color: str, source: str) -> bool:
    """Heuristic: is this hex used as a background colour?"""
    idx = source.find(hex_color)
    context = source[max(0, idx - 80) : idx + len(hex_color) + 80]
    return any(
        kw in context.lower()
        for kw in ["background", "bg-", "background-color:"]
    )


# ---------------------------------------------------------------------------
# Source-level accessibility pattern detectors
# ---------------------------------------------------------------------------

_MISSING_ALT_RE = re.compile(r"<img\s(?![^>]*\balt\b)[^>]*>", re.IGNORECASE)
_INLINE_STYLE_RE = re.compile(r'style\s*=\s*\{?\{?["\']', re.IGNORECASE)
_FORM_NO_LABEL_RE = re.compile(
    r"<(?:input|select|textarea)\s(?![^>]*\b(id|aria-label|aria-labelledby)\b)[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
_TABINDEX_POSITIVE_RE = re.compile(r'tabIndex\s*=\s*["\']?([1-9])', re.IGNORECASE)
_FOCUS_STYLE_RE = re.compile(r"(focus|focus-visible|focus-within)", re.IGNORECASE)
_ARIA_ROLE_RE = re.compile(r'role\s*=\s*["\']', re.IGNORECASE)
_BUTTON_NO_TYPE_RE = re.compile(r"<button\s(?![^>]*\btype\b)[^>]*>", re.IGNORECASE)
_CLICK_DIV_RE = re.compile(
    r'<div\s[^>]*onClick\s*=\s*\{', re.IGNORECASE
)
_LINK_NO_HREF_RE = re.compile(r"<a\s(?![^>]*\bhref\b)[^>]*>", re.IGNORECASE)
_AUTOPLAY_VIDEO_RE = re.compile(r"<video\s[^>]*autoPlay", re.IGNORECASE)
_TOUCH_TARGET_RE = re.compile(
    r"(w-(?:\[)?(\d+)(?:px\])?|min-w-(?:\[)?(\d+)(?:px\]?)|width:\s*['\"]?(\d+)px)",
    re.IGNORECASE,
)


def _check_missing_alt_text(source: str) -> List[Dict[str, Any]]:
    """Detect <img> tags without alt attribute."""
    findings = []
    for match in _MISSING_ALT_RE.finditer(source):
        line_num = source[: match.start()].count("\n") + 1
        findings.append(
            {
                "rule": "wcag-1.1.1-non-text-content",
                "severity": VIOLATION,
                "message": "Image missing alt attribute — screen readers cannot describe this image.",
                "line": line_num,
                "snippet": match.group()[:120],
                "suggestion": 'Add descriptive alt text or alt="" for decorative images.',
            }
        )
    return findings


def _check_form_labels(source: str) -> List[Dict[str, Any]]:
    """Detect form inputs without associated labels or aria-label."""
    findings = []
    for match in _FORM_NO_LABEL_RE.finditer(source):
        line_num = source[: match.start()].count("\n") + 1
        findings.append(
            {
                "rule": "wcag-1.3.1-info-and-relationships",
                "severity": VIOLATION,
                "message": "Form input has no associated <label>, aria-label, or aria-labelledby.",
                "line": line_num,
                "snippet": match.group()[:120],
                "suggestion": "Wrap in <label> or add aria-label='...'.",
            }
        )
    return findings


def _check_focus_states(source: str, filename: str) -> List[Dict[str, Any]]:
    """Warn if stylesheets/components have no focus indicators."""
    findings = []
    # Only flag if file looks like a style file or component file
    is_style_file = any(
        filename.endswith(ext) for ext in (".css", ".scss", ".module.css", ".tsx", ".jsx")
    )
    if is_style_file and not _FOCUS_STYLE_RE.search(source):
        findings.append(
            {
                "rule": "wcag-2.4.7-focus-visible",
                "severity": VIOLATION,
                "message": "No :focus or focus-visible styles found — keyboard users cannot see focus position.",
                "line": 1,
                "snippet": "",
                "suggestion": "Add focus-visible:ring-2 focus-visible:ring-offset-2 or equivalent CSS.",
            }
        )
    return findings


def _check_clickable_divs(source: str) -> List[Dict[str, Any]]:
    """Detect <div onClick> that should be <button> or <a>."""
    findings = []
    for match in _CLICK_DIV_RE.finditer(source):
        line_num = source[: match.start()].count("\n") + 1
        findings.append(
            {
                "rule": "wcag-4.1.2-name-role-value",
                "severity": VIOLATION,
                "message": "Clickable <div> detected — not keyboard-accessible, no semantic role.",
                "line": line_num,
                "snippet": match.group()[:120],
                "suggestion": "Use <button> or <a> with appropriate role and tabIndex.",
            }
        )
    return findings


def _check_positive_tabindex(source: str) -> List[Dict[str, Any]]:
    """Detect positive tabIndex values which break natural tab order."""
    findings = []
    for match in _TABINDEX_POSITIVE_RE.finditer(source):
        line_num = source[: match.start()].count("\n") + 1
        findings.append(
            {
                "rule": "wcag-2.4.3-focus-order",
                "severity": VIOLATION,
                "message": f"Positive tabIndex={match.group(1)} breaks natural focus order.",
                "line": line_num,
                "snippet": match.group()[:120],
                "suggestion": "Use tabIndex={0} for focusable or tabIndex={-1} for programmatic focus.",
            }
        )
    return findings


def _check_button_types(source: str) -> List[Dict[str, Any]]:
    """Detect <button> without explicit type — defaults to 'submit' in forms."""
    findings = []
    for match in _BUTTON_NO_TYPE_RE.finditer(source):
        line_num = source[: match.start()].count("\n") + 1
        findings.append(
            {
                "rule": "form-usability",
                "severity": SUGGESTION,
                "message": "<button> without explicit type — may accidentally submit forms.",
                "line": line_num,
                "snippet": match.group()[:120],
                "suggestion": 'Add type="button" unless intentional form submission.',
            }
        )
    return findings


def _check_autoplay_video(source: str) -> List[Dict[str, Any]]:
    """Detect autoplay video without muted attribute."""
    findings = []
    for match in _AUTOPLAY_VIDEO_RE.finditer(source):
        line_num = source[: match.start()].count("\n") + 1
        if "muted" not in match.group().lower():
            findings.append(
                {
                    "rule": "wcag-1.4.2-audio-control",
                    "severity": VIOLATION,
                    "message": "Autoplay video without muted — may startle users, fails WCAG 1.4.2.",
                    "line": line_num,
                    "snippet": match.group()[:120],
                    "suggestion": "Add muted attribute or remove autoplay.",
                }
            )
    return findings


def _check_heading_hierarchy(source: str) -> List[Dict[str, Any]]:
    """Detect skipped heading levels (e.g. h1 → h3)."""
    findings = []
    heading_re = re.compile(r"<h([1-6])\b", re.IGNORECASE)
    levels = [int(m.group(1)) for m in heading_re.finditer(source)]
    for i in range(1, len(levels)):
        if levels[i] > levels[i - 1] + 1:
            findings.append(
                {
                    "rule": "wcag-1.3.1-info-and-relationships",
                    "severity": SUGGESTION,
                    "message": f"Heading level skipped: h{levels[i-1]} → h{levels[i]}.",
                    "line": 0,
                    "snippet": "",
                    "suggestion": "Maintain sequential heading hierarchy for screen readers.",
                }
            )
    return findings


def _check_landmark_roles(source: str) -> List[Dict[str, Any]]:
    """Suggest using semantic HTML landmarks."""
    findings = []
    has_main = bool(re.search(r"<main\b|role\s*=\s*['\"]main['\"]", source, re.I))
    has_nav = bool(re.search(r"<nav\b|role\s*=\s*['\"]navigation['\"]", source, re.I))
    if not has_main and len(source) > 500:
        findings.append(
            {
                "rule": "wcag-1.3.1-info-and-relationships",
                "severity": SUGGESTION,
                "message": "No <main> landmark found — screen readers cannot locate main content.",
                "line": 1,
                "snippet": "",
                "suggestion": "Wrap primary content in <main> tag.",
            }
        )
    return findings


def _check_colour_contrast(source: str) -> List[Dict[str, Any]]:
    """Heuristically check colour contrast ratios in source code."""
    findings = []
    pairs = _extract_colours_from_source(source)
    seen: set[Tuple[str, str]] = set()
    for text_color, bg_color in pairs:
        key = (text_color.lower(), bg_color.lower())
        if key in seen:
            continue
        seen.add(key)
        try:
            ratio = _contrast_ratio(text_color, bg_color)
        except (ValueError, ZeroDivisionError):
            continue
        if ratio < CONTRAST_RATIO_NORMAL:
            findings.append(
                {
                    "rule": "wcag-1.4.3-contrast-minimum",
                    "severity": VIOLATION,
                    "message": (
                        f"Colour contrast ratio {ratio:.2f}:1 is below "
                        f"{CONTRAST_RATIO_NORMAL}:1 for text {text_color} on {bg_color}."
                    ),
                    "line": 0,
                    "snippet": f"text: {text_color}, bg: {bg_color}",
                    "suggestion": "Increase contrast to at least 4.5:1 for normal text.",
                }
            )
    return findings


def _check_loading_empty_error_states(source: str, filename: str) -> List[Dict[str, Any]]:
    """Check that components implement loading, empty, and error states."""
    findings = []
    # Only check component/page files, not utility modules
    if not any(filename.endswith(ext) for ext in (".tsx", ".jsx")):
        return findings

    is_page = "/page." in filename or "/app/" in filename
    is_component = "/components/" in filename
    if not (is_page or is_component):
        return findings

    has_loading = bool(
        re.search(r"(loading|skeleton|spinner|isLoading|isFetching)", source, re.I)
    )
    has_empty = bool(
        re.search(r"(empty|no-data|no-results|isEmpty|length\s*===?\s*0)", source, re.I)
    )
    has_error = bool(
        re.search(r"(error|isError|catch|fallback|ErrorBoundary)", source, re.I)
    )

    if not has_loading:
        findings.append(
            {
                "rule": "ux-loading-state",
                "severity": SUGGESTION,
                "message": "No loading state detected — users see nothing while data loads.",
                "line": 1,
                "snippet": "",
                "suggestion": "Add a skeleton or spinner for the loading phase.",
            }
        )
    if not has_empty and is_page:
        findings.append(
            {
                "rule": "ux-empty-state",
                "severity": SUGGESTION,
                "message": "No empty state detected — users see blank screen when no data.",
                "line": 1,
                "snippet": "",
                "suggestion": "Add an empty state illustration or message.",
            }
        )
    if not has_error:
        findings.append(
            {
                "rule": "ux-error-state",
                "severity": VIOLATION,
                "message": "No error handling detected — unhandled errors show blank/broken UI.",
                "line": 1,
                "snippet": "",
                "suggestion": "Add error boundary or try/catch with user-friendly message.",
            }
        )
    return findings


def _check_responsive_classes(source: str) -> List[Dict[str, Any]]:
    """Check for responsive breakpoint classes in Tailwind code."""
    findings = []
    # If file uses Tailwind but has no responsive prefixes, flag it
    uses_tailwind = bool(re.search(r"(className|class)\s*=", source))
    has_responsive = bool(re.search(r"\b(sm|md|lg|xl|2xl):", source))
    if uses_tailwind and not has_responsive and len(source) > 300:
        findings.append(
            {
                "rule": "ux-responsive-design",
                "severity": SUGGESTION,
                "message": "No responsive breakpoint classes found — layout may break on mobile.",
                "line": 1,
                "snippet": "",
                "suggestion": "Add sm:/md:/lg: prefixes for responsive layouts.",
            }
        )
    return findings


def _check_touch_targets(source: str) -> List[Dict[str, Any]]:
    """Heuristically check that interactive elements meet 44px minimum."""
    findings = []
    # Look for small width/height in interactive elements
    small_size_re = re.compile(
        r"(w|width|min-w|minWidth)[:\-\s]*\[?(\d{1,2})px\]?",
        re.IGNORECASE,
    )
    for match in small_size_re.finditer(source):
        size = int(match.group(2))
        if size < TOUCH_TARGET_MIN_PX:
            # Check if this is in an interactive context
            ctx_start = max(0, match.start() - 200)
            context = source[ctx_start : match.end() + 50]
            if re.search(r"(button|link|onClick|href|cursor-pointer)", context, re.I):
                line_num = source[: match.start()].count("\n") + 1
                findings.append(
                    {
                        "rule": "wcag-2.5.8-target-size",
                        "severity": VIOLATION,
                        "message": f"Interactive element width {size}px is below 44px minimum touch target.",
                        "line": line_num,
                        "snippet": match.group()[:120],
                        "suggestion": "Increase to at least 44×44px or add padding.",
                    }
                )
    return findings


# ---------------------------------------------------------------------------
# Aggregate local analysis
# ---------------------------------------------------------------------------

def _analyse_source_file(source: str, filename: str) -> List[Dict[str, Any]]:
    """Run all local accessibility and UX checks on a single source file."""
    findings: List[Dict[str, Any]] = []
    findings.extend(_check_missing_alt_text(source))
    findings.extend(_check_form_labels(source))
    findings.extend(_check_focus_states(source, filename))
    findings.extend(_check_clickable_divs(source))
    findings.extend(_check_positive_tabindex(source))
    findings.extend(_check_button_types(source))
    findings.extend(_check_autoplay_video(source))
    findings.extend(_check_heading_hierarchy(source))
    findings.extend(_check_landmark_roles(source))
    findings.extend(_check_colour_contrast(source))
    findings.extend(_check_loading_empty_error_states(source, filename))
    findings.extend(_check_responsive_classes(source))
    findings.extend(_check_touch_targets(source))
    return findings


# ---------------------------------------------------------------------------
# Tool: result container
# ---------------------------------------------------------------------------

@dataclass
class ReviewResult:
    """Structured result from running UIUX review tools."""
    findings: List[Dict[str, Any]] = field(default_factory=list)
    design_diffs: List[Dict[str, Any]] = field(default_factory=list)
    pr_comments: List[Dict[str, Any]] = field(default_factory=list)
    has_violations: bool = False

    def add_finding(self, finding: Dict[str, Any]) -> None:
        self.findings.append(finding)
        if finding.get("severity") == VIOLATION:
            self.has_violations = True

    def summary(self) -> Dict[str, Any]:
        violations = [f for f in self.findings if f.get("severity") == VIOLATION]
        suggestions = [f for f in self.findings if f.get("severity") == SUGGESTION]
        opinions = [f for f in self.findings if f.get("severity") == OPINION]
        return {
            "total_findings": len(self.findings),
            "violations": len(violations),
            "suggestions": len(suggestions),
            "opinions": len(opinions),
            "has_violations": self.has_violations,
            "verdict": "FAIL" if self.has_violations else "PASS",
            "findings": self.findings,
            "design_diffs": self.design_diffs,
            "pr_comments_posted": len(self.pr_comments),
        }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _fetch_pr_files(
    mcp: MCPClient,
    *,
    repo: str,
    pr_number: int,
) -> List[Dict[str, Any]]:
    """Fetch files changed in a PR via GitHub MCP.

    Parameters
    ----------
    mcp:
        The shared MCP client instance.
    repo:
        Repository in ``owner/name`` format.
    pr_number:
        Pull request number.

    Returns
    -------
    list[dict]
        Each dict contains ``filename``, ``status``, ``patch``, and ``content``.
    """
    log.info("fetching_pr_files", repo=repo, pr_number=pr_number)
    try:
        response = await mcp.call(
            server="github_mcp",
            tool="get_pr_files",
            arguments={"repo": repo, "pr_number": pr_number},
        )
        files = response if isinstance(response, list) else response.get("files", [])
        # Filter to frontend-relevant files only
        frontend_extensions = {".tsx", ".jsx", ".ts", ".js", ".css", ".scss", ".html"}
        frontend_files = []
        for f in files:
            fname = f.get("filename", "")
            if any(fname.endswith(ext) for ext in frontend_extensions):
                frontend_files.append(f)
        log.info("pr_files_filtered", total=len(files), frontend=len(frontend_files))
        return frontend_files
    except Exception as exc:
        log.error("fetch_pr_files_failed", error=str(exc))
        return []


async def _fetch_file_content(
    mcp: MCPClient,
    *,
    repo: str,
    path: str,
    ref: str = "main",
) -> str:
    """Fetch the full content of a single file via GitHub MCP."""
    log.info("fetching_file_content", repo=repo, path=path, ref=ref)
    try:
        response = await mcp.call(
            server="github_mcp",
            tool="get_file",
            arguments={"repo": repo, "path": path, "ref": ref},
        )
        if isinstance(response, dict):
            return response.get("content", "")
        return str(response)
    except Exception as exc:
        log.error("fetch_file_content_failed", path=path, error=str(exc))
        return ""


async def _get_design_spec(
    mcp: MCPClient,
    *,
    component_name: str | None = None,
    spec_path: str | None = None,
) -> Dict[str, Any]:
    """Fetch design specifications from OpenDesign MCP.

    Parameters
    ----------
    mcp:
        The shared MCP client instance.
    component_name:
        Optional name of the component to look up.
    spec_path:
        Optional path to a design spec file in the repo.

    Returns
    -------
    dict
        Design spec including colours, spacing, typography, component specs.
    """
    log.info("fetching_design_spec", component=component_name, path=spec_path)
    try:
        arguments: Dict[str, Any] = {}
        if component_name:
            arguments["component"] = component_name
        if spec_path:
            arguments["path"] = spec_path
        response = await mcp.call(
            server="opendesign_mcp",
            tool="get_design_spec",
            arguments=arguments,
        )
        return response if isinstance(response, dict) else {"raw": response}
    except Exception as exc:
        log.error("fetch_design_spec_failed", error=str(exc))
        return {"error": str(exc), "available": False}


async def _compare_with_design(
    mcp: MCPClient,
    *,
    implementation_source: str,
    design_spec: Dict[str, Any],
    component_name: str | None = None,
) -> List[Dict[str, Any]]:
    """Compare frontend implementation against design spec via OpenDesign MCP.

    Returns a list of discrepancies, each with severity, message, and details.
    """
    log.info("comparing_with_design", component=component_name)
    diffs: List[Dict[str, Any]] = []

    if not design_spec or design_spec.get("error"):
        log.warning("design_spec_unavailable", spec=design_spec)
        return diffs

    try:
        response = await mcp.call(
            server="opendesign_mcp",
            tool="compare_design",
            arguments={
                "implementation": implementation_source[:50000],  # cap for API limits
                "spec": json.dumps(design_spec),
                "component": component_name or "unknown",
            },
        )
        if isinstance(response, list):
            diffs = response
        elif isinstance(response, dict) and "diffs" in response:
            diffs = response["diffs"]
        elif isinstance(response, dict) and "discrepancies" in response:
            diffs = response["discrepancies"]
    except Exception as exc:
        log.error("compare_design_failed", error=str(exc))
        diffs.append(
            {
                "severity": OPINION,
                "message": f"Could not compare with design spec: {exc}",
                "source": "opendesign_mcp",
            }
        )

    # Normalise severity values
    for diff in diffs:
        sev = diff.get("severity", "").upper()
        if sev not in (VIOLATION, SUGGESTION, OPINION):
            diff["severity"] = SUGGESTION

    return diffs


async def _post_pr_review_comments(
    mcp: MCPClient,
    *,
    repo: str,
    pr_number: int,
    findings: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Post review findings as PR comments via GitHub MCP.

    Only posts VIOLATION and SUGGESTION findings as line-level comments.
    OPINION findings are included in the summary comment only.

    Returns a list of posted comment results.
    """
    posted: List[Dict[str, Any]] = []

    # Post individual line comments for violations and suggestions
    action_findings = [f for f in findings if f.get("severity") in (VIOLATION, SUGGESTION)]
    for finding in action_findings:
        if finding.get("line", 0) <= 0:
            continue
        try:
            severity_icon = "🔴" if finding["severity"] == VIOLATION else "🟡"
            body = (
                f"{severity_icon} **[{finding['severity']}]** {finding.get('message', '')}\n\n"
                f"**Rule:** `{finding.get('rule', 'unknown')}`\n\n"
                f"**Suggestion:** {finding.get('suggestion', '')}"
            )
            result = await mcp.call(
                server="github_mcp",
                tool="create_pr_comment",
                arguments={
                    "repo": repo,
                    "pr_number": pr_number,
                    "body": body,
                    "path": finding.get("file", ""),
                    "line": finding.get("line", 0),
                },
            )
            posted.append({"finding_rule": finding.get("rule"), "status": "posted", "result": result})
        except Exception as exc:
            log.error("post_comment_failed", rule=finding.get("rule"), error=str(exc))
            posted.append({"finding_rule": finding.get("rule"), "status": "failed", "error": str(exc)})

    # Post summary comment
    violations = [f for f in findings if f.get("severity") == VIOLATION]
    suggestions = [f for f in findings if f.get("severity") == SUGGESTION]
    opinions = [f for f in findings if f.get("severity") == OPINION]
    verdict = "❌ **BLOCKED** — Violations found" if violations else "✅ **APPROVED** — No violations"

    summary_body = (
        f"## 🎨 UIUX Review Report\n\n"
        f"**Verdict:** {verdict}\n\n"
        f"| Severity | Count |\n|---|---|\n"
        f"| 🔴 VIOLATION | {len(violations)} |\n"
        f"| 🟡 SUGGESTION | {len(suggestions)} |\n"
        f"| 🔵 OPINION | {len(opinions)} |\n\n"
    )
    if violations:
        summary_body += "### Violations\n"
        for v in violations[:10]:
            summary_body += f"- `{v.get('rule')}` — {v.get('message')}\n"
    if suggestions:
        summary_body += "\n### Suggestions\n"
        for s in suggestions[:10]:
            summary_body += f"- `{s.get('rule')}` — {s.get('message')}\n"

    try:
        await mcp.call(
            server="github_mcp",
            tool="create_pr_comment",
            arguments={
                "repo": repo,
                "pr_number": pr_number,
                "body": summary_body,
            },
        )
        posted.append({"type": "summary", "status": "posted"})
    except Exception as exc:
        log.error("post_summary_comment_failed", error=str(exc))
        posted.append({"type": "summary", "status": "failed", "error": str(exc)})

    return posted


async def _block_pr_merge(
    mcp: MCPClient,
    *,
    repo: str,
    pr_number: int,
    reason: str,
) -> Dict[str, Any]:
    """Block a PR from merging via GitHub MCP.

    Uses a PR review with REQUEST_CHANGES to block the merge.
    """
    log.warning("blocking_pr_merge", repo=repo, pr_number=pr_number, reason=reason)
    try:
        result = await mcp.call(
            server="github_mcp",
            tool="create_pr_review",
            arguments={
                "repo": repo,
                "pr_number": pr_number,
                "event": "REQUEST_CHANGES",
                "body": (
                    f"## 🔴 UIUX Review — Merge Blocked\n\n"
                    f"**Reason:** {reason}\n\n"
                    f"Please fix the violations listed in the inline comments "
                    f"and re-request review."
                ),
            },
        )
        return {"status": "blocked", "result": result}
    except Exception as exc:
        log.error("block_pr_merge_failed", error=str(exc))
        return {"status": "failed", "error": str(exc)}


async def _approve_pr(
    mcp: MCPClient,
    *,
    repo: str,
    pr_number: int,
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Approve a PR via GitHub MCP when no violations are found."""
    log.info("approving_pr", repo=repo, pr_number=pr_number)
    try:
        result = await mcp.call(
            server="github_mcp",
            tool="create_pr_review",
            arguments={
                "repo": repo,
                "pr_number": pr_number,
                "event": "APPROVE",
                "body": (
                    f"## ✅ UIUX Review — Approved\n\n"
                    f"Findings: {summary.get('violations', 0)} violations, "
                    f"{summary.get('suggestions', 0)} suggestions, "
                    f"{summary.get('opinions', 0)} opinions.\n\n"
                    f"No blocking violations found. Good to merge!"
                ),
            },
        )
        return {"status": "approved", "result": result}
    except Exception as exc:
        log.error("approve_pr_failed", error=str(exc))
        return {"status": "failed", "error": str(exc)}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_tools(mcp: MCPClient) -> Dict[str, Any]:
    """Return the UIUX Reviewer's tool registry.

    Each key is a tool name; each value is an async callable that the agent
    can invoke during review processing.  Tools are pre-bound to the given
    ``mcp`` client instance.

    Parameters
    ----------
    mcp:
        The shared :class:`MCPClient` for calling GitHub MCP and OpenDesign MCP.

    Returns
    -------
    dict[str, callable]
        Mapping of tool name → async callable.
    """

    async def fetch_pr_files(
        repo: str,
        pr_number: int,
    ) -> List[Dict[str, Any]]:
        """Fetch frontend-relevant files changed in a GitHub PR.

        Parameters
        ----------
        repo : str
            Repository in ``owner/name`` format.
        pr_number : int
            Pull request number.

        Returns
        -------
        list[dict]
            List of file metadata dicts with ``filename``, ``status``, ``patch``, ``content``.
        """
        return await _fetch_pr_files(mcp, repo=repo, pr_number=pr_number)

    async def fetch_file_content(
        repo: str,
        path: str,
        ref: str = "main",
    ) -> str:
        """Fetch the full content of a file from GitHub.

        Parameters
        ----------
        repo : str
            Repository in ``owner/name`` format.
        path : str
            File path within the repository.
        ref : str
            Git ref (branch, tag, or SHA). Defaults to ``"main"``.

        Returns
        -------
        str
            Raw file content as a string.
        """
        return await _fetch_file_content(mcp, repo=repo, path=path, ref=ref)

    async def get_design_spec(
        component_name: str | None = None,
        spec_path: str | None = None,
    ) -> Dict[str, Any]:
        """Fetch design specifications from OpenDesign MCP.

        Parameters
        ----------
        component_name : str, optional
            Name of the component to look up.
        spec_path : str, optional
            Path to a design spec file.

        Returns
        -------
        dict
            Design specification including colours, spacing, typography.
        """
        return await _get_design_spec(
            mcp, component_name=component_name, spec_path=spec_path
        )

    async def compare_with_design(
        implementation_source: str,
        design_spec: Dict[str, Any],
        component_name: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Compare implementation source against design spec.

        Parameters
        ----------
        implementation_source : str
            Full source code of the component/page being reviewed.
        design_spec : dict
            Design specification fetched via ``get_design_spec``.
        component_name : str, optional
            Name of the component for context.

        Returns
        -------
        list[dict]
            List of discrepancies with severity, message, and details.
        """
        return await _compare_with_design(
            mcp,
            implementation_source=implementation_source,
            design_spec=design_spec,
            component_name=component_name,
        )

    async def analyse_accessibility(
        source: str,
        filename: str,
    ) -> List[Dict[str, Any]]:
        """Run local WCAG 2.1 AA accessibility analysis on source code.

        Checks for:
        - Missing alt text on images
        - Form inputs without labels
        - Missing focus states
        - Clickable divs instead of semantic elements
        - Positive tabIndex values
        - Button types
        - Autoplay video without mute
        - Heading hierarchy
        - Landmark roles
        - Colour contrast ratios
        - Touch target sizes
        - Loading / empty / error states
        - Responsive breakpoint classes

        Parameters
        ----------
        source : str
            Full source code to analyse.
        filename : str
            File path (used for context-aware checks).

        Returns
        -------
        list[dict]
            List of findings, each with ``rule``, ``severity``, ``message``,
            ``line``, ``snippet``, and ``suggestion``.
        """
        log.info("analysing_accessibility", filename=filename, length=len(source))
        findings = _analyse_source_file(source, filename)
        log.info(
            "accessibility_analysis_complete",
            filename=filename,
            total_findings=len(findings),
            violations=sum(1 for f in findings if f.get("severity") == VIOLATION),
        )
        return findings

    async def post_pr_comments(
        repo: str,
        pr_number: int,
        findings: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Post review findings as inline and summary PR comments.

        Parameters
        ----------
        repo : str
            Repository in ``owner/name`` format.
        pr_number : int
            Pull request number.
        findings : list[dict]
            Findings from ``analyse_accessibility`` or ``compare_with_design``.

        Returns
        -------
        list[dict]
            Results of each posted comment.
        """
        return await _post_pr_review_comments(
            mcp, repo=repo, pr_number=pr_number, findings=findings
        )

    async def block_pr(
        repo: str,
        pr_number: int,
        reason: str,
    ) -> Dict[str, Any]:
        """Block a PR from merging due to UIUX violations.

        Parameters
        ----------
        repo : str
            Repository in ``owner/name`` format.
        pr_number : int
            Pull request number.
        reason : str
            Reason for blocking.

        Returns
        -------
        dict
            Status of the block action.
        """
        return await _block_pr_merge(
            mcp, repo=repo, pr_number=pr_number, reason=reason
        )

    async def approve_pr(
        repo: str,
        pr_number: int,
        summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Approve a PR when no UIUX violations are found.

        Parameters
        ----------
        repo : str
            Repository in ``owner/name`` format.
        pr_number : int
            Pull request number.
        summary : dict
            Review summary (from ``ReviewResult.summary()``).

        Returns
        -------
        dict
            Status of the approval action.
        """
        return await _approve_pr(
            mcp, repo=repo, pr_number=pr_number, summary=summary
        )

    async def generate_review_report(
        findings: List[Dict[str, Any]],
        design_diffs: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """Generate a structured review report from all findings.

        Aggregates findings from accessibility analysis and design comparison,
        classifies by severity, and produces a final verdict.

        Parameters
        ----------
        findings : list[dict]
            All findings from local analysis.
        design_diffs : list[dict], optional
            Discrepancies from design comparison.

        Returns
        -------
        dict
            Structured report with counts, verdict, and detailed findings.
        """
        result = ReviewResult()
        for finding in findings:
            result.add_finding(finding)
        if design_diffs:
            for diff in design_diffs:
                normalised = {
                    "rule": diff.get("rule", "design-compliance"),
                    "severity": diff.get("severity", SUGGESTION),
                    "message": diff.get("message", diff.get("description", "")),
                    "line": diff.get("line", 0),
                    "snippet": diff.get("snippet", ""),
                    "suggestion": diff.get("suggestion", diff.get("recommendation", "")),
                    "source": "opendesign_mcp",
                }
                result.add_finding(normalised)
                result.design_diffs.append(diff)

        report = result.summary()
        log.info(
            "review_report_generated",
            total=report["total_findings"],
            violations=report["violations"],
            verdict=report["verdict"],
        )
        return report

    # ------------------------------------------------------------------
    # Return the tool registry
    # ------------------------------------------------------------------

    return {
        "fetch_pr_files": fetch_pr_files,
        "fetch_file_content": fetch_file_content,
        "get_design_spec": get_design_spec,
        "compare_with_design": compare_with_design,
        "analyse_accessibility": analyse_accessibility,
        "post_pr_comments": post_pr_comments,
        "block_pr": block_pr,
        "approve_pr": approve_pr,
        "generate_review_report": generate_review_report,
    }