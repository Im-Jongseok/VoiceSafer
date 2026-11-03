import logo from "../../../assets/voicesafer-logo.svg";

export default function BrandLogo({ compact = false }) {
  return (
    <img
      className={`brand-logo${compact ? " brand-logo-compact" : ""}`}
      src={logo}
      alt="VoiceSafer"
      width="600"
      height="150"
      decoding="async"
    />
  );
}
