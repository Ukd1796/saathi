import { Suspense } from "react";
import { Shell } from "@/components/shell";

export default function DashLayout({ children }: LayoutProps<"/">) {
  return (
    <Suspense fallback={<div className="flex min-h-screen items-center justify-center text-sm text-muted">Loading…</div>}>
      <Shell>{children}</Shell>
    </Suspense>
  );
}
