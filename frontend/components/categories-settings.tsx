"use client";

import { XIcon } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, UnauthenticatedError } from "@/lib/api";
import { redirectToLogin } from "@/lib/redirect-to-login";
import {
  addCategory,
  getCategories,
  removeCategory,
  type Categories,
} from "@/lib/thoughts";

/**
 * "Categories": the five fixed kinds, and the ones the user adds for their
 * proposal cards. Removing one leaves the thoughts that have it as they are.
 */
export function CategoriesSection() {
  const [categories, setCategories] = useState<Categories | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCategories()
      .then((loaded) => !cancelled && setCategories(loaded))
      .catch((caught: unknown) => {
        if (cancelled) return;
        if (caught instanceof UnauthenticatedError) redirectToLogin("/settings");
        else setError("The categories could not be loaded.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not change the categories.");
    } finally {
      setBusy(false);
    }
  }

  function add(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    void run(async () => {
      setCategories(await addCategory(name));
      setName("");
    });
  }

  function remove(category: string) {
    void run(async () => {
      await removeCategory(category);
      setCategories(
        (current) => current && { ...current, added: current.added.filter((c) => c !== category) },
      );
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Categories</CardTitle>
        <CardDescription>
          Each filed thought can have a category. Add your own next to the five fixed kinds.
          Removing one keeps it on the thoughts that already have it.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {categories && (
          <ul aria-label="Your categories" className="flex flex-wrap gap-1.5">
            {categories.fixed.map((category) => (
              <li key={category}>
                <Badge variant="secondary">{category}</Badge>
              </li>
            ))}
            {categories.added.map((category) => (
              <li key={category}>
                <Badge variant="outline" className="pr-0.5">
                  {category}
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`Remove ${category}`}
                    disabled={busy}
                    onClick={() => remove(category)}
                  >
                    <XIcon />
                  </Button>
                </Badge>
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={add} className="flex items-center gap-2">
          <Input
            aria-label="New category"
            placeholder="For example: recipe"
            value={name}
            maxLength={60}
            onChange={(event) => setName(event.target.value)}
          />
          <Button type="submit" disabled={busy || !name.trim()}>
            Add
          </Button>
        </form>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
