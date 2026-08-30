"""Windows SAPI5 speech synthesis via System.Speech.

The fully offline provider. It drives ``System.Speech.Synthesis`` through
PowerShell rather than through a Python COM binding, which avoids adding
``pywin32`` as a dependency for one narrow feature.

Honest limitations, surfaced in the UI rather than hidden:

* Voices are whatever is installed on the machine. A stock Windows install has
  English voices and, unless the user installed a Persian language pack, **no
  Persian voice at all**. :meth:`list_voices` reports what is actually there.
* Quality is dated compared with neural voices.
* There is no pitch control through this API surface, so ``supports_pitch`` is
  false and the pitch setting is ignored - reported, not silently dropped.

The generated script is written to a temporary ``.ps1`` file and executed with
``-File``. Passing it inline with ``-Command`` would mean the text has to
survive PowerShell quoting rules, and Persian text with apostrophes would break
it. Writing a UTF-8 BOM file and having PowerShell read the text back from a
separate UTF-8 file avoids the quoting problem entirely.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.core.errors import ProcessCancelledError, TTSError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.paths import PATHS
from app.domain.enums import Language, SpeakingStyle, VoiceAge, VoiceGender
from app.domain.tts import SpeechOptions, VoiceSpec
from app.process import CancelToken, ProcessSpec, run_process
from app.tts.base import LogCallback, TTSProvider, TTSProviderInfo

logger = get_logger(__name__)

POWERSHELL = "powershell.exe"

#: Enumerate installed voices as JSON.
_LIST_VOICES_SCRIPT = """
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = @()
foreach ($v in $synth.GetInstalledVoices()) {
    if (-not $v.Enabled) { continue }
    $info = $v.VoiceInfo
    $voices += [pscustomobject]@{
        Name    = $info.Name
        Culture = $info.Culture.Name
        Gender  = $info.Gender.ToString()
        Age     = $info.Age.ToString()
        Desc    = $info.Description
    }
}
$synth.Dispose()
$voices | ConvertTo-Json -Compress -Depth 3
"""

#: Synthesise to a wave file. Paths and text arrive as arguments/files so no
#: user-controlled string is ever interpolated into the script body.
_SPEAK_SCRIPT = """
param(
    [Parameter(Mandatory=$true)][string]$TextFile,
    [Parameter(Mandatory=$true)][string]$OutFile,
    [Parameter(Mandatory=$true)][string]$VoiceName,
    [Parameter(Mandatory=$true)][int]$Rate,
    [Parameter(Mandatory=$true)][int]$Volume
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    if ($VoiceName -ne '') { $synth.SelectVoice($VoiceName) }
    $synth.Rate = $Rate
    $synth.Volume = $Volume
    $synth.SetOutputToWaveFile($OutFile)
    $synth.Speak($text)
} finally {
    $synth.Dispose()
}
"""


class Sapi5Provider(TTSProvider):
    """Offline Windows speech synthesis."""

    id = "sapi5"
    display_name = "صدای ویندوز (آفلاین)"

    def __init__(self) -> None:
        self._voice_cache: list[VoiceSpec] | None = None

    # -- availability ------------------------------------------------------

    def check_availability(self) -> TTSProviderInfo:
        info = TTSProviderInfo(
            id=self.id,
            display_name=self.display_name,
            offline=True,
            supports_pitch=False,
            supports_styles=False,
        )

        if os.name != "nt":
            info.available = False
            info.unavailable_reason = "این موتور فقط روی ویندوز کار می‌کند."
            return info

        try:
            voices = self.list_voices()
        except Exception as exc:
            logger.info("SAPI5 probe failed: %s", exc)
            info.available = False
            info.unavailable_reason = "دسترسی به موتور گفتار ویندوز ممکن نشد."
            return info

        info.voice_count = len(voices)
        info.supported_languages = sorted(
            {voice.language for voice in voices}, key=lambda lang: lang.value
        )

        if not voices:
            info.available = False
            info.unavailable_reason = "هیچ صدای نصب‌شده‌ای در ویندوز پیدا نشد."
            info.hint = "از «تنظیمات ویندوز ← زمان و زبان ← گفتار» صدا نصب کنید."
            return info

        info.available = True
        if not any(voice.language == Language.PERSIAN for voice in voices):
            # Not a failure - the provider works, just not for Persian.
            info.hint = (
                "هیچ صدای فارسی روی این سیستم نصب نیست. برای فارسی از موتور "
                "«صداهای عصبی مایکروسافت» استفاده کنید."
            )
        return info

    # -- voices ------------------------------------------------------------

    def list_voices(self, language: Language | None = None) -> list[VoiceSpec]:
        if self._voice_cache is None:
            self._voice_cache = self._query_voices()
        voices = self._voice_cache
        if language is not None:
            voices = [voice for voice in voices if voice.language == language]
        return voices

    def _query_voices(self) -> list[VoiceSpec]:
        if os.name != "nt":
            return []

        script_path = self._write_script(_LIST_VOICES_SCRIPT, "list_voices")
        try:
            result = run_process(
                ProcessSpec(
                    argv=[
                        POWERSHELL,
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(script_path),
                    ],
                    timeout_seconds=60,
                ),
                check=False,
            )
        finally:
            script_path.unlink(missing_ok=True)

        if result.exit_code != 0 or not result.stdout.strip():
            logger.info("could not enumerate SAPI voices: %s", result.stderr[:300])
            return []

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.info("SAPI voice listing was not valid JSON")
            return []

        # ConvertTo-Json emits an object, not an array, for a single voice.
        entries = payload if isinstance(payload, list) else [payload]

        voices: list[VoiceSpec] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            culture = str(entry.get("Culture") or "")
            language = _culture_to_language(culture)
            if language is None:
                # A voice for a language the platform does not model yet.
                continue
            voices.append(
                VoiceSpec(
                    id=str(entry.get("Name") or ""),
                    provider=self.id,
                    name=f"{entry.get('Name')} ({culture})",
                    language=language,
                    locale=culture,
                    gender=_map_gender(str(entry.get("Gender") or "")),
                    age=_map_age(str(entry.get("Age") or "")),
                    styles=[SpeakingStyle.NEUTRAL],
                    supports_pitch=False,
                    supports_rate=True,
                    description=str(entry.get("Desc") or ""),
                )
            )
        return voices

    # -- synthesis ---------------------------------------------------------

    def synthesize(
        self,
        text: str,
        options: SpeechOptions,
        output_path: Path,
        *,
        on_log: LogCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        if os.name != "nt":
            raise TTSError(
                "SAPI5 is only available on Windows",
                user_message="این موتور فقط روی ویندوز کار می‌کند.",
            )
        if not text.strip():
            raise TTSError(
                "refusing to synthesize empty text",
                user_message="متنی برای تبدیل به گفتار وجود ندارد.",
            )

        # SAPI writes WAV only. The assembler converts to the requested format.
        if output_path.suffix.lower() != ".wav":
            output_path = output_path.with_suffix(".wav")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        temp_dir = PATHS.storage / ".tts-temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        text_file = temp_dir / f"say_{new_id()}.txt"
        text_file.write_text(text, encoding="utf-8")
        script_path = self._write_script(_SPEAK_SCRIPT, "speak")

        # System.Speech rate is -10..10, where 0 is the natural rate.
        rate = max(-10, min(10, round((options.rate - 1.0) * 10)))
        volume = max(0, min(100, round(options.volume * 100)))

        if on_log:
            on_log(
                "system",
                f"sapi5 voice={options.voice_id!r} rate={rate} volume={volume} chars={len(text)}",
            )

        try:
            result = run_process(
                ProcessSpec(
                    argv=[
                        POWERSHELL,
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(script_path),
                        "-TextFile",
                        str(text_file),
                        "-OutFile",
                        str(output_path),
                        "-VoiceName",
                        options.voice_id or "",
                        "-Rate",
                        str(rate),
                        "-Volume",
                        str(volume),
                    ],
                    timeout_seconds=600,
                ),
                cancel_token=cancel_token,
                check=False,
            )
        finally:
            text_file.unlink(missing_ok=True)
            script_path.unlink(missing_ok=True)

        if cancel_token is not None and cancel_token.cancelled:
            output_path.unlink(missing_ok=True)
            raise ProcessCancelledError("synthesis cancelled by user")

        if result.exit_code != 0:
            output_path.unlink(missing_ok=True)
            raise TTSError(
                f"SAPI5 synthesis failed ({result.exit_code}): {result.stderr[:400]}",
                user_message="تولید گفتار با موتور ویندوز انجام نشد.",
                hint="صدای انتخاب‌شده ممکن است دیگر نصب نباشد. صدای دیگری انتخاب کنید.",
            )

        if not output_path.is_file() or output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            raise TTSError(
                "SAPI5 produced no audio",
                user_message="موتور گفتار ویندوز خروجی صوتی تولید نکرد.",
            )

        return output_path

    @staticmethod
    def _write_script(body: str, name: str) -> Path:
        temp_dir = PATHS.storage / ".tts-temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        path = temp_dir / f"{name}_{new_id()}.ps1"
        # BOM so PowerShell reads the file as UTF-8 regardless of code page.
        path.write_text(body, encoding="utf-8-sig")
        return path


def _culture_to_language(culture: str) -> Language | None:
    """Map a .NET culture name such as ``fa-IR`` onto a supported language."""
    prefix = culture.split("-")[0].lower()
    for language in Language:
        if language.value == prefix:
            return language
    return None


def _map_gender(value: str) -> VoiceGender:
    lowered = value.lower()
    if "female" in lowered:
        return VoiceGender.FEMALE
    if "male" in lowered:
        return VoiceGender.MALE
    return VoiceGender.UNKNOWN


def _map_age(value: str) -> VoiceAge:
    lowered = value.lower()
    if "child" in lowered or "teen" in lowered:
        return VoiceAge.YOUNG
    if "senior" in lowered:
        return VoiceAge.MATURE
    if "adult" in lowered:
        return VoiceAge.ADULT
    return VoiceAge.UNKNOWN
