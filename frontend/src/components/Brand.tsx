import { BrandDecoration } from "./BrandDecoration";

export function Brand() {
  return (
    <>
      <BrandDecoration />
      <div className="brand-lockup">
        <img className="brand-logo" src="/assets/argus-icon-trimmed.png" alt="" />
        <span className="brand-copy">
          <span className="brand-title"><span className="brand-title-accent">A</span>RGUS</span>
          <span className="brand-accent-line" aria-hidden="true"><span className="brand-accent-dot" /></span>
          <span className="brand-tagline">
            <span className="brand-tagline-marker" aria-hidden="true" />
            <span className="brand-tagline-intelligent">INTELLIGENT</span>
            <span>&nbsp;REMOTE METER MONITORING SYSTEM</span>
          </span>
        </span>
      </div>
    </>
  );
}
