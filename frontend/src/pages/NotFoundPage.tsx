import { Link } from "react-router-dom";
import { FileQuestion } from "lucide-react";
import { Button, EmptyState } from "@/components/ui";

export function NotFoundPage() {
  return (
    <EmptyState
      icon={<FileQuestion size={40} />}
      title="این صفحه پیدا نشد"
      description="آدرس واردشده در برنامه وجود ندارد."
      action={
        <Link to="/">
          <Button variant="secondary">بازگشت به داشبورد</Button>
        </Link>
      }
    />
  );
}
