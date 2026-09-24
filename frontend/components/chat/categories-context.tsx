"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { FIXED_CATEGORIES, getCategories } from "@/lib/thoughts";

const CategoriesContext = createContext<string[] | null>(null);

/** Loads the user's categories once per chat page, for the proposal cards. */
export function CategoriesProvider({ children }: { children: ReactNode }) {
  const [categories, setCategories] = useState<string[]>(FIXED_CATEGORIES);

  useEffect(() => {
    let cancelled = false;
    getCategories()
      .then((loaded) => !cancelled && setCategories([...loaded.fixed, ...loaded.added]))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return <CategoriesContext.Provider value={categories}>{children}</CategoriesContext.Provider>;
}

/** The categories a card offers: the user's, or the fixed kinds outside a provider. */
export function useCategories(): string[] {
  return useContext(CategoriesContext) ?? FIXED_CATEGORIES;
}
