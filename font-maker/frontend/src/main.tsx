import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "../../../frontend/src/styles.css";
import "./font-maker.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
