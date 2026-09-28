"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, listProducts, currentAccount, serverUnavailable, storedSession, type ApiAccount, type ApiActionShape,
  type ApiProduct, type ApiProductShape } from "@pixel-console/lib/pixel-api";

/**
 * The signed-in context of the console: which organization, which product is open, and whether
 * unsaved or in-progress work would be lost by switching. The server derives every one of these
 * again from the session; the browser's copy is only for display.
 */
interface ConsoleState {
  organizationId: string;
  productId: string | null;
  activeWork: string | null; // e.g. "an onboarding draft" or "a playground conversation"
  // Increases each time unsaved work is discarded; the page that owns the work resets on it.
  discardEpoch: number;
  theme: "system" | "light" | "dark";
}

export interface ProductSurface {
  productId: string;
  shape: ApiProductShape;
  currentPage: string | null;
  selectedRecordId: string | null;
  reloadRecords: () => Promise<void>;
  showAction: (action: ApiActionShape, payload: Record<string, unknown>) => void;
}

/** One product of the signed-in organization, as the console lists it. */
export interface ConsoleProduct {
  id: string;
  organizationId: string;
  teamId: string;
  name: string;
  slug: string;
  /** What it is for, in one line: the sentence somebody wrote, or its shape when nobody did. */
  description: string;
  state: "active" | "archived";
  revision: number;
}

interface ConsoleApi extends ConsoleState {
  visibleProducts: ConsoleProduct[];
  liveError: string | null;
  /** Set when the last attempt failed because Pixel's server did not answer, not because of who asked. */
  liveUnavailable: boolean;
  /**
   * Set only when the server said it does not know this caller.
   *
   * Everything else - a proxy hiccup, a cold container, a refused request on the way back from
   * another page - is a failure to ask, not an answer about who is asking. Those used to land in
   * the same branch, so one bad response while returning from the demo put a Sign in button in
   * front of somebody whose session was alive the whole time.
   */
  signedOut: boolean;
  account: ApiAccount | null;
  loading: boolean;
  reloadProducts: () => void;
  /**
   * What the open product screen wants the assistant to be able to do: reload its records and act
   * on its screens. Absent when nobody is inside a product, and replaced whole when another is
   * opened, so one product's callbacks can never run against another's.
   */
  productSurface: ProductSurface | null;
  setProductSurface: (surface: ProductSurface | null) => void;
  selectProduct: (id: string | null) => void;
  setActiveWork: (what: string | null) => void;
  setTheme: (theme: ConsoleState["theme"]) => void;
}

/**
 * How long to wait before asking the server a second time.
 *
 * Long enough that a container which was asleep has started answering, short enough that
 * nobody reads it as the page being stuck.
 */
const RETRY_PAUSE_MS = 600;

const Context = createContext<ConsoleApi | null>(null);

export function ConsoleProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<ApiAccount | null>(null);
  const [state, setState] = useState<ConsoleState>({
    organizationId: "", productId: null, activeWork: null, discardEpoch: 0, theme: "system",
  });

  // The organization's products, from the server. Until the first answer arrives nothing is
  // listed, so the console never shows a product that is not there.
  const [live, setLive] = useState<ApiProduct[] | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [liveUnavailable, setLiveUnavailable] = useState(false);
  const [signedOut, setSignedOut] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reloads, setReloads] = useState(0);
  useEffect(() => {
    let cancelled = false;
    // A retry after an outage shows that it is trying again rather than the old failure.
    if (reloads > 0) setLoading(true);
    (async () => {
      // Two attempts, because one failed request is not an answer about who is asking. Coming
      // back from the demo can land on a cold container or a proxy that is still warming up, and
      // a single unlucky response used to end with a Sign in button in front of somebody whose
      // session had not gone anywhere. Only the server saying it does not know this caller ends
      // the question, and it ends it on the first attempt without waiting for the second.
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          // Ask the server, rather than looking for something this tab happens to remember. A new
          // tab, a refresh and a reopened browser all still carry the session cookie, and each of
          // them used to look signed out because this tab's own memory was empty.
          const identity = await currentAccount();
          const products = await listProducts({ csrfToken: "", userId: identity.user_id, tenantId: identity.tenant_id });
          if (cancelled) return;
          setAccount(identity);
          setState((current) => ({ ...current, organizationId: identity.tenant_id,
            productId: products.some((p) => p.product_id === current.productId) ? current.productId : null }));
          setLive(products);
          setLiveError(null);
          setLiveUnavailable(false);
          setSignedOut(false);
          break;
        } catch (error) {
          if (cancelled) return;
          // Being signed out is not an error, and the server's words for it ("Authorization header
          // is required") are not for the person reading the page.
          const refused = error instanceof ApiError && (error.status === 401 || error.status === 403);
          if (refused) {
            setSignedOut(true);
            setLiveError(null);
            setLiveUnavailable(false);
            break;
          }
          if (attempt === 0) {
            await new Promise((settle) => setTimeout(settle, RETRY_PAUSE_MS));
            if (cancelled) return;
            continue;
          }
          setSignedOut(false);
          setLiveError(error instanceof Error ? error.message : "Products could not be loaded.");
          setLiveUnavailable(serverUnavailable(error));
        }
      }
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [reloads]);

  const visibleProducts = useMemo<ConsoleProduct[]>(() => (live ?? []).map((product) => ({
    id: product.product_id,
    organizationId: state.organizationId,
    teamId: product.team_id ?? "",
    name: product.name,
    slug: product.product_id,
    // What somebody wrote about it beats what Pixel can count about it. A product added
        // before anybody was asked still says something true rather than nothing.
        description: product.purpose?.trim()
          || `${product.entities.length} kinds of record, ${product.views.length} screens.`,
    state: product.state === "active" ? "active" : "archived",
    revision: product.definition_version,
  })), [live, state.organizationId]);

  const reloadProducts = useCallback(() => setReloads((count) => count + 1), []);
  const [productSurface, setProductSurface] = useState<ProductSurface | null>(null);

  // Actions are stable across renders, and a setter that changes nothing keeps the same state
  // object, so effects that depend on them can never loop.
  const selectProduct = useCallback((id: string | null) => setState((s) => {
    if (s.productId === id && s.activeWork === null) return s;
    // Switching away from unsaved work discards it, so the owning page must reset, not keep it.
    return { ...s, productId: id, activeWork: null, discardEpoch: s.activeWork ? s.discardEpoch + 1 : s.discardEpoch };
  }), []);
  const setActiveWork = useCallback((activeWork: string | null) => setState((s) => (
    s.activeWork === activeWork ? s : { ...s, activeWork })), []);
  const setTheme = useCallback((theme: ConsoleState["theme"]) => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    setState((s) => (s.theme === theme ? s : { ...s, theme }));
  }, []);

  const api = useMemo<ConsoleApi>(() => ({
    ...state, visibleProducts, liveError, liveUnavailable, signedOut, account, loading, reloadProducts,
    productSurface, setProductSurface, selectProduct, setActiveWork, setTheme,
  }), [state, visibleProducts, liveError, liveUnavailable, signedOut, account, loading, reloadProducts,
       productSurface, selectProduct, setActiveWork, setTheme]);
  return <Context.Provider value={api}>{children}</Context.Provider>;
}

export function useConsole(): ConsoleApi {
  const value = useContext(Context);
  if (!value) throw new Error("useConsole outside ConsoleProvider");
  return value;
}
