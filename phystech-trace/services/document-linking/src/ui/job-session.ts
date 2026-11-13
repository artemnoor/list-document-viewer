export const ACTIVE_JOB_STORAGE_KEY = "kfz-document-linking:active-job-id";

type StringStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function readActiveJobId(storage: StringStorage | undefined = typeof window === "undefined" ? undefined : window.sessionStorage): string | null {
  const value = storage?.getItem(ACTIVE_JOB_STORAGE_KEY)?.trim();
  return value || null;
}

export function saveActiveJobId(id: string, storage: StringStorage | undefined = typeof window === "undefined" ? undefined : window.sessionStorage): void {
  if (id.trim()) storage?.setItem(ACTIVE_JOB_STORAGE_KEY, id);
}

export function clearActiveJobId(storage: StringStorage | undefined = typeof window === "undefined" ? undefined : window.sessionStorage): void {
  storage?.removeItem(ACTIVE_JOB_STORAGE_KEY);
}
