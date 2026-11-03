import {
  Component,
  StrictMode,
  Suspense,
  lazy,
  useEffect,
  useState,
} from "react";
import { createRoot } from "react-dom/client";
import LandingPage from "./LandingPage";
const ApplicationPage = lazy(() => import("./ApplicationPage"));
const LookupPage = lazy(() => import("./LookupPage"));
const OperatorPage = lazy(() => import("./operator/OperatorPage"));
import "./index.css";

// A tab opened before a deployment may request an old page chunk.
window.addEventListener("vite:preloadError", (event) => {
  try {
    const key = "voice-vaccine-page-reload";
    const last = Number(sessionStorage.getItem(key) || 0);
    if (Date.now() - last < 60000) return;
    sessionStorage.setItem(key, String(Date.now()));
    event.preventDefault();
    window.location.reload();
  } catch {
    // If storage is unavailable, the boundary still provides manual recovery.
  }
});

class PageBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-5 px-6 text-center">
        <h1 className="text-xl font-semibold">화면을 불러오지 못했습니다.</h1>
        <p className="text-sm leading-6 text-slate-500">
          연결 상태를 확인한 뒤 다시 불러와 주세요.
        </p>
        <button
          className="rounded-full bg-primary px-6 py-3 font-semibold text-white"
          onClick={() => window.location.reload()}
        >
          다시 불러오기
        </button>
      </main>
    );
  }
}

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
      ? "훈련 신청 | VoiceSafer"
      : path === "/lookup"
        ? "신청 조회 | VoiceSafer"
        : path === "/control"
          ? "관제 | VoiceSafer"
          : "VoiceSafer | 보이스피싱 예방 모의훈련";
  }, [path]);
  if (path.startsWith("/apply")) return <ApplicationPage />;
  if (path === "/lookup") return <LookupPage />;
  if (path === "/control") return <OperatorPage />;
  return <LandingPage navigate={navigate} />;
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <PageBoundary>
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
    </PageBoundary>
  </StrictMode>,
);
