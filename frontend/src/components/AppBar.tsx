// The one bar at the top of every screen: on the left the app's name (Books screen) or the book's
// section menu (Pages & capture, Review groups, Pages, Export), in the middle what is open (the book's
// name and numbers on one line), on the right the Books and Datasets screens and the help.
import { ReactNode } from "react";
import { AppInfo } from "../api";
import { go } from "../route";
import HelpLink from "./HelpLink";

/** `current`: the list screen that is open (C21: Books and Datasets are two screens), shown as such. */
export default function AppBar(props: { info: AppInfo | null; left: ReactNode; middle?: ReactNode; current?: "books" | "datasets" }) {
  const link = (to: "books" | "datasets", path: string, text: string) => (
    <button className={props.current === to ? "link current" : "link"} aria-current={props.current === to ? "page" : undefined}
      onClick={() => go(path)}>
      {text}
    </button>
  );
  return (
    <header className="top">
      <div className="top-left">{props.left}</div>
      <div className="top-middle">{props.middle}</div>
      <nav className="top-right" aria-label="App">
        {link("books", "/", "Books")}
        {link("datasets", "/datasets", "Datasets")}
        <HelpLink page="new-book.html" info={props.info}>
          Help
        </HelpLink>
      </nav>
    </header>
  );
}
