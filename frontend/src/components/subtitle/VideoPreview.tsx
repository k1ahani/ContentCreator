import { forwardRef, useEffect, useState } from "react";
import { assetUrl } from "@/lib/api/client";
import { cueBoxStyle, overlayContainerStyle } from "@/lib/subtitleStyle";
import type { SubtitleCue, SubtitleStyle } from "@/lib/api/types";

export interface VideoPreviewHandle {
  video: HTMLVideoElement | null;
}

export const VideoPreview = forwardRef<
  HTMLVideoElement,
  {
    assetId: string;
    currentTime: number;
    activeCue: SubtitleCue | null;
    style: SubtitleStyle;
    onTimeUpdate: (time: number) => void;
    onLoadedMetadata?: (duration: number) => void;
  }
>(function VideoPreview({ assetId, activeCue, style, onTimeUpdate, onLoadedMetadata }, ref) {
  const [containerEl, setContainerEl] = useState<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    if (!containerEl) return;
    const video = containerEl.querySelector("video");
    if (!video) return;

    const updateScale = () => {
      if (video.videoWidth > 0) {
        setScale(video.getBoundingClientRect().width / video.videoWidth);
      }
    };

    const observer = new ResizeObserver(updateScale);
    observer.observe(video);
    video.addEventListener("loadedmetadata", updateScale);
    return () => {
      observer.disconnect();
      video.removeEventListener("loadedmetadata", updateScale);
    };
  }, [containerEl]);

  return (
    // Outer flex centers the video when it renders narrower than the column
    // (a portrait/vertical source, or a very wide one capped by max-height).
    <div className="flex justify-center">
      {/* inline-block so this box shrink-wraps to the video's actual
          rendered size for any aspect ratio - the overlay below is
          absolutely positioned against this exact box, so if it were full
          width instead, a portrait video's subtitle margins would be
          computed against empty letterbox space rather than the frame. */}
      <div
        ref={setContainerEl}
        className="relative inline-block max-h-[65vh] overflow-hidden rounded-xl bg-black"
      >
        <video
          ref={ref}
          src={assetUrl(assetId)}
          controls
          // max-h caps a tall/portrait video so it can never dominate the
          // page (the original bug: a plain w-full video has no height
          // limit and grows as tall as its aspect ratio demands); max-w
          // caps a very wide one at the column width instead of overflowing.
          className="block max-h-[65vh] max-w-full"
          onTimeUpdate={(e) => onTimeUpdate(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => onLoadedMetadata?.(e.currentTarget.duration)}
        />
        {activeCue && (
          <div style={overlayContainerStyle(style)}>
            <div style={cueBoxStyle(style, scale)}>{activeCue.text}</div>
          </div>
        )}
      </div>
    </div>
  );
});
