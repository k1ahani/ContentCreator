/**
 * Navigation structure, matching requirement 42 verbatim (§42 MAIN
 * APPLICATION NAVIGATION). Adding a section here plus a route in
 * `src/App.tsx` is the whole recipe for a new top-level page - see
 * docs/FRONTEND.md.
 */

import {
  LayoutDashboard,
  Folder,
  Terminal,
  Settings,
  AudioLines,
  Captions,
  FileText,
  Subtitles,
  Mic,
  type LucideIcon,
} from "lucide-react";

export interface NavLeaf {
  label: string;
  path: string;
  icon: LucideIcon;
}

export const NAVIGATION: NavLeaf[] = [
  { label: "داشبورد", path: "/", icon: LayoutDashboard },
  { label: "پروژه‌ها", path: "/projects", icon: Folder },
  { label: "کنسول هوش مصنوعی", path: "/console", icon: Terminal },
  { label: "تنظیمات", path: "/settings", icon: Settings },
];

/** Project-scoped navigation, shown once a project is open. */
export const PROJECT_NAVIGATION: NavLeaf[] = [
  { label: "بررسی کلی", path: "", icon: LayoutDashboard },
  { label: "استخراج صدا از ویدیو", path: "audio", icon: AudioLines },
  { label: "تبدیل صدا به متن", path: "transcribe", icon: Captions },
  { label: "ویرایش و ترجمه متن", path: "text", icon: FileText },
  { label: "زیرنویس", path: "subtitles", icon: Subtitles },
  { label: "تبدیل متن به صدا", path: "speech", icon: Mic },
];
