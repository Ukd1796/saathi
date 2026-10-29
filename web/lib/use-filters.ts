"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

/**
 * Filter state kept in the URL query (?area=Bandra&sort=last), so it survives back/refresh and
 * can be shared. Keys at their default value are left out of the URL.
 */
export function useFilters<T extends Record<string, string>>(defaults: T) {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const values = useMemo(
    () => Object.fromEntries(Object.entries(defaults).map(([k, d]) => [k, params.get(k) ?? d])) as T,
    // eslint-disable-next-line react-hooks/exhaustive-deps -- defaults is a literal per page
    [params],
  );

  const set = useCallback((patch: Partial<T>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === defaults[k]) next.delete(k);
      else next.set(k, v as string);
    }
    const qs = next.toString();
    router.replace(qs ? `${path}?${qs}` : path, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, path, router]);

  const reset = useCallback(() => router.replace(path, { scroll: false }), [path, router]);
  const active = Object.entries(defaults).filter(([k, d]) => values[k] !== d).length;
  return { values, set, reset, active };
}
