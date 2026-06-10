---
name: ux-design
description: Comprehensive UI guidelines covering design tokens, component rules, and interaction patterns for the pi-CoWork application.
---

# UX Design Skill

Comprehensive UI guidelines covering the full application — cards, forms, detail pages, sidebar, modals, notifications, etc. Extends the UI Conventions (#79) and UI Design Guidelines (#80) sections in `AGENTS.md` with formal design tokens, component rules, and interaction patterns.

Agents working on UI changes should follow these guidelines to keep the application visually consistent.

## Design Principles

1. **Clarity over cleverness** — simple, readable UI. No decorative elements that don't convey meaning.
2. **Consistency** — reuse design tokens and CSS variables. No one-off color values, margins, or font sizes.
3. **Progressive disclosure** — collapse/expand for secondary content, modals for secondary actions, inline for primary actions.
4. **Mobile-first responsive** — breakpoints at 640px and 768px. The 768px breakpoint hides the sidebar and shows the hamburger topbar. The 640px breakpoint stacks forms and makes the assistant full-screen.
5. **Accessibility fundamentals** — focus rings on all interactive elements, keyboard navigation (Enter/Escape/Tab), contrast ratios ≥ 4.5:1 for normal text.
6. **Vanilla-only** — no CSS frameworks, no JavaScript frameworks, no build step. All styles in `static/style.css`.

## Design Tokens

All tokens are CSS custom properties defined in `:root` in `static/style.css`. New components **must** use these tokens, not hardcode values.

### Color System

| Category | Token | Value | Usage |
|----------|-------|-------|-------|
| Background | `--bg` | `#f3f4f6` | Page background, subtle fills |
| Surface | `--surface` | `#ffffff` | Card/panel backgrounds |
| Surface elevated | `--surface-elevated` | `#ffffff` | Card inner zones, header backgrounds |
| Text | `--text` | `#111827` | Primary text |
| Text secondary | `--text-secondary` | `#4b5563` | Descriptions, labels |
| Text muted | `--text-muted` | `#9ca3af` | Timestamps, hints, empty states |
| Border | `--border` | `#e5e7eb` | Card borders, dividers |
| Border secondary | `--border-secondary` | `#f1f5f9` | Subtle separators (card footer top) |
| Border strong | `--border-strong` | `#d1d5db` | Hover borders, active borders |
| Primary | `--primary` | `#2563eb` | Buttons, links, active nav |
| Primary soft | `--primary-soft` | `#eff6ff` | Hover fills, badge backgrounds |
| Primary hover | `--primary-hover` | `#1d4ed8` | Button hover state |
| Success | `--success` | `#10b981` | Positive feedback, badges |
| Success soft | `--success-soft` | `#ecfdf5` | Success badge backgrounds |
| Warning | `--warning` | `#f59e0b` | Warning states, badges |
| Warning soft | `--warning-soft` | `#fffbeb` | Warning badge backgrounds |
| Danger | `--danger` | `#ef4444` | Error/danger buttons, badges |
| Danger soft | `--danger-soft` | `#fef2f2` | Error badge backgrounds |
| Danger hover | `--danger-hover` | `#dc2626` | Danger button hover |

**Priority colors** (used directly, not as tokens):
- Critical: `#dc2626`
- High: `#d97706`
- Medium: `#2563eb`
- Low: `#6b7280`

### Typography

- **Font family**: `system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif`
- **Size scale**: 0.7rem (badges) → 0.75rem (card ID, timestamps) → 0.8rem (small buttons, table code) → 0.85rem (labels, inputs) → 0.9rem (body text, nav links) → 0.95rem (card title, status) → 1rem (section headings, forms) → 1.1rem (panel headers, modal titles) → 1.15rem (sidebar brand) → 1.2rem (mobile page header) → 1.35rem (desktop detail title) → 1.4rem (page header)
- **Weight scale**: 400 (body), 500 (nav, labels, inputs), 600 (card titles, badges, section heads), 700 (page headers, sidebar brand)
- **Line heights**: 1 (badges, icons), 1.25 (compact), 1.3 (headings), 1.35 (card title), 1.4 (toast, assistant message), 1.5 (body default), 1.6 (description)

### Spacing Scale

| Name | Values | When to use |
|------|---------|-------------|
| Tight | 0.15rem, 0.2rem, 0.25rem, 0.3rem, 0.35rem | Inner badge padding, small gaps |
| Default | 0.4rem, 0.5rem, 0.55rem, 0.6rem, 0.65rem, 0.7rem, 0.75rem | Standard padding, field gaps, list items |
| Comfortable | 1rem, 1.1rem, 1.15rem, 1.25rem | Section padding, heading margins |
| Loose | 1.5rem, 1.75rem | Page container padding, section gaps |

### Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-sm` | 0.375rem | Small elements: badges, pills, code blocks |
| `--radius` | 0.5rem | Default: inputs, buttons, cards, modals |
| `--radius-lg` | 0.75rem | Large: panels, form cards, section cards, data tables |
| Pill | 999px | Badges, status pills, priority labels, selects |

### Shadows

| Token | Value | Usage |
|-------|-------|-------|
| `--shadow` | `0 1px 2px rgba(0,0,0,0.04)` | Cards, form cards, section cards (default elevation) |
| `--shadow-md` | `0 4px 6px -1px rgba(0,0,0,0.06), 0 2px 4px -1px rgba(0,0,0,0.03)` | Card hover, buttons hover, modals |
| `--shadow-lg` | `0 10px 15px -3px rgba(0,0,0,0.08), 0 4px 6px -2px rgba(0,0,0,0.03)` | Panels, notifications, assistant bubble |

### Z-Index Layers

| Layer | z-index | Element |
|-------|---------|---------|
| Topbar | 30 | `.topbar` |
| Sidebar overlay | 40 | `.sidebar-overlay` |
| Sidebar | 50 | `.sidebar` |
| Panel overlay | 40 | `.panel-overlay` |
| Slide panel | 55 | `.slide-panel` |
| Modal | 100 | `.modal` |
| Notification panel | 100 | `.notification-panel` |
| Label popover | 1000 | `.label-popover` |
| Toast | 9999 | `.toast-container` |
| Assistant bubble | 201 | `.assistant-bubble` |
| Assistant panel (open) | 250 | `.assistant-panel.open` |

## Component Guidelines

### Board Cards
Three-zone layout (`.card-header` → `.card-body` → `.card-footer`). Priority accent via `border-left: 3px solid <color>` with `.card-priority-Critical/High/Medium/Low`. Status rendered as a styled `<select>` (`.card-status-select`, `appearance:none` + custom chevron SVG). Labels as `.label-pill` with opacity `33`/`55` for bg/border. Label add button as `.card-label-add` (circular dashed `+`). Entry animation: `card-entrance` (fade + translateY 4px, 0.2s).

### Section Cards
`.section-card` — `var(--surface)` bg, `var(--border)` border, `var(--radius-lg)` border-radius, `var(--shadow)` shadow, `1rem` padding. Used for ticket detail content sections.

### Sidebar Cards
`.sidebar-card` — identical styling to section-card, used in ticket sidebar. Fields use `.sidebar-field-label` (muted, uppercase, 0.75rem) and `.sidebar-field-value` (0.9rem).

### Board Manager Cards
`.board-card` — horizontal flex, `0.75rem` padding, `var(--radius)` border. Active state uses `var(--primary-soft)` bg + `var(--primary)` border.

### Running Agent Cards
`.running-card` — inline-flex with `.pulse-indicator` (animated dot), `.kill-btn` for kill action.

### Agent Run Cards
`.agent-run-card` — status badges use `.badge.run-running`, `.run-completed`, `.run-failed` with 22/44 opacity hex pattern. Log output uses dark (`#1e1e2e` bg, `#cdd6f4` text) monospace block.

### Question Cards
`.question-card` — inside `.questions-section` (purple-tinted border/bg: `#ddd6fe`/`#faf5ff`). Options as radio/checkbox group with `.question-option`.

### Forms
`.form-card` — white surface, border-radius `var(--radius-lg)`, `var(--shadow)`, `max-width: 640px`. Inputs: `var(--bg)` background, focus ring `0 0 0 3px rgba(37,99,235,0.1)` + `border-color: var(--primary)`. Checkboxes in `.checkbox-group` rows. Inline forms via `.form-inline`.

### Buttons
- **Primary** (`.btn.primary`): `var(--primary)` bg, white text, hover `var(--primary-hover)`
- **Danger** (`.btn.danger`): `var(--danger)` bg, white text, hover `var(--danger-hover)`
- **Ghost** (`.btn.ghost`): transparent bg/border, hover shows `var(--bg)` bg
- **Small** (`.btn.small`): reduced padding `0.3rem 0.6rem`, font-size `0.8rem`
- **Run agent** (`.btn.run-agent`): gradient `#6366f1 → #8b5cf6`, white text
- **Re-run agent** (`.btn.rerun-agent`): gradient `#ea580c → #f59e0b`, white text
- **Kill** (`.kill-btn`): outlined danger-soft bg, `#991b1b` text, hover fills solid `var(--danger)`
- **Add** (`.add-btn`): minimal, transparent bg, `var(--primary)` text, hover `var(--primary-soft)` bg
- All buttons: `transition: background .15s, border-color .15s, box-shadow .15s`, `white-space: nowrap`, disabled `opacity: 0.6–0.7`, `cursor: not-allowed`

### Badges & Pills
- **Status** (`.badge.status`): purple-tinted (`#e0e7ff` bg, `#3730a3` text)
- **Priority** (`.card-priority-label.p-*`): color-coded bg/text/border per level
- **Agent** (`.badge.agent`): primary-soft bg, primary text, `#bfdbfe` border
- **Queued** (`.badge.queued`): warning-soft bg, `#92400e` text, `#fde68a` border
- **Gate** (`.badge.gate`): `#fef3c7` bg, `#92400e` text, `#fcd34d` border
- **Question** (`.badge.question`): `#ede9fe` bg, `#5b21b6` text
- **Recurring** (`.badge.recurring`): primary-soft bg, primary text
- **Label pills** (`.label-pill`): colored bg at `33` opacity, border at `55` opacity, `min-width: 1.8rem`, `0.6rem` horizontal padding
- **All badges**: `border-radius: 999px`, `font-size: 0.75rem`, `font-weight: 600`, `line-height: 1`

### Modals
Fixed overlay `rgba(0,0,0,0.45)` at z-index 100. Content: `var(--surface)`, `var(--radius-lg)`, `var(--shadow-lg)`, `max-width: 540px`. Animation: `modal-in` (fade + translateY -10px, 0.2s). Responsive: `max-height: calc(100vh - 2rem)`, at ≤768px reduced padding.

### Slide Panels
Fixed position, 320px wide (max 85vw). Board manager slides from right. Overlay `rgba(0,0,0,0.35)` at z-index 40. Transition: `transform 0.25s ease` (translateX). Header uses `border-bottom` separator.

### Toast Notifications
Fixed top-right, z-index 9999. Types: success (`--success-soft` bg, `#065f46` text, `#6ee7b7` border), error (`--danger-soft` bg, `#991b1b` text, `#fca5a5` border), warning (`--warning-soft` bg, `#92400e` text, `#fde68a` border), info (`--primary-soft` bg, `#1e40af` text, `#bfdbfe` border). Animations: `toast-in` (slideX 1rem, 0.2s), `toast-out` (reverse, 0.2s). Default duration 4000ms. Click to dismiss.

### Tables
`.data-table` inside `.table-wrapper` (scrollable, bordered, `var(--radius-lg)`). Header: `var(--bg)` bg, `var(--text-secondary)` color, `0.8rem` uppercase. Rows: `border-bottom: 1px solid var(--border)`. Code in cells: `var(--bg)` bg, `var(--radius-sm)`.

### Filters
Priority toggles (`.priority-toggle`, pill-shaped, active state `var(--primary-soft)` + `var(--primary)` border). Label pills (`.filter-label-pill` in `.label-filters`). Search input (`#ticket-search`, min-width 200px). Active filter summary (`.filter-summary` > `.filter-pill` with dismiss ×, `.filter-clear-all`).

## Interaction Patterns

### Hover States
- **Cards** (`.card:hover`): `border-color → #bfdbfe`, `box-shadow → var(--shadow-md)`. No translateY transform.
- **Buttons** (`.btn:hover`): background shifts, border-color shifts to `var(--border-strong)`. Primary: `var(--primary-hover)` bg + `var(--shadow-md)`.
- **Nav links** (`.nav-link:hover`): `background → var(--bg)`, `color → var(--text)`.
- **Color swatches** (`.color-swatch:hover`): `scale(1.08)`.
- **Board manager cards** (`.board-card:hover`): `border-color → var(--border-strong)`, `background → var(--bg)`.

### Focus States
- **Focus ring pattern**: `outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(37,99,235,0.1);`
- Applied to: all form inputs, select elements, buttons (where explicitly styled)
- Visible focus is mandatory for accessibility — never `outline: none` without replacing it.

### Active / Pressed States
- **Primary buttons** hover darker but no explicit `:active` rule (relies on browser default).
- **Danger buttons** hover to `var(--danger-hover)`.
- **Disabled state**: `opacity: 0.6–0.7`, `cursor: not-allowed`. Applied via `:disabled` pseudo-class or `.killed` class.

### Transitions
- **Default (0.15s ease)**: `background`, `border-color`, `box-shadow`, `color`, `opacity` — used on cards, buttons, badges, nav links, inputs, toggles.
- **Slower (0.25s ease)**: `transform`, `opacity` — used on slide panels (`.slide-panel`), modal background (0.15s), assistant panel.

### Animations
| Animation | Duration | Effect | Used by |
|-----------|----------|--------|----------|
| `card-entrance` | 0.2s ease | fade + translateY(4px) | Board cards, groups |
| `fade-in` | 0.2s ease | fade + translateY(4px) | Groups on refresh |
| `modal-in` | 0.2s ease | fade + translateY(-10px) | Modal content |
| `modal-bg-in` | 0.15s ease | opacity 0 → 1 | Modal overlay |
| `toast-in` | 0.2s ease | slideX(1rem) from right | Toast notifications |
| `toast-out` | 0.2s ease | slideX(1rem) to right | Toast dismiss |
| `pulse-dot` | 1.5s infinite ease-in-out | scale(1→1.4→1) + opacity(1→0.6→1) | Running agent indicator |
| `skeleton-shimmer` | 1.5s infinite | background-position gradient sweep | Loading skeletons |

### Keyboard Handling
- **Enter**: triggers form submit/search on inputs; activates toggles/selects.
- **Escape**: closes modals, popover panels, label picker, notification panel.
- **Tab**: standard focus traversal through form fields and interactive elements.
- **Click-away**: closes notifications, label picker popover, slide panels.

### Loading States
- **Skeleton** (`.skeleton`): animated gradient shimmer (`skeleton-shimmer` animation). Variants: `.skeleton-text` (0.85rem height, bottom margin), `.skeleton-card` (4.5rem height, 1px border), `.board-skeleton` (full board skeleton container).

### Empty States
- **Empty class** (`.empty`): `color: var(--text-muted)`, `font-style: italic`, `text-align: center`, `padding: 2rem 1rem`. Used for empty lists, no-results states.

## Layout Patterns

### App Layout
Flex: `.sidebar` (fixed left, 220px, z-index 50) + `.main` (flex:1, margin-left: 220px). Mobile topbar toggles sidebar visibility via `.sidebar.open` + overlay.

| Breakpoint | Sidebar | Topbar | Main |
|------------|---------|--------|------|
| > 768px | Fixed left, visible | Hidden | Margin-left 220px |
| ≤ 768px | Hidden (`.open` to show) | Flex, sticky | Margin-left 0 |

### Page Layout
`.container` (max-width 1200px, centered, padding 1.5rem, `min-width: 0`). Page header: `.page-header` (flex, space-between, gap 1rem, wrap).

### Two-Column Detail
`.ticket-layout` — CSS Grid: `1fr 280px`. Main (`.ticket-main`) for content, Sticky sidebar (`.ticket-sidebar`) for metadata. Collapses to single column at ≤768px (sidebar moves above content with `order: -1`).

### Assistant Panel
Fixed panel (right side, 33.33vw, min 280px, max 60vw, resizable). Bubble at bottom-right (3.5rem circle). z-index 200 (closed) / 250 (open). At ≤640px: full-screen overlay, no resize.

### Notification Panel
Fixed top-right (0.5rem offset), 320px wide, z-index 100, max-height 400px. Dismiss per-item or clear-all.

### Sticky Elements
- Sidebar: `position: fixed; inset: 0 auto 0 0`
- Topbar: `position: sticky; top: 0`
- Ticket sidebar: `position: sticky; top: calc(var(--topbar-height, 0px) + 1.5rem)`
- Notification panel: `position: fixed; top: 0.5rem; right: 0.5rem`
