import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import LandingPage from "./LandingPage";
import ApplicationPage from "./ApplicationPage";
import LookupPage from "./LookupPage";
import "./index.css";

function App() {
  const [path, setPath] = useState(window.location.pathname);
  const [application, setApplication] = useState(null);
  function navigate(url) {
    window.history.pushState(null, "", url);
    setPath(window.location.pathname);
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
        !["/", "/lookup", "/apply", "/apply/scenario", "/apply/voice"].includes(
          url.pathname,
        )
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
      ? "신청 체험 | VoiceVaccine"
      : path === "/lookup"
        ? "체험 신청 조회 | VoiceVaccine"
        : "VoiceVaccine | 보이스피싱 예방 모의훈련";
  }, [path]);
  if (path.startsWith("/apply"))
    return <ApplicationPage onComplete={setApplication} />;
  if (path === "/lookup") return <LookupPage application={application} />;
  return <LandingPage navigate={navigate} />;
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
