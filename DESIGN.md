# Fractal Replay Journal Design Contract

## 1. Purpose and audience

This document codifies the existing Chrome extension overlay shown on TradingView. It is a preservation contract, not a redesign brief: later work must extend the same restrained, dark, compact operational surface.

The primary user is a trader reviewing a chart while replay is active. The overlay is secondary to the chart, so it must be fast to scan, movable, narrow, and visually quiet. The immediate workflow is to confirm extracted metadata, choose a moving-average crossover hypothesis, add a decision note, submit once for agent review, and read the stored review without leaving the chart.

The design dials are intentionally conservative: low visual variance, no decorative motion, and high information density. TradingView remains the dominant canvas.

## 2. Principles

1. **Operational, not promotional.** Use compact controls, direct labels, and one clear primary action. Do not add hero treatments, illustrations, gradients, or decorative cards.
2. **Chart first.** The closed dock occupies little space; the open sheet stays bounded and scrolls internally. The overlay must never become a full-page application on desktop.
3. **One accent, semantic states.** Violet denotes selection, focus, and the primary action. Green, amber, and red are reserved for success, warning, and error.
4. **Evidence before opinion.** Read-only extracted data, editable confirmed data, the user's hypothesis, and the agent review must remain visibly distinct.
5. **Progressive disclosure.** The dock exposes status and entry. The sheet exposes metadata and submission. Review content appears only after submission or when reopening a reviewed entry.
6. **Stable geometry.** Dynamic labels, loading text, warnings, and Korean copy must wrap inside fixed responsive bounds without resizing the overlay controls.
7. **No decorative motion.** Dragging and opening/closing are functional state changes. Any future transition must use only `transform` or `opacity`, respect reduced motion, and remain brief.

## 3. Declared tokens

These names document the current values. A later consolidation pass should expose them as CSS custom properties instead of repeating raw values.

### Color

| Token | Value | Use |
| --- | --- | --- |
| `color.panel` | `rgba(15, 16, 17, 0.94)` | Overlay material |
| `color.panel-solid` | `#0f1011` | Dark text on amber warning |
| `color.text` | `#f7f8f8` | Primary text and controls |
| `color.text-muted` | `#9ca3af` | Labels, kicker, hotkey, section titles |
| `color.border` | `rgba(247, 248, 248, 0.14)` | Default rim and dividers |
| `color.surface-subtle` | `rgba(255, 255, 255, 0.04)` | Sections and quiet action cells |
| `color.surface-control` | `rgba(255, 255, 255, 0.06)` | Fields, icon buttons, secondary buttons |
| `color.surface-divider` | `rgba(255, 255, 255, 0.08)` | Action-rail divider bed |
| `color.control-border` | `rgba(255, 255, 255, 0.12)` | Input and textarea border |
| `color.accent` | `#7170ff` | Primary action |
| `color.accent-soft` | `rgba(113, 112, 255, 0.075)` | Confirmed-data tint |
| `color.accent-status` | `rgba(113, 112, 255, 0.2)` | Checking/loading status fill |
| `color.accent-hover` | `rgba(113, 112, 255, 0.18)` | Secondary control hover |
| `color.accent-action-hover` | `rgba(113, 112, 255, 0.32)` | Action and segment hover |
| `color.accent-border` | `rgba(113, 112, 255, 0.35)` | Selected/confirmed border |
| `color.accent-border-status` | `rgba(113, 112, 255, 0.36)` | Checking/loading status border |
| `color.accent-border-hover` | `rgba(113, 112, 255, 0.55)` | Secondary control hover border |
| `color.focus` | `rgba(113, 112, 255, 0.8)` | Focus indicator |
| `color.success` | `#10b981` | Success semantic source |
| `color.success-soft` | `rgba(16, 185, 129, 0.16)` | Ready/saved/review-complete fill |
| `color.success-border` | `rgba(16, 185, 129, 0.35)` | Ready/saved/review-complete border |
| `color.warning` | `#fbbf24` | Warning chip fill |
| `color.warning-soft` | `rgba(251, 191, 36, 0.16)` | Warning status fill |
| `color.warning-border` | `rgba(251, 191, 36, 0.4)` | Warning status border |
| `color.danger` | `#ff6363` | Error semantic source |
| `color.danger-soft` | `rgba(255, 99, 99, 0.16)` | Error status fill |
| `color.danger-border` | `rgba(255, 99, 99, 0.42)` | Error status border |

