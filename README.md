# پلتفرم محلی تولید محتوا با هوش مصنوعی

# Local AI Content Creator Platform

یک پلتفرم حرفه‌ای و محلی برای تولید محتوا: استخراج صدا از ویدیو، تبدیل گفتار به متن،
ویرایش و ترجمه متن با هوش مصنوعی، ساخت و ویرایش زیرنویس با تایم‌لاین، و تبدیل متن به
گفتار طبیعی. رابط کاربری کاملاً فارسی و راست‌به‌چپ (RTL) است و همه‌چیز به‌صورت محلی و
بدون نیاز به ورود به حساب کاربری اجرا می‌شود.

A local, single-user platform for content production: extract audio from
video, transcribe speech to text, edit and translate text with AI, build and
edit subtitles on a timeline, and synthesize natural speech from text. The UI
is fully Persian/RTL. Everything runs on your own machine — there is no login.

---

## پیش‌نیازها / Requirements

| ابزار / Tool | نسخه / Version | یادداشت / Notes |
|---|---|---|
| Windows | 10/11 | این پلتفرم فقط برای ویندوز طراحی شده است |
| [uv](https://docs.astral.sh/uv/) | latest | مدیریت محیط پایتون؛ اگر نصب نباشد، `setup.ps1` آن را نصب می‌کند |
| Node.js | 20+ | برای ساخت رابط کاربری |
| [Claude CLI](https://claude.com/claude-code) | latest | برای تمام ویژگی‌های هوش مصنوعی (ویرایش، ترجمه، بازبینی رونوشت) |
| FFmpeg | — | نیازی به نصب دستی نیست؛ `setup.ps1` یک نسخه ایستا دانلود می‌کند |

پایتون سیستمی لازم نیست — `uv` نسخه ۳.۱۲ پین‌شده را خودش فراهم می‌کند.
A system-wide Python install is not required — `uv` provisions a pinned 3.12.

---

## نصب و راه‌اندازی / Setup

```powershell
# یک‌بار اجرا شود / run once
.\scripts\setup.ps1

# اجرای برنامه / start the platform
.\start.bat
```

`setup.ps1` این کارها را انجام می‌دهد:

1. نصب `uv` در صورت نبودن آن
2. ساخت محیط مجازی پایتون ۳.۱۲ برای بک‌اند و نصب وابستگی‌ها
3. نصب موتور تبدیل گفتار به متن (`faster-whisper`) — با `-SkipAsr` می‌توان رد کرد
4. دانلود نسخه ایستای FFmpeg در `bin\ffmpeg\` (در صورت نبودن)
5. نصب وابستگی‌های فرانت‌اند و ساخت نسخه نهایی (`npm run build`)

پس از اجرای موفق، `start.bat` بک‌اند را اجرا می‌کند (که فرانت‌اند ساخته‌شده را نیز
سرو می‌کند)، منتظر آماده‌شدن آن می‌ماند و مرورگر را باز می‌کند.

Claude CLI باید جداگانه نصب و وارد حساب شده باشد. اگر به‌طور خودکار شناسایی نشد،
مسیر آن را از صفحه «تنظیمات ← هوش مصنوعی» وارد کنید.

The Claude CLI must be installed and logged in separately; if it is not
auto-detected, set its path from Settings → AI.

---

## توسعه / Development

```powershell
# بک‌اند با بارگذاری مجدد خودکار
cd backend
.venv\Scripts\python.exe -m app.main

# فرانت‌اند با Hot Module Reload، جداگانه
cd frontend
npm run dev   # http://localhost:5173, proxies /api to the backend
```

اجرای آزمون‌ها / running tests:

```powershell
cd backend
.venv\Scripts\python.exe -m pytest
```

۲۶۰+ آزمون واحد و یکپارچه‌سازی وجود دارد که روی FFmpeg، پایگاه‌داده SQLite و
(در صورت در دسترس بودن) Claude CLI واقعی اجرا می‌شوند — هیچ‌کدام mock نیستند.

260+ unit and integration tests exist and run against real FFmpeg, a real
SQLite database, and (when available) the real Claude CLI — nothing is mocked.

---

## ساختار پروژه / Project structure

```
ContentCreatorApp/
├── backend/          FastAPI + Python 3.12
│   └── app/
│       ├── ai/               provider-neutral AI layer (Claude today, GPT-ready)
│       ├── transcription/    speech-recognition layer (local Whisper)
│       ├── tts/               text-to-speech layer (Edge neural, SAPI5 offline)
│       ├── media/            FFmpeg integration, audio, subtitles, video
│       ├── jobs/              background job system + SSE event bus
│       ├── db/                SQLite connection, migrations, repositories
│       ├── domain/           framework-free domain models
│       ├── api/                FastAPI routers and schemas
│       └── services/          settings and cross-cutting services
├── frontend/         React + TypeScript + Vite, Persian RTL
├── bin/ffmpeg/       bundled FFmpeg (downloaded by setup.ps1)
├── storage/          projects, database, downloaded ASR models (gitignored)
├── config/           local overrides (app.json, models.json — gitignored)
├── docs/             architecture and extension documentation
└── scripts/          setup and maintenance scripts
```

See `docs/PROJECT_STRUCTURE.md` for the full breakdown and
`docs/ARCHITECTURE.md` for how the pieces fit together.

---

## مستندسازی برای عامل‌های هوش مصنوعی آینده / Documentation for future AI agents

پوشه `docs/` برای این ساخته شده که یک عامل کدنویسی هوش مصنوعی بتواند معماری،
قابلیت‌های موجود، قراردادها و نقاط توسعه پروژه را بدون خواندن کل کدبیس بفهمد.
پیش از تغییر هر بخش، سند مرتبط را در `docs/` بخوانید — قرارداد کامل در
`docs/DEVELOPMENT_GUIDE.md` توضیح داده شده است. برای افزودن قابلیت جدید،
`docs/EXTENDING_THE_APPLICATION.md` نقطه شروع است.

The `docs/` directory exists so a future AI coding agent can understand this
project's architecture, existing functionality, conventions, and extension
points without reading the whole codebase. Read the relevant doc before
touching a subsystem — the full convention is in `docs/DEVELOPMENT_GUIDE.md`.
To add a capability, start at `docs/EXTENDING_THE_APPLICATION.md`.

---

## عیب‌یابی / Troubleshooting

| مشکل / Issue | راه‌حل / Fix |
|---|---|
| «FFmpeg پیدا نشد» | `.\scripts\setup.ps1` را دوباره اجرا کنید، یا مسیر را در تنظیمات وارد کنید |
| «Claude CLI پیدا نشد» | نصب و ورود به حساب را با دستور `claude` در ترمینال بررسی کنید |
| «موتور تبدیل گفتار به متن نصب نشده» | `.\scripts\install_asr.ps1` را اجرا کنید |
| صفحه اصلی خالی/۵۰۳ نمایش می‌دهد | در پوشه `frontend`: `npm install && npm run build` |
| درگاه (port) در دسترس نیست | ویندوز محدوده‌هایی از پورت‌ها را برای Hyper-V رزرو می‌کند؛ برنامه به‌طور خودکار پورت آزاد بعدی را پیدا می‌کند — پورت واقعی در `logs\app.log` ثبت می‌شود |

جزئیات فنی کامل همیشه در `logs\app.log` ثبت می‌شود.
Full technical detail is always logged to `logs\app.log`.

---

## مجوز / License

پروژه شخصی — برای استفاده محلی. This is a personal local project.
