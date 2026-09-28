"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthCard } from "@pixel-console/components/auth-card";
import { Alert, Button, Field, Input } from "@pixel-console/components/ui";
import { INVALID_EMAIL, normalizeEmail } from "@pixel-console/lib/email";
import {
  requestEmailCode, signInMode, signInWithEmail, signUpWithEmail, type SignInMode,
} from "@pixel-console/lib/pixel-api";

/**
 * A deployment either emails a one-time code or takes an address on its own, and only the server
 * knows which. Asking it first is what keeps this page honest: it used to promise an email in
 * every case, including where the hosting could not send one, so the only way to learn what this
 * Pixel actually does was to submit and wait for it to fail.
 */
const DESCRIPTION: Record<SignInMode, string> = {
  code: "We'll email you a one-time code. There is no password, and if you have not been here before this makes you a workspace of your own.",
  open: "Use your email to return to your workspace. New here? Create a workspace first, then this same email brings you back to it.",
  disabled: "Sign-in is not switched on for this Pixel yet.",
};

export default function SignIn() {
  const router = useRouter();
  const [mode, setMode] = useState<SignInMode | null>(null);
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [openFlow, setOpenFlow] = useState<"sign-in" | "sign-up">("sign-in");
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
        if (openFlow === "sign-up") {
          // A new workspace needs a human name from the start. A returning workspace does not:
          // its name, products and records are already on the account.
          const first = firstName.trim();
          const last = lastName.trim();
          if (!first || !last) { setError("Enter your first and last name."); setSending(false); return; }
          await signUpWithEmail(address, first, last);
        } else {
          await signInWithEmail(address);
        }
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
      footer={<Link href="/demo">Visit demo</Link>}>
      {mode === "disabled"
        ? <Alert tone="warn">Nobody can sign in here until whoever runs this Pixel turns sign-in on.</Alert>
        : <form className="px-stack" onSubmit={submit} noValidate>
            {mode === "open" ? (
              <div className="px-row" role="group" aria-label="Sign in or create an account">
                <Button type="button" aria-pressed={openFlow === "sign-in"}
                  variant={openFlow === "sign-in" ? "primary" : "ghost"}
                  onClick={() => { setOpenFlow("sign-in"); setError(null); }}>
                  Sign in
                </Button>
                <Button type="button" aria-pressed={openFlow === "sign-up"}
                  variant={openFlow === "sign-up" ? "primary" : "ghost"}
                  onClick={() => { setOpenFlow("sign-up"); setError(null); }}>
                  Create account
                </Button>
              </div>
            ) : null}
            {mode === "open" && openFlow === "sign-up" ? (
              <div className="px-row" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
                <div style={{ flex: "1 1 140px" }}>
                  <Field label="First name">{(f) => (
                    <Input id={f.id} describedBy={f.describedBy} autoComplete="given-name" maxLength={60}
                      autoFocus value={firstName} onChange={(e) => { setFirstName(e.target.value); setError(null); }} />
                  )}</Field>
                </div>
                <div style={{ flex: "1 1 140px" }}>
                  <Field label="Last name">{(f) => (
                    <Input id={f.id} describedBy={f.describedBy} autoComplete="family-name" maxLength={60}
                      value={lastName} onChange={(e) => { setLastName(e.target.value); setError(null); }} />
                  )}</Field>
                </div>
              </div>
            ) : null}
            <Field label="Your email" error={error}>{(f) => (
              <Input id={f.id} describedBy={f.describedBy} invalid={f.invalid} type="email" autoComplete="email" inputMode="email"
                autoFocus={mode !== "open"} value={email} onChange={(e) => { setEmail(e.target.value); setError(null); }} />
            )}</Field>
            <Button type="submit" variant="primary" loading={sending} disabled={mode === null}>
              {mode === "open" ? (openFlow === "sign-up" ? "Create workspace" : "Continue") : "Email me a code"}
            </Button>
          </form>}
    </AuthCard>
  );
}
