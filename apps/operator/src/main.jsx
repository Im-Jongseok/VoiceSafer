import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import OperatorPage from "./OperatorPage";
import "./index.css";

createRoot(document.getElementById("root")).render(
  <StrictMode><OperatorPage /></StrictMode>,
);
