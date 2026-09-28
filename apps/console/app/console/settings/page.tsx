"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { useConsole } from "@pixel-console/components/console-context";
import { useToast } from "@pixel-console/components/toast";
import { Button, Field, Input, PageHead, Panel } from "@pixel-console/components/ui";
import { changeOwnName, endSession, renameOrganization, signInMode, storedSession, type SignInMode }
  from "@pixel-console/lib/pixel-api";

/**
 * What signing in to this Pixel actually takes.
 *
 * This panel used to state flatly that a one-time code is emailed, which stops being true
 * the moment a deployment is set to take an address on its own. Somebody reading their own
 * account should not be told something about it that is not so, least of all about how it is
 * protected, so the wording follows the deployment rather than being written into the page.
 */
const SIGN_IN_WORDS: Record<SignInMode, string> = {
  code: "A one-time code sent to your email. There is no password to manage.",
  open: "Your email address on its own. This Pixel is open for demonstration, so anyone who knows your address can open this workspace.",
  disabled: "Sign-in is not switched on for this Pixel.",
};

const ROLE_WORDS: Record<string, string> = {
  org_admin: "Organization admin", team_admin: "Team admin", team_member: "Team member",
};

/** What a signed-in organization can really set today: its name, and who you are signed in as. */
function LiveSettings() {
  const c = useConsole();
  const toast = useToast();
  const router = useRouter();
  const current = c.account?.organization_name ?? "";
  const [name, setName] = useState(current);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = c.account?.role === "org_admin";
  const [howSignInWorks, setHowSignInWorks] = useState<SignInMode | null>(null);
  // Your own name, which everybody here sees and which the assistant answers with. It was
  // asked for once, at sign-in, and then there was nowhere to correct a typo in it.
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  useEffect(() => {
    setFirstName(c.account?.first_name ?? "");
    setLastName(c.account?.last_name ?? "");
  }, [c.account?.first_name, c.account?.last_name]);

  async function saveName(event: React.FormEvent) {
    event.preventDefault();
    const first = firstName.trim();
    const last = lastName.trim();
    if (!first || !last) { setNameError("Enter your first and last name."); return; }
    setSavingName(true); setNameError(null);
    try {
      const saved = await changeOwnName(first, last);
      toast("ok", `You are now shown as ${saved.name}.`);
      c.reloadProducts();
    } catch (caught) {
      setNameError(caught instanceof Error ? caught.message : "Your name could not be saved.");
    } finally {
      setSavingName(false);
    }
  }

  useEffect(() => {
    let current = true;
    signInMode().then((found) => { if (current) setHowSignInWorks(found); }, () => {});
    return () => { current = false; };
  }, []);

  useEffect(() => { setName(current); }, [current]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const session = storedSession();
    const wanted = name.trim();
    if (!wanted) { setError("Give your organization a name."); return; }
    if (!session) return;
    setSaving(true); setError(null);
    try {
      const saved = await renameOrganization(session, wanted);
      toast("ok", `Your organization is now called ${saved.name}.`);
      c.reloadProducts();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The name could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHead title="Settings" description="Your organization's name and the account you are signed in with." />
      <Panel title="Organization">
        <form className="px-stack" onSubmit={save} noValidate>
          <Field label="Organization name" error={error}
            hint={isAdmin ? "Shown to everyone in your organization and at the top of every page." : "Only an organization admin can change this."}>{(f) => (
            <Input id={f.id} describedBy={f.describedBy} invalid={f.invalid} value={name} maxLength={80}
              data-px-control="organization_name_field"
              disabled={!isAdmin} onChange={(e) => { setName(e.target.value); setError(null); }} />
          )}</Field>
          {isAdmin ? (
            <div className="px-row">
              <Button type="submit" variant="primary" loading={saving}
                disabled={!name.trim() || name.trim() === current}>Save name</Button>
            </div>
          ) : null}
        </form>
      </Panel>
      <Panel title="Your account">
        <dl className="px-record-fields">
          <div><dt>Name</dt><dd>{c.account?.name ?? "Not set"}</dd></div>
          <div><dt>Email</dt><dd>{c.account?.email ?? "Not set"}</dd></div>
          <div><dt>Role</dt><dd>{ROLE_WORDS[c.account?.role ?? ""] ?? c.account?.role}</dd></div>
          <div><dt>Sign-in</dt><dd>{howSignInWorks ? SIGN_IN_WORDS[howSignInWorks] : "There is no password to manage."}</dd></div>
        </dl>
        <form className="px-row" style={{ alignItems: "flex-end", flexWrap: "wrap", marginTop: "var(--px-space-4)" }}
          onSubmit={saveName} noValidate>
          <div style={{ flex: "0 1 160px" }}>
            <Field label="First name" error={nameError}>{(f) => (
              <Input id={f.id} describedBy={f.describedBy} invalid={f.invalid} value={firstName} maxLength={60}
                onChange={(e) => { setFirstName(e.target.value); setNameError(null); }} />
            )}</Field>
          </div>
          <div style={{ flex: "0 1 160px" }}>
            <Field label="Last name">{(f) => (
              <Input id={f.id} describedBy={f.describedBy} value={lastName} maxLength={60}
                onChange={(e) => { setLastName(e.target.value); setNameError(null); }} />
            )}</Field>
          </div>
          <Button type="submit" loading={savingName}
            disabled={!firstName.trim() || !lastName.trim()
              || (firstName.trim() === (c.account?.first_name ?? "") && lastName.trim() === (c.account?.last_name ?? ""))}>
            Save your name</Button>
        </form>
        <div className="px-row" style={{ marginTop: "var(--px-space-4)" }}>
          <Button onClick={() => { void endSession().then(() => router.push("/signed-out")); }}>
            <LogOut aria-hidden />Sign out</Button>
        </div>
      </Panel>
    </>
  );
}

export default function Page() {
  return <LiveSettings />;
}
