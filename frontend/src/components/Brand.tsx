import { BrandDecoration } from "./BrandDecoration";

// Issue #25: Dashboard上部ではキャラクターアイコンを非表示にする(showIcon=false)。
// Brandは他画面(Monitor Detail/Create等)でも共有しているため、アセット自体は
// 削除せず、このpropで表示だけを画面ごとに切り替える(既定はtrue=従来どおり表示)。
export function Brand({ showIcon = true }: { showIcon?: boolean }) {
  return (
    <>
      <BrandDecoration />
      <div className="brand-lockup">
        {showIcon && <img className="brand-logo" src="/assets/argus-icon-trimmed.png" alt="" />}
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
