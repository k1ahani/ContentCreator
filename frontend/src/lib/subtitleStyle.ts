/**
 * SubtitleStyle -> CSS.
 *
 * Mirrors `backend/app/media/subtitles/style.py` (which targets ASS/libass)
 * so the live preview in the browser and the burned-in render agree on what
 * a style actually looks like. Keep the two in step when either changes -
 * see docs/SUBTITLE_SYSTEM.md.
 */

import type { CSSProperties } from "react";
import type { SubtitleStyle } from "@/lib/api/types";

function hexToRgba(hex: string, opacity: number): string {
  const clean = hex.replace("#", "");
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

const positionAlign: Record<SubtitleStyle["position"], CSSProperties["alignItems"]> = {
  top: "flex-start",
  middle: "center",
  bottom: "flex-end",
};

const textAlign: Record<SubtitleStyle["alignment"], CSSProperties["textAlign"]> = {
  left: "left",
  center: "center",
  right: "right",
};

/** CSS for the overlay container positioned over the video. */
export function overlayContainerStyle(style: SubtitleStyle): CSSProperties {
  return {
    position: "absolute",
    inset: 0,
    display: "flex",
    flexDirection: "column",
    alignItems: positionAlign[style.position],
    padding: `${style.margin_vertical / 20}% ${style.margin_horizontal / 20}%`,
    pointerEvents: "none",
  };
}

/**
 * CSS for the cue text box itself.
 *
 * `scale` is the video's on-screen rendered width divided by its native pixel
 * width (`videoWidth`). The backend authors the ASS script against the
 * source video's own resolution (see `render_subtitles` in
 * `backend/app/media/video.py`, which passes `probe.width`/`probe.height` as
 * PlayRes), so this keeps the preview's relative font size in step with what
 * the burned-in render will produce regardless of how big the player is
 * on screen.
 */
export function cueBoxStyle(style: SubtitleStyle, scale: number): CSSProperties {
  const hasBackground = style.background_opacity > 0;
  const outline = Math.max(0.5, style.outline_width * scale);
  return {
    fontFamily: `"${style.font_family}", Vazirmatn, Tahoma, sans-serif`,
    fontSize: `${Math.max(8, style.font_size * scale)}px`,
    fontWeight: style.bold ? 700 : 400,
    fontStyle: style.italic ? "italic" : "normal",
    color: style.text_color,
    textAlign: textAlign[style.alignment],
    backgroundColor: hasBackground ? hexToRgba(style.background_color, style.background_opacity) : "transparent",
    padding: hasBackground ? "0.2em 0.5em" : 0,
    borderRadius: hasBackground ? "0.2em" : 0,
    textShadow: hasBackground
      ? "none"
      : [
          `-${outline}px -${outline}px 0 ${style.outline_color}`,
          `${outline}px -${outline}px 0 ${style.outline_color}`,
          `-${outline}px ${outline}px 0 ${style.outline_color}`,
          `${outline}px ${outline}px 0 ${style.outline_color}`,
          style.shadow_depth > 0
            ? `${style.shadow_depth * scale}px ${style.shadow_depth * scale}px 2px rgba(0,0,0,0.6)`
            : "",
        ]
          .filter(Boolean)
          .join(", "),
    maxWidth: "90%",
    lineHeight: 1.4,
    whiteSpace: "pre-wrap",
  };
}

export const DEFAULT_SUBTITLE_STYLE: SubtitleStyle = {
  font_family: "Vazirmatn",
  font_size: 28,
  bold: false,
  italic: false,
  text_color: "#FFFFFF",
  background_color: "#000000",
  background_opacity: 0.65,
  outline_color: "#000000",
  outline_width: 2,
  shadow_depth: 0,
  position: "bottom",
  alignment: "center",
  margin_vertical: 40,
  margin_horizontal: 60,
};

export const FONT_OPTIONS = ["Vazirmatn", "Tahoma", "Arial", "Segoe UI", "IRANSans", "B Nazanin"];
