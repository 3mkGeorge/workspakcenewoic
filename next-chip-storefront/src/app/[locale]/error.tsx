"use client";

import { useEffect } from "react";
import { ErrorView } from "@/components/client/status";

export default function LocaleError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return <ErrorView retry={retry} />;
}
