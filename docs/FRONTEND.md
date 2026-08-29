# Frontend

## Purpose

Structure and conventions of the React frontend. Read `docs/RTL_UI_GUIDELINES.md`
alongside this for the Persian/RTL-specific rules — they're kept separate
because RTL correctness is a cross-cutting concern every page has to get
right, not a feature of any one part of the tree.

## Stack, and why

- **React + TypeScript + Vite** — fast dev server, no framework lock-in
  beyond React itself, good TypeScript support out of the box.
- **Tailwind CSS** — utility classes handle RTL naturally via logical
  properties (`ms-`/`me-`/`ps-`/`pe-` instead of `ml-`/`mr-`/`pl-`/`pr-`),
  which matters enormously for a genuinely bidirectional UI — see
  `docs/RTL_UI_GUIDELINES.md`.
- **TanStack Query (React Query)** — all server state (projects, jobs,
  documents, subtitle tracks, settings) lives here, not in component state or
  a global store. It handles caching, refetch-on-mutation invalidation, and
  loading/error states uniformly.
- **Zustand** — only for genuinely client-only UI state: theme and the mobile
  sidebar drawer (`frontend/src/store/uiStore.ts`). Nothing server-derived
  belongs here.
- **react-router-dom** — standard nested routing; project-scoped pages nest
  under `/projects/:projectId/*` via `ProjectLayout`.

No component library (shadcn, MUI, etc.) — every primitive in
`components/ui/` is hand-built specifically to be RTL-correct and Persian-
typography-aware from the ground up, which a library retrofitted with `dir`
support tends not to get entirely right.

## Directory structure

```
frontend/src/
├── lib/
│   ├── api/
│   │   ├── client.ts        fetch wrapper, ApiError (carries the backend's Persian message)
│   │   ├── types.ts          hand-mirrored types from backend Pydantic models
│   │   ├── resources.ts      typed calls, grouped by backend router
│   │   └── events.ts          shared EventSource + job event bus
│   ├── format.ts              Persian number/date/duration formatting
│   └── subtitleStyle.ts        SubtitleStyle -> CSS (mirrors backend's -> ASS)
│
├── hooks/
│   ├── useJobRunner.ts         start a job, track it live (the core feature-page hook)
│   ├── useJobWatcher.ts        watch an EXISTING job (used by the AI console)
│   └── useProject.ts           resolve :projectId from the route
│
├── components/
│   ├── ui/                     Button, Card, Dialog, Toast, Tabs, Input, ... (RTL-correct primitives)
│   ├── layout/                 AppShell, Sidebar (desktop rail + mobile drawer), Header, navigation.ts
│   ├── ai/                     ModelSelector (the "مدل پیشنهادی" panel)
│   ├── console/                CliConsole (live LTR-inside-RTL log viewer)
│   ├── media/                  FilePickerDialog (backend filesystem browse)
│   ├── subtitle/                VideoPreview, SubtitleTimeline, CueDetailPanel, StylePanel
│   └── tts/                     SpeechSegmentEditor (structured text+pause list)
│
├── pages/
│   ├── DashboardPage, ProjectsPage, ConsolePage, SettingsPage, NotFoundPage
│   └── project/                 ProjectLayout + one page per feature (Audio/Transcribe/Text/Subtitles/Speech)
│
├── store/uiStore.ts             theme + mobile drawer only
├── App.tsx                       route table
└── main.tsx                       React root, QueryClientProvider, BrowserRouter
```

## The core pattern: `useJobRunner`

Every feature page (audio extraction, transcription, text editing, subtitle
generate/render, TTS) follows the same shape, built on
`frontend/src/hooks/useJobRunner.ts`:

```tsx
const runner = useJobRunner((job) => {
  // called once, when the job completes successfully
});

const start = () => runner.run(() => jobsApi.extractAudio(projectId, assetId, preset));

// runner.status, runner.progress, runner.stage, runner.logs, runner.error
// runner.cancel(), runner.reset()
```

`useJobRunner` submits the job, subscribes to the shared SSE bus filtered by
that job's id (`frontend/src/lib/api/events.ts`), and accumulates progress/log
events into local state. A page never talks to `/api/jobs/*` or
`/api/events` directly — this hook is the only integration point, which is
what keeps six otherwise-similar feature pages from six slightly-different
job-tracking implementations.

`useJobWatcher` is the counterpart for the AI console page
(`frontend/src/pages/ConsolePage.tsx`), which needs to attach to a job the
*user* picks from history — possibly already running, possibly finished —
rather than one this page instance started.

## Data flow

Server state only ever flows through React Query:

```tsx
const { data, isLoading } = useQuery({
  queryKey: ["assets", projectId],
  queryFn: () => assetsApi.list(projectId),
});
```

Mutations invalidate the relevant query keys on success
(`queryClient.invalidateQueries`); `useJobRunner`'s completion handler
additionally invalidates `assets`, `documents`, `subtitleTracks`, `jobs` and
`project` broadly on every job completion, since almost every job mutates at
least one of those.

## Adding a page

1. Create `frontend/src/pages/<Name>Page.tsx` (or under `pages/project/` if
   it's project-scoped).
2. Add the route in `frontend/src/App.tsx`.
3. Add a nav entry to `NAVIGATION` or `PROJECT_NAVIGATION` in
   `frontend/src/components/layout/navigation.ts` (uses a `lucide-react` icon
   component, not a string name — see the file for the pattern).
4. If it starts jobs, use `useJobRunner`; if it lists/creates resources, add
   the typed calls to `frontend/src/lib/api/resources.ts` first (and the
   types to `types.ts` if the backend added a new shape).

## Common mistakes

- **A model, provider, or voice name typed directly into JSX.** Everything
  AI-related renders from `GET /api/ai/*` — see `docs/AI_MODELS.md`. A
  hardcoded `<option>Sonnet</option>` is a regression.
- **Fetching in a `useEffect` instead of `useQuery`.** Breaks caching,
  refetch-on-invalidation, and loading-state consistency with the rest of the
  app.
- **Forgetting `.ltr` on technical content.** See
  `docs/RTL_UI_GUIDELINES.md` — file paths, CLI output, JSON, and numbers in
  some contexts need explicit LTR treatment inside the RTL page.
- **Building a new job-tracking mechanism instead of `useJobRunner`.** If a
  page needs live progress for something it started, it needs
  `useJobRunner`, not a hand-rolled `EventSource` or polling loop.

## Type sync with the backend

`frontend/src/lib/api/types.ts` is hand-mirrored from the backend's Pydantic
models — there's no codegen step. When a backend domain model or schema
changes shape, update the corresponding TypeScript interface in the same
change. A mismatch surfaces as a TypeScript error at the call site in
`resources.ts`, which is the safety net this manual approach relies on — run
`npm run typecheck` after any backend schema change that could affect the
frontend.