The preview harness alone uses `#050607`, `rgba(255, 255, 255, 0.035)`, and `rgba(247, 248, 248, 0.12)` to simulate a chart. They are not product-surface tokens and must not enter extension UI code.

### Type

| Token | Value | Use |
| --- | --- | --- |
| `font.ui` | `Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif` | All UI copy |
| `font.data` | `"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace` | Data, fields, textarea |
| `type.10` | `10px / 1.2` | Warning chip |
| `type.11` | `11px / 1.2` | Labels, status, kicker, secondary controls |
| `type.12` | `12px / 1.2` | Buttons |
| `type.data` | `12px / 1.35` | Read-only and editable data |
| `type.title` | `15px / 1.3` | Dock and sheet title |
| `type.icon` | `20px / 1` | Existing close glyph only |
| `weight.regular` | `400` | Body/data default |
| `weight.action` | `700` | Secondary and rail actions |
| `weight.primary` | `800` | Primary Submit/entry action |

Letter spacing is always `0`. Kicker and section titles are uppercase; normal labels, status, notes, actions, and review prose are not transformed.

### Spacing and size

| Token | Value | Use |
| --- | --- | --- |
| `space.hairline` | `1px` | Borders and action separators |
| `space.2` | `2px` | Viewport-height border compensation only |
| `space.4` | `4px` | Field label and wrapped-data gaps |
| `space.5` | `5px` | Status vertical padding; warning radius |
| `space.6` | `6px` | Warning/secondary horizontal details |
| `space.8` | `8px` | Grid gap, control inset, compact section rhythm |
| `space.10` | `10px` | Section padding and vertical separation |
| `space.12` | `12px` | Header gap and lower utility/warning padding |
| `space.14` | `14px` | Overlay edge inset and main content gutter |
| `space.16` | `16px` | Desktop viewport offset |
| `control.icon` | `30px` square | Close control |
| `control.field` | `32px` | Text input height |
| `control.secondary` | `34px` minimum | Utility and segmented controls |
| `control.primary-compact` | `38px` minimum | Closed-dock primary action |
| `control.primary` | `42px` minimum | Submit action rail |
| `content.warning-min` | `22px` | Warning row reserve |
| `content.note` | `64px` | Initial textarea height |
| `status.max` | `150px` | Status pill maximum width |

Values `18px`, `28px`, and `50px` belong only to the current shadow geometry or textarea width calculation, not the spacing scale. Values `20px`, `30px`, `32px`, `34px`, `38px`, `42px`, and `64px` are component sizes, not general layout spacing.

### Radius and depth

| Token | Value | Use |
| --- | --- | --- |
| `radius.warning` | `5px` | Warning chip |
| `radius.control` | `6px` | Inputs and buttons |
| `radius.panel` | `8px` | Overlay and framed sections |
| `radius.pill` | `999px` | Status only |
| `depth.overlay` | `0 18px 50px rgba(0, 0, 0, 0.42)` | Floating overlay shadow |
| `layer.overlay` | `2147483647` | TradingView overlay stacking context |

No nested card elevation, blur filter, glow, inset shadow, or additional elevation tier is permitted. Panel translucency plus the single overlay shadow is the complete material recipe.

## 4. Responsive geometry

- **Closed dock, desktop:** fixed `right: 16px; bottom: 16px`; width `min(380px, calc(100vw - 32px))`. Its two-column grid is `minmax(0, 1fr) auto`, with the primary entry action and hotkey spanning both columns.
- **Open sheet, desktop:** fixed `top: 70px; right: 16px; bottom: auto`; width `min(448px, calc(100vw - 32px))`; maximum height `80vh`. The dock is hidden. Header and bottom Submit remain outside the internally scrolling `.fj-sheet-scroll` region.
- **Content grid:** two equal `minmax(0, 1fr)` tracks; wide fields span both. Main content uses a `14px` horizontal gutter and an `8px` grid gap.
- **Mobile breakpoint:** at `max-width: 480px`, use `8px` right/bottom offsets and `calc(100vw - 16px)` width. The open sheet anchors to the bottom, not the top, and grows to at most `92vh`. Metadata becomes one column.
- **Drag bounds:** both dock and sheet remain draggable but must be reclamped after opening, closing, resizing, or content geometry changes. Drag handles use grab/grabbing cursor and disable selection while dragging.
- **Overflow:** only the sheet body scrolls vertically. Fields use `100%` of their assigned grid track; the panel clips its own rounded boundary. Review copy, status, chips, and long Korean/English identifiers wrap; controls never create horizontal scrolling.
- **Preview-only geometry:** the `100vh` body, `15%/5%/52%` chart line, and `72px 48px` grid are fixture scenery, not product layout tokens.

