// The frame of Font Maker: one bar at the top and the screen chosen by the address:
//   #/               Fonts     (Fonts.tsx: the font projects and "New font")
//   #/fonts/<id>[/<tab>]   one font  (FontView.tsx; tabs: glyphs, settings)
import { useEffect, useState } from "react";
import { api, AppInfo } from "./api";
import Fonts from "./Fonts";
import FontView from "./FontView";
import { go, useRoute } from "./route";

export default function App() {
  const route = useRoute();
  const [info, setInfo] = useState<AppInfo | null>(null);

  useEffect(() => {
    api.app().then(setInfo, () => setInfo(null));
  }, []);

  const fontId = route[0] === "fonts" ? route[1] : undefined;
  return (
    <div className="app">
      <header className="top">
        <div className="top-left">
          <button className="brand link" onClick={() => go("/")}>
            Font Maker
          </button>
        </div>
        <div className="top-middle muted small">{info && `Library: ${info.library} (read-only)`}</div>
        <nav className="top-right" aria-label="App" />
      </header>
      <main>{fontId ? <FontView fontId={fontId} tab={route[2] ?? "glyphs"} /> : <Fonts />}</main>
    </div>
  );
}
