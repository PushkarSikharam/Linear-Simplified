"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Boxes, Network, PlayCircle, Plus, UserCircle, Users } from "lucide-react";
import { useConsole } from "@pixel-console/components/console-context";
import { Alert, EmptyState, PageHead, Panel, StatusBadge } from "@pixel-console/components/ui";
import { listMembers, listTeams, storedSession } from "@pixel-console/lib/pixel-api";

/**
 * How much there is of everything, at a glance.
 *
 * A workspace with things in it should look like one. The numbers are the same ones the
 * assistant answers with, read from the same endpoints, so the screen and Edith cannot disagree
 * about how many people are here.
 */
function Counts({ products }: { products: number }) {
  const [people, setPeople] = useState<number | null>(null);
  const [teams, setTeams] = useState<number | null>(null);
  useEffect(() => {
    let current = true;
    (async () => {
      const session = storedSession();
      if (!session) return;
      try {
        const [found, foundTeams] = await Promise.all([listMembers(session), listTeams(session)]);
        if (current) { setPeople(found.length); setTeams(foundTeams.length); }
      } catch {
        // A count that cannot be fetched is left out rather than shown as zero, which would be
        // a number somebody could act on and a lie.
      }
    })();
    return () => { current = false; };
  }, []);
  // One of something is not "1 Teams". A count beside the wrong word is the kind of small
  // wrongness that makes everything around it look unfinished.
  const tiles: Array<[typeof Boxes, string, string, number | null, string]> = [
    [Boxes, "Product", "Products", products, "/console/products"],
    [UserCircle, "Person", "People", people, "/console/organization"],
    [Users, "Team", "Teams", teams, "/console/organization"],
  ];
  return (
    <ul className="px-counts" aria-label="What is in this workspace">
      {tiles.map(([Icon, one, many, value, href]) => (
        <li key={many}>
          <Link href={href}>
            <Icon aria-hidden />
            <strong>{value === null ? "-" : value}</strong>
            <span>{value === 1 ? one : many}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/**
 * What somebody sees when they arrive.
 *
 * A first screen that says only "no products yet" leaves a person with nothing to act on. This
 * one says what Pixel is for, what to do first, and what the assistant beside it can be asked,
 * and it changes once there is something to come back to.
 */
function LiveOverview() {
  const c = useConsole();
  const products = c.visibleProducts;
  const first = products.length === 0;
  const mayAdd = c.account === null || c.account.role === "org_admin" || c.account.role === "team_admin";

  return <>
    <PageHead
      title={first ? "Welcome to Pixel" : (c.account?.organization_name ?? "Your workspace")}
      description={first
        ? "Pixel runs your products. Describe one, and Edith can answer about it, open its screens, and create and assign its records."
        : "Your products, and where to go next."}
      actions={mayAdd ? <Link className="px-button" data-variant="primary" href="/console/products/new">
        <Plus aria-hidden />Add a product</Link> : undefined} />

    {c.account?.role === "org_admin" && c.account.organization_name === "My organization" ? (
      <Alert title="Give your organization a name">
        It is called &quot;My organization&quot; for now. <Link href="/console/settings">Name it in Settings</Link>,
        and everyone you add will see it at the top of every page.
      </Alert>
    ) : null}

    {first ? (
      <Panel title="Start here">
        <ol className="px-stack" style={{ margin: 0, paddingLeft: 20, gap: 10 }}>
          <li>
            <strong>Describe your product.</strong> Tell Pixel what it keeps - deals, tickets,
            customers - and Pixel writes its definition for you to read before anything runs on it.
            {mayAdd ? (
              <div className="px-row" style={{ marginTop: 6 }}>
                <Link className="px-button" data-variant="primary" href="/console/products/new">
                  <Plus aria-hidden />Add your first product</Link>
              </div>
            ) : (
              <div className="px-small px-muted" style={{ marginTop: 6 }}>
                An organization admin adds products. You will be able to use them as soon as they exist.
              </div>
            )}
          </li>
          <li>
            <strong>See one that already works.</strong> The guided demo is a finished product
            running on the same Pixel you are using.
            <div className="px-row" style={{ marginTop: 6 }}>
              <Link className="px-button" data-variant="primary" href="/demo"><PlayCircle aria-hidden />Visit demo</Link>
              <Link className="px-button" href="/architecture"><Network aria-hidden />How Pixel works</Link>
            </div>
          </li>
          <li>
            <strong>Ask Edith.</strong> She is beside every screen. Try "add a product",
            "show me the demo", or "how many products do I have".
          </li>
        </ol>
      </Panel>
    ) : null}

    {first ? null : <Counts products={products.length} />}

    <Panel title="Your products" actions={products.length
      ? <Link href="/console/products">All products</Link> : undefined}>
      {first ? (
        <EmptyState title="No products yet"
          action={mayAdd ? <Link className="px-button" data-variant="primary" href="/console/products/new">
            <Plus aria-hidden />Add a product</Link> : undefined}>
          {mayAdd
            ? "Once you add one, it appears here and Edith can answer about it."
            : "Once an admin adds one, it appears here and Edith can answer about it."}
        </EmptyState>
      ) : <div className="px-table-wrap"><table className="px-table">
        <thead><tr><th>Product</th><th>What it is for</th><th>Version</th><th>Status</th></tr></thead>
        <tbody>{products.map((product) => (
          <tr key={product.id}>
            <td><Link href={`/console/products/${encodeURIComponent(product.id)}`}>{product.name}</Link></td>
            <td className="px-muted">{product.description}</td>
            <td>{product.revision}</td>
            <td><StatusBadge status={product.state} /></td>
          </tr>
        ))}</tbody>
      </table></div>}
    </Panel>

    {first ? null : (
      <Panel title="Elsewhere in Pixel">
        <div className="px-row" style={{ flexWrap: "wrap" }}>
          {mayAdd ? <Link className="px-button" data-px-control="add_product_button" href="/console/products/new"><Plus aria-hidden />Add a product</Link> : null}
          <Link className="px-button" href="/console/organization"><Users aria-hidden />People and teams</Link>
          <Link className="px-button" data-variant="primary" href="/demo"><PlayCircle aria-hidden />Visit demo</Link>
          <Link className="px-button" href="/architecture"><Network aria-hidden />How Pixel works</Link>
        </div>
      </Panel>
    )}
  </>;
}

export default function Overview() {
  return <LiveOverview />;
}