## 5. Primitives and states

### Dock

The dock contains the product kicker, compact title, backend/review status, one violet entry button, and the keyboard hint. It has default, backend-checking, ready, warning, and error states. Dragging changes the cursor only. The entry button hover/focus/disabled states must use the shared accent/focus tokens and retain its `38px` minimum height.

### Sheet

The sheet contains a fixed header, one scroll region, and one fixed action rail. Closing saves the draft but does not submit. Submission must not close the sheet because loading and agent review are rendered in place. The sheet states are draft, validating, submitting, reviewing, reviewed, recoverable error, and retrying.

### Sections and fields

`.fj-section` is the only framed content primitive. Do not place a framed section inside another framed section. Extracted candidate data is read-only; confirmed scoring data is editable and receives the subtle violet confirmation tint. Labels use muted UI type; values use mono data type. Fields require default, hover, focus, invalid, disabled/read-only, and populated states. Invalid fields pair a danger border with adjacent text; color alone is insufficient.

### Hypothesis segmented control

Use one three-column segmented group for `Golden cross expected`, `Dead cross expected`, and `Uncertain`. This replaces directional Long/Short/Watch/Skip actions; it is evidence context, not the submit command. Each segment has a stable minimum height of `34px`, `11px` UI text, a shared group boundary, and default, hover, selected, keyboard-focus, and disabled states. The selected state uses `color.accent-action-hover` plus `color.accent-border`; it must also expose `aria-pressed="true"` or native radio semantics. On narrow/CJK layouts, labels may wrap to two lines without changing sibling widths.

### Primary Submit

There is one full-width `Submit for review` button in the fixed bottom rail, minimum height `42px`, `12px` text, weight `800`, violet fill, and white text. It replaces Save draft as a visible command and replaces the four decision buttons. Draft saving remains automatic and is communicated by status text. Submit states are default, hover, keyboard-focus, disabled for invalid/in-flight input, submitting, awaiting agent review, success, and recoverable error. The label may change to a concise progress phrase but button geometry must remain stable.

### Status

Status is a compact pill capped at `150px`, allowed to wrap anywhere. Checking/loading uses violet; ready, draft-saved, and review-complete use green; incomplete evidence/retry uses amber; submission/review failure uses red. Every status pairs color with text and a `data-status` value. Do not use color for confidence scoring.

### Review sections

Agent output appears below the submitted decision context in the existing scroll region. Use one summary header followed by flat, separated sections for: sufficient evidence, missing evidence, excessive or redundant evidence, contradictions, edited decision note, confidence, and review metadata. Avoid cards inside the sheet section. Lists use short rows and existing `10px`/`14px` rhythm; longer edited-note prose uses the UI font at `12px / 1.35`, not mono. Provide loading skeleton/placeholder rows with stable heights, complete, partial-data warning, empty/not-applicable, and error-with-retry states. Raw model output, prompts, and stack traces are never shown.

## 6. Accessibility and CJK constraints

- All buttons have accessible names. The close control must retain `aria-label="Close"` until localized; icon-only actions require a tooltip only when their symbol is unfamiliar.
- Keyboard order follows the visual order: header close, confirmed fields, hypothesis, note, utilities if retained, Submit, then review controls. `Cmd/Ctrl + Enter` submits the same single review action; it must not imply a hidden `watch` decision.
- Every interactive primitive needs a visible `color.focus` indicator with at least a `2px` effective outline/ring. Focus must not rely on border color alone, because the current `1px` field border is too subtle.
- Existing `30px`-`42px` controls are compact desktop targets. Where touch input is detected or at the mobile breakpoint, primary and segmented actions should provide a `44px` effective hit area without changing the visual density of desktop fields.
- Status, warning, invalid, and selected states use text or semantics in addition to color. Loading status uses `aria-live="polite"`; blocking submission failures use an alert-equivalent announcement.
- Korean copy must not be forced to uppercase. Keep letter spacing `0`, allow natural line breaking, and use the system-sans fallbacks when Inter lacks Hangul glyphs. Do not hard-code line breaks in Korean labels.
- Long provider symbols, ISO timestamps, warning identifiers, and mixed Korean/Latin notes use `overflow-wrap: anywhere` where necessary. Mono data may wrap; it must not shrink below `12px`.
- Text zoom to 200% and widths down to `320px` must preserve access to Submit and close without horizontal scroll or overlap. Respect `prefers-reduced-motion` for any later open/close transition.

