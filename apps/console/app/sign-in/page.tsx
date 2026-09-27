"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthCard } from "@pixel-console/components/auth-card";
import { Alert, Button, Field, Input } from "@pixel-console/components/ui";
import { INVALID_EMAIL, normalizeEmail } from "@pixel-console/lib/email";
import { requestEmailCode, signInMode, signInWithEmail, type SignInMode } from "@pixel-console/lib/pixel-api";

/**
 * A deployment either emails a one-time code or takes an address on its own, and only the server
 * knows which. Asking it first is what keeps this page honest: it used to promise an email in
 * every case, including where the hosting could not send one, so the only way to learn what this
 * Pixel actually does was to submit and wait for it to fail.
 */
const DESCRIPTION: Record<SignInMode, string> = {
  code: "We'll email you a one-time code. There is no password, and if you have not been here before this makes you a workspace of your own.",
  open: "Type the address you want your workspace under. There is no code and no password, and if you have not been here before this makes you a workspace of your own - come back to the same address and your products and people are where you left them.",
  disabled: "Sign-in is not switched on for this Pixel yet.",
};

export default function SignIn() {
  const router = useRouter();
  const [mode, setMode] = useState<SignInMode | null>(null);
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    let current = true;
    // A server that cannot be asked is treated as the ordinary case rather than as broken: the
    // code path is what every deployment has had, and it refuses clearly on its own if it is off.
    signInMode().then((found) => { if (current) setMode(found); },
      () => { if (current) setMode("code"); });
    return () => { current = false; };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (mode === null || mode === "disabled") return;
    const address = normalizeEmail(email);
    if (!address) { setError(INVALID_EMAIL); return; }
    setSending(true);
    try {
      if (mode === "open") {
        await signInWithEmail(address);
        router.replace("/console");
        return;
      }
      const challenge = await requestEmailCode(address);
      sessionStorage.setItem("pixel.email.challenge", JSON.stringify({ email: address, id: challenge.challenge_id }));
      router.push("/sign-in/verify");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sign-in could not start.");
    } finally { setSending(false); }
  }

  return (
    <AuthCard title="Sign in to Pixel"
      description={mode === null ? DESCRIPTION.code : DESCRIPTION[mode]}
      footer={<Link href="/demo">Explore the demo</Link>}>
      {mode === "disabled"
        ? <Alert tone="warn">Nobody can sign in here until whoever runs this Pixel turns sign-in on.</Alert>
        : <form className="px-stack" onSubmit={submit} noValidate>
            <Field label="Your email" error={error}>{(f) => (
              <Input id={f.id} describedBy={f.describedBy} invalid={f.invalid} type="email" autoComplete="email" inputMode="email"
                autoFocus value={email} onChange={(e) => { setEmail(e.target.value); setError(null); }} />
            )}</Field>
            <Button type="submit" variant="primary" loading={sending} disabled={mode === null}>
              {mode === "open" ? "Continue" : "Email me a code"}
            </Button>
          </form>}
    </AuthCard>
  );
}
