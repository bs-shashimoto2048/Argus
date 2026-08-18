export function BrandDecoration() {
  return (
    <div className="brand-background" aria-hidden="true">
      <svg className="brand-background-svg" viewBox="0 0 620 120" focusable="false">
        <defs>
          <radialGradient id="brand-zone-glow" cx="42%" cy="50%" r="62%">
            <stop offset="0" stopColor="#2563eb" stopOpacity=".12" />
            <stop offset=".72" stopColor="#60a5fa" stopOpacity=".045" />
            <stop offset="1" stopColor="#93c5fd" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="brand-zone-ink" x1="0" y1=".2" x2="1" y2=".8">
            <stop offset="0" stopColor="#1d4ed8" stopOpacity=".17" />
            <stop offset=".52" stopColor="#2563eb" stopOpacity=".15" />
            <stop offset="1" stopColor="#60a5fa" stopOpacity=".035" />
          </linearGradient>
          <linearGradient id="brand-zone-streak" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#2563eb" stopOpacity=".14" />
            <stop offset=".7" stopColor="#60a5fa" stopOpacity=".09" />
            <stop offset="1" stopColor="#93c5fd" stopOpacity="0" />
          </linearGradient>
          <radialGradient id="brand-icon-halo" cx="50%" cy="50%" r="50%">
            <stop offset="0" stopColor="#ffffff" stopOpacity=".76" />
            <stop offset=".38" stopColor="#ffffff" stopOpacity=".3" />
            <stop offset=".7" stopColor="#ffffff" stopOpacity=".08" />
            <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
          </radialGradient>
        </defs>

        <ellipse cx="245" cy="61" rx="250" ry="67" fill="url(#brand-zone-glow)" />

        <path
          d="M-72 53c27-30 70-22 101-41 37-23 80-17 101 10 18 23 38 16 65 20 38 5 63 29 52 52-11 23-55 22-83 28-39 9-59 31-100 23-31-6-46-28-75-31-35-4-88-30-61-61Z"
          fill="url(#brand-zone-ink)"
        />
        <path d="M18 99c50-13 89-29 140-47 38-13 74-19 112-17" fill="none" stroke="#3b82f6" strokeWidth="13" strokeLinecap="round" opacity=".11" />
        <path d="M-10 111c69-14 114-39 176-67 36-16 73-24 116-24" fill="none" stroke="url(#brand-zone-streak)" strokeWidth="5" strokeLinecap="round" />
        <path d="M115 16c62 1 99 12 142 30 30 13 60 17 105 12" fill="none" stroke="#60a5fa" strokeWidth="7" strokeLinecap="round" opacity=".075" />

        <ellipse cx="104" cy="58" rx="76" ry="57" fill="url(#brand-icon-halo)" />

        <path d="M72 25c7-15 23-16 29-4 6 12-7 24-18 20-9-3-14-9-11-16Z" fill="#2563eb" opacity=".17" />
        <path d="M286 17c5-10 16-10 20-2 4 9-4 17-12 15-7-2-10-7-8-13Z" fill="#3b82f6" opacity=".16" />
        <ellipse cx="350" cy="96" rx="13" ry="6" fill="#60a5fa" opacity=".16" transform="rotate(-26 350 96)" />
        <circle cx="402" cy="29" r="6" fill="#1d4ed8" opacity=".18" />
        <circle cx="440" cy="89" r="4" fill="#2563eb" opacity=".2" />
        <circle cx="468" cy="45" r="3" fill="#60a5fa" opacity=".19" />

        <g className="brand-target" fill="none" stroke="#3b82f6" strokeWidth="1.5" opacity=".09">
          <circle cx="126" cy="38" r="31" />
          <circle cx="126" cy="38" r="17" />
          <path d="M126 0v76M88 38h76" />
          <circle cx="126" cy="38" r="3" fill="#2563eb" stroke="none" />
        </g>

        <g fill="#93c5fd" opacity=".15">
          <circle cx="30" cy="13" r="3" /><circle cx="46" cy="8" r="5" /><circle cx="318" cy="108" r="3" />
          <circle cx="378" cy="14" r="3" /><circle cx="496" cy="74" r="4" /><circle cx="526" cy="34" r="2.5" />
        </g>
      </svg>
    </div>
  );
}
