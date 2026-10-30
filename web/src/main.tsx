import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./theme.css";
import Home from "./pages/Home";
import Run from "./pages/Run";
import Infra from "./pages/Infra";
import Dev from "./pages/Dev";
import Evidence from "./pages/Evidence";
import { useHashRoute } from "./ui";

function Theme() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    try { const s = localStorage.getItem("ls-theme"); if (s === "light" || s === "dark") return s; } catch { /* ignore */ }
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  const flip = () => {
    const t = theme === "dark" ? "light" : "dark";
    setTheme(t);
    try { localStorage.setItem("ls-theme", t); } catch { /* ignore */ }
  };
  return (
    <button className="link small nav-hit" onClick={flip} title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}

function App() {
  const route = useHashRoute();
  const parts = route.split("/").filter(Boolean);
  let page;
  if (parts[0] === "run" && parts[1]) page = <Run key={route} kind="run" id={decodeURIComponent(parts[1])} />;
  else if (parts[0] === "replay" && parts[1]) page = <Run key={route} kind="replay" id={decodeURIComponent(parts[1])} />;
  else if (parts[0] === "infra") page = <Infra />;
  else if (parts[0] === "evidence") page = <Evidence />;
  else if (parts[0] === "dev") page = <Dev />;
  else page = <Home />;
  const title = parts[0] === "run" ? "Live run" : parts[0] === "replay" ? "Recording" : parts[0] === "infra" ? "Under the hood" : "";
  useEffect(() => { document.title = title ? `${title} · LogicScout` : "LogicScout"; }, [title]);
  return (
    <>
      <nav className="nav" aria-label="Main">
        <a href="#/" className="brand">LogicScout</a>
        <span className="spacer" />
        <a href="#/infra" className="small nav-hit">Under the hood</a>
        <Theme />
      </nav>
      {page}
    </>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
