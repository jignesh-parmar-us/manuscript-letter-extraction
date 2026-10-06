// A link to a help page (docs/help/, served at /help/...). In the browser it opens in a new tab; in
// the app window, which has no tabs, the backend opens it in the web browser.
import { MouseEvent, ReactNode } from "react";
import { api, AppInfo } from "../api";

export default function HelpLink(props: { page: string; info: AppInfo | null; children: ReactNode }) {
  const href = `/help/${props.page}`;
  function open(e: MouseEvent) {
    if (props.info?.mode === "window") {
      e.preventDefault();
      api.openHelp(props.page).catch(() => window.open(href, "_blank"));
    }
  }
  return (
    <a className="help-link small" href={href} target="_blank" rel="noreferrer" onClick={open}>
      {props.children}
    </a>
  );
}
