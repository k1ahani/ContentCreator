# RTL UI Guidelines

## The rule

The application is `dir="rtl"` from `index.html` — RTL is the default for
everything, not a mode applied on top of an LTR-first design. Technical
content opts **into** LTR explicitly; nothing opts out of RTL.

## Use logical properties, never physical ones

Tailwind's logical-property utilities (`ms-`/`me-`, `ps-`/`pe-`, `start-`/`end-`)
flip automatically with `dir`; physical ones (`ml-`/`mr-`, `pl-`/`pr-`,
`left-`/`right-`) do not and will silently produce a mirrored, wrong layout in
RTL.

```tsx
// wrong - fixed to the visual right regardless of direction
<div className="mr-2 pl-4">

// right - "end" and "start" follow the reading direction
<div className="me-2 ps-4">
```

Grep the codebase for `ml-`, `mr-`, `pl-`, `pr-`, `left-`, `right-` before
merging a new component — a hit is very likely a bug, not a style choice.
`SubtitleTimeline.tsx`'s cue-edge handles are one of the few legitimate
exceptions (`start-0`/`end-0` are already used there correctly, since a
timeline scrubber has its own left-to-right time convention regardless of
page direction — see the LTR exception below).

## LTR islands for technical content

Requirement: file paths, CLI commands, code, JSON, URLs, and logs need LTR
containers inside the RTL interface — mixing directions incorrectly is
explicitly called out as something to avoid.

`frontend/src/styles/index.css` defines two utility classes for this:

```css
.ltr {
  direction: ltr;
  unicode-bidi: isolate;
  text-align: left;
  font-family: monospace;
}

.num {
  direction: ltr;
  unicode-bidi: isolate;
  display: inline-block;
}
```

- **`.ltr`** — for a whole block of technical content: the CLI console
  (`components/console/CliConsole.tsx`), file paths in the file picker
  (`components/media/FilePickerDialog.tsx`), raw JSON, code.
- **`.num`** — for a number embedded inline in Persian prose ("۱۲ فایل"),
  so a multi-digit figure doesn't visually reorder when it sits next to RTL
  text. Used throughout for byte sizes, durations, counts
  (`lib/format.ts`'s `formatNumber`/`formatBytes`/`formatDuration` pair with
  this class at every call site).

`unicode-bidi: isolate` matters as much as `direction: ltr` here — without
it, an LTR span next to RTL text can still have its *neighboring punctuation*
reordered by the browser's bidi algorithm, which is the subtle bug that makes
"mixing LTR and RTL incorrectly" visible even when the text itself looks
right in isolation.

## Timeline and scrubber components are a deliberate exception

`SubtitleTimeline.tsx` wraps its track in `dir="ltr"` regardless of the page's
own direction. A time-based scrubber has its own universal convention — time
increases left to right — and that convention is stronger than the page's
text direction. Forcing RTL on a timeline would make dragging feel backwards
to anyone who has used a video editor before, Persian-speaking or not. This is
the one place `dir` is overridden rather than respected, and it's intentional.

## Typography

Vazirmatn (loaded via Google Fonts in `index.html`, with Tahoma/Segoe UI/
sans-serif fallbacks — see `tailwind.config.js`'s `fontFamily.sans`) is the
default typeface everywhere. It's a variable Persian font designed for UI
text with good Latin coverage too, so mixed Persian/English content (a
translation task's two panes, for instance) doesn't require a font switch.

`body`'s `font-feature-settings` in `index.css` enables stylistic sets tuned
for legibility at UI sizes, not just print.

## Component-level checklist

When building or reviewing a component:

- [ ] Uses `ms-`/`me-`/`ps-`/`pe-`/`start-`/`end-`, never `ml-`/`mr-`/`pl-`/`pr-`/`left-`/`right-`
- [ ] Icons that imply direction (arrows, chevrons) point the right way for
      RTL — `lucide-react`'s `ArrowLeft` visually points toward the *start* of
      reading order in this app, which is correct for "back" navigation; check
      this deliberately rather than assuming
- [ ] Technical content (paths, code, JSON, logs, URLs) is wrapped in `.ltr`
- [ ] Inline numbers in Persian sentences use `.num` or
      `lib/format.ts`'s formatters
- [ ] Dialogs, dropdowns and tooltips anchor from the correct logical edge (test
      by toggling `dir` in devtools, not just by reading the JSX)
- [ ] Touch targets stay usable on mobile — see `docs/EXTENDING_THE_APPLICATION.md`'s
      responsive-design notes for a page

## Testing RTL correctness

There is no automated RTL-correctness test — this is a visual/interaction
property. When adding a component with any directional affordance (an arrow,
a drag handle, a swipe gesture), manually verify it in the running app rather
than trusting that Tailwind's logical classes alone guarantee correctness;
they guarantee the *box model* flips correctly, not that an icon or gesture
you hardcoded still makes sense.
