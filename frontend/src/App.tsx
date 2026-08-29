import { Routes, Route } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { ToastHost } from "@/components/ui";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { DashboardPage } from "@/pages/DashboardPage";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { ProjectLayout } from "@/pages/project/ProjectLayout";
import { ProjectOverviewPage } from "@/pages/project/ProjectOverviewPage";
import { AudioExtractPage } from "@/pages/project/AudioExtractPage";
import { TranscribePage } from "@/pages/project/TranscribePage";
import { TextEditPage } from "@/pages/project/TextEditPage";
import { SubtitlesPage } from "@/pages/project/SubtitlesPage";
import { SubtitleEditorPage } from "@/pages/project/SubtitleEditorPage";
import { SpeechPage } from "@/pages/project/SpeechPage";
import { ConsolePage } from "@/pages/ConsolePage";
import { SettingsPage } from "@/pages/SettingsPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/console" element={<ConsolePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>

        <Route path="/projects/:projectId" element={<ProjectLayout />}>
          <Route index element={<ProjectOverviewPage />} />
          <Route path="audio" element={<AudioExtractPage />} />
          <Route path="transcribe" element={<TranscribePage />} />
          <Route path="text" element={<TextEditPage />} />
          <Route path="subtitles" element={<SubtitlesPage />} />
          <Route path="subtitles/:trackId" element={<SubtitleEditorPage />} />
          <Route path="speech" element={<SpeechPage />} />
        </Route>

        <Route element={<AppShell />}>
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
      <ToastHost />
    </ErrorBoundary>
  );
}
