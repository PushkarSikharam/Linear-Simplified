import { useRef, useState } from "react";

export type CreateRecord<T> = (record: T, requestKey: string) => Promise<void>;

export function useRecordSubmit<T>() {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const request = useRef<{ body: string; key: string } | null>(null);

  async function submit(record: T, save: CreateRecord<T>) {
    if (pending.current) return;
    const body = JSON.stringify(record);
    if (request.current?.body !== body) request.current = { body, key: crypto.randomUUID() };
    pending.current = true;
    setSaving(true);
    setError(null);
    try {
      await save(record, request.current.key);
      request.current = null;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save. Please try again.");
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }

  return { saving, error, submit };
}