## 7. Accepted debt and consolidation ledger

The following debt is accepted for the current extraction. Later UI work must consolidate it rather than introducing more raw values.

Interaction coverage already implemented is not debt: inputs, textareas, and all buttons share the `2px` `:focus-visible` ring; interactive controls nested in drag handles are excluded from pointer-drag capture; buttons share disabled feedback; and the primary Submit implements hover plus distinct, disabled `saving` and `reviewing` phases with stable progress labels.

| Debt | Current raw values / location | Required follow-up |
| --- | --- | --- |
| Color variants bypass variables | White surfaces `0.04/0.06/0.08/0.12`; accent alpha `0.075/0.18/0.20/0.32/0.35/0.36/0.55/0.80`; semantic fills/borders `0.16/0.35/0.40/0.42` in `styles.css` and `actions.css` | Add the declared color custom properties and replace raw declarations. |
| Spacing and component sizes bypass variables | `1, 2, 4, 5, 6, 8, 10, 12, 14, 16, 22, 28, 30, 32, 34, 38, 42, 64px` plus shadow `18/50px` | Add spacing/component custom properties; do not incorrectly promote component sizes to general spacing. |
| Type is only partially explicit | Browser-default regular weight; `10/11/12/15/20px`, weights `700/800`, line heights `1/1.2/1.3/1.35`; Inter and JetBrains Mono are referenced but not bundled | Centralize type tokens and verify actual extension font availability. Keep the current fallback behavior unless font loading is deliberately added. |
| Radius values bypass variables | `5px`, `6px`, `8px`, `999px` | Add radius custom properties; preserve the component-specific rule. |
| Panel repositioning is pointer-only | Dock/header drag handles preserve focus and activation for their nested buttons, but the drag surfaces themselves are not keyboard-operable | Keep the implemented control focus behavior; add a separately labelled keyboard move affordance only if keyboard repositioning becomes a product requirement. |
| Close icon is a text glyph | `×` at `20px / 1` | Replace with the project's single established icon family when one is adopted; do not hand-draw an SVG. |
| Preview values are fixture-local | `#050607`, white `0.035`, text `0.12`; `100vh`, `15%`, `5%`, `52%`, `72px`, `48px` | Keep out of production tokens. A preview cleanup may use `100dvh`, but it is outside product scope. |
| Responsive coverage stops at 480px | Only desktop and mobile rules exist | Preserve current geometry; verify `320`, `375`, `480`, `768`, and `1280px` when product UI changes are implemented. |
| Motion remains intentionally absent | Hypothesis selection, Submit-for-review state changes, automatic draft status, capture acknowledgement, and agent review sections are implemented without decorative transitions | Keep future motion functional, GPU-composited, brief, and reduced-motion aware. |

Implemented review primitives are `.fj-review-section`, `.fj-review-summary`, `.fj-review-block`, `.fj-review-list`, `.fj-review-risk`, `.fj-review-meta`, and `.fj-retry-review`. They use flat separators rather than nested cards, keep Korean prose on natural word boundaries with an emergency overflow fallback, and expose ready, failed, empty-list, risk, evidence-summary, and capture-ID retry states.

`overall_assessment` is the supported confidence and decision-quality signal for Hermes review. A separate numeric confidence value is intentionally absent because the current evidence contract does not calibrate a meaningful probability. Ready and failed results retain the same flat section headings; empty evidence categories render `None identified` rather than disappearing.

Cross-check result: every existing raw color, font family, font size/weight/line-height family, spacing family, radius, shadow, overlay width/height, breakpoint, and preview-only geometry found in `extension/src/styles.css`, `extension/src/actions.css`, and `extension/preview.html` is either declared above or explicitly classified as fixture-only/component geometry. The debt table identifies all values that are documented but still undeclared in product CSS and therefore require consolidation by the implementation worker.
