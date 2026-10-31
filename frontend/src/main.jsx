import { StrictMode, Suspense, lazy, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import LandingPage from "./LandingPage";
const ApplicationPage = lazy(() => import("./ApplicationPage"));
const LookupPage = lazy(() => import("./LookupPage"));
const OperatorPage = lazy(() => import("./OperatorPage"));
import "./index.css";

function App() {
  const [path, setPath] = useState(window.location.pathname);
  function navigate(url) {
    window.history.pushState(null, "", url);
    setPath(window.location.pathname);
    window.dispatchEvent(new Event("app:navigate"));
    window.scrollTo({ top: 0 });
  }
  useEffect(() => {
    function pop() {
      setPath(window.location.pathname);
    }
    function click(event) {
      const anchor = event.target.closest?.("a[href]");
      if (
        !anchor ||
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey ||
        anchor.target ||
        anchor.hasAttribute("download")
      )
        return;
      const url = new URL(anchor.href);
      if (
        url.origin !== window.location.origin ||
        anchor.getAttribute("href").startsWith("#")
      )
        return;
      if (
        ![
          "/",
          "/lookup",
          "/apply",
          "/apply/scenario",
          "/apply/voice",
          "/control",
        ].includes(url.pathname)
      )
        return;
      event.preventDefault();
      navigate(url.pathname + url.search + url.hash);
    }
    window.addEventListener("popstate", pop);
    document.addEventListener("click", click);
    return () => {
      window.removeEventListener("popstate", pop);
      document.removeEventListener("click", click);
    };
  }, []);
  useEffect(() => {
    document.title = path.startsWith("/apply")
      ? "훈련 신청 | VoiceVaccine"
      : path === "/lookup"
        ? "신청 조회 | VoiceVaccine"
        : path === "/control"
          ? "관제 | VoiceVaccine"
          : "VoiceVaccine | 보이스피싱 예방 모의훈련";
  }, [path]);
  if (path.startsWith("/apply")) return <ApplicationPage />;
  if (path === "/lookup") return <LookupPage />;
  if (path === "/control") return <OperatorPage />;
  return <LandingPage navigate={navigate} />;
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Suspense
      fallback={
        <p
          role="status"
          className="flex min-h-screen items-center justify-center text-sm text-slate-400"
        >
          화면을 불러오는 중…
        </p>
      }
    >
      <App />
    </Suspense>
  </StrictMode>,
);
