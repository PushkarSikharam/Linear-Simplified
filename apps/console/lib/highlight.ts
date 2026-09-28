/**
 * Showing somebody the control that does the thing they asked about.
 *
 * "Where do I add a person?" is answered by taking them to the screen and marking the button,
 * not by describing where the button is. The definition names the control; a screen claims that
 * name with `data-px-control`, and this finds it and makes it obvious for a few seconds.
 *
 * The wait exists because the screen is usually still arriving: the assistant navigates and
 * highlights in the same breath, and the control does not exist until the new page has rendered.
 * When it never appears, nothing happens - a missed highlight is a small disappointment, and a
 * thrown error in the middle of a conversation is not.
 */
const HIGHLIGHT_CLASS = "px-highlight";
const ATTEMPT_PAUSE_MS = 100;
const ATTEMPTS = 25;
const HELD_MS = 4000;

export function controlSelector(control: string): string {
  const escape = typeof CSS !== "undefined" && CSS.escape ? CSS.escape : (value: string) => value.replace(/"/g, '\\"');
  return `[data-px-control="${escape(control)}"]`;
}

/**
 * Resolves true when the control was found and marked, false when it never appeared.
 *
 * Whether it appeared matters to the caller. A screen shows the controls the person may use, so
 * a control that is not there is usually one their role does not have - and having been told
 * "I'll open People and teams and highlight Add a person", they should not then be left looking
 * for a button that was never going to be on the page.
 */
export function highlightControl(control: string): Promise<boolean> {
  if (typeof document === "undefined" || !control) return Promise.resolve(false);
  return new Promise((settle) => {
    let tries = 0;
    const look = () => {
      const found = document.querySelector<HTMLElement>(controlSelector(control));
      if (!found) {
        tries += 1;
        if (tries < ATTEMPTS) window.setTimeout(look, ATTEMPT_PAUSE_MS);
        else settle(false);
        return;
      }
      found.scrollIntoView({ block: "center", behavior: "smooth" });
      found.classList.add(HIGHLIGHT_CLASS);
      window.setTimeout(() => found.classList.remove(HIGHLIGHT_CLASS), HELD_MS);
      // Focus as well as mark it: somebody who asked where a control is can then use it without
      // reaching for the mouse, and a screen reader says what was found instead of nothing.
      if (typeof found.focus === "function") found.focus({ preventScroll: true });
      settle(true);
    };
    look();
  });
}
