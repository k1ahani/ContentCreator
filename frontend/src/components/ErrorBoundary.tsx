import { Component, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: unknown) {
    console.error("[ErrorBoundary]", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50 p-6 text-center dark:bg-slate-950">
          <div className="rounded-full bg-red-100 p-3 text-red-600 dark:bg-red-950 dark:text-red-400">
            <AlertTriangle size={28} />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              خطای غیرمنتظره‌ای رخ داد
            </h1>
            <p className="mt-1 max-w-md text-sm text-slate-500 dark:text-slate-400">
              رابط کاربری با خطا مواجه شد. می‌توانید صفحه را دوباره بارگذاری کنید.
            </p>
          </div>
          <Button onClick={() => window.location.reload()}>بارگذاری دوباره</Button>
        </div>
      );
    }
    return this.props.children;
  }
}
