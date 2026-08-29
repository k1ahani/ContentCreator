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
    <div ref={setContainerEl} className="relative overflow-hidden rounded-xl bg-black">
      <video
        ref={ref}
        src={assetUrl(assetId)}
        controls
        className="w-full"
        onTimeUpdate={(e) => onTimeUpdate(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => onLoadedMetadata?.(e.currentTarget.duration)}
      />
      {activeCue && (
        <div style={overlayContainerStyle(style)}>
          <div style={cueBoxStyle(style, scale)}>{activeCue.text}</div>
        </div>
      )}
    </div>
  );
});
