// The one bar at the top of every screen: on the left the app's name (Books screen) or the book's
// section menu (Pages & capture, Review groups, Pages, Export), in the middle what is open (the book's
// name and numbers on one line), on the right the way back to the books and the help.
import { ReactNode } from "react";
import { AppInfo } from "../api";
import { go } from "../route";
import HelpLink from "./HelpLink";

export default function AppBar(props: { info: AppInfo | null; left: ReactNode; middle?: ReactNode; books?: boolean }) {
  return (
    <header className="top">
      <div className="top-left">{props.left}</div>
      <div className="top-middle">{props.middle}</div>
      <nav className="top-right" aria-label="App">
        {props.books !== false && (
          <button className="link" onClick={() => go("/")}>
            Books
          </button>
        )}
        <HelpLink page="new-book.html" info={props.info}>
          Help
        </HelpLink>
      </nav>
    </header>
  );
}
