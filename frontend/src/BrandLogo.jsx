import logo from "./assets/voice-vaccine-logo.svg";

export default function BrandLogo({ compact = false }) {
  return (
    <img
      className={`brand-logo${compact ? " brand-logo-compact" : ""}`}
      src={logo}
      alt="VoiceVaccine"
      width="720"
      height="150"
      decoding="async"
    />
  );
}
