export function AppBackground() {
  return (
    <div className="app-background" aria-hidden="true">
      <svg className="app-background-svg" viewBox="0 0 1600 1000" preserveAspectRatio="none" focusable="false">
        <defs>
          <linearGradient id="splash-deep" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#2563eb" stopOpacity=".18" />
            <stop offset=".65" stopColor="#3b82f6" stopOpacity=".12" />
            <stop offset="1" stopColor="#60a5fa" stopOpacity=".03" />
          </linearGradient>
          <linearGradient id="splash-mid" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" stopColor="#3b82f6" stopOpacity=".15" />
            <stop offset="1" stopColor="#93c5fd" stopOpacity=".04" />
          </linearGradient>
          <radialGradient id="splash-soft">
            <stop offset="0" stopColor="#60a5fa" stopOpacity=".16" />
            <stop offset="1" stopColor="#bfdbfe" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Lower-left paint pool */}
        <g className="splash-medium">
          <path d="M-80 770c45-69 125-79 190-42 46 26 71 12 113 42 56 39 47 116-13 142-62 28-122-6-179 18-61 25-131-1-143-59-7-32 9-69 32-101Z" fill="url(#splash-mid)" />
          <path d="M70 866c54-19 104-4 124 28 17 27-14 57-56 54-46-3-96-21-104-48-5-15 10-28 36-34Z" fill="url(#splash-soft)" />
        </g>
        <g className="lower-spray" fill="#60a5fa">
          <circle cx="230" cy="780" r="12" opacity=".16" /><circle cx="285" cy="816" r="6" opacity=".19" /><circle cx="342" cy="758" r="8" opacity=".13" />
          <ellipse cx="388" cy="845" rx="15" ry="6" opacity=".15" transform="rotate(20 388 845)" /><circle cx="438" cy="900" r="5" opacity=".18" />
        </g>

        {/* Lower-right splash layered with supporting radar */}
        <g className="splash-large-right">
          <path d="M1130 850c28-61 89-75 119-127 35-60 114-75 166-34 42 33 35 88 86 113 67 33 99 113 43 167-51 48-121 13-180 35-65 24-129 10-156-38-19-34-101-46-78-116Z" fill="url(#splash-deep)" />
          <path d="M1304 751c39-42 101-47 139-14 33 29 22 76-20 98-50 26-119 11-139-27-9-18-1-38 20-57Z" fill="url(#splash-soft)" />
        </g>
        <g className="right-spray" fill="#3b82f6">
          <circle cx="1192" cy="680" r="10" opacity=".17" /><circle cx="1255" cy="633" r="5" opacity=".2" /><ellipse cx="1324" cy="612" rx="16" ry="7" opacity=".14" transform="rotate(-30 1324 612)" />
          <circle cx="1484" cy="704" r="9" opacity=".17" /><circle cx="1545" cy="748" r="4" opacity=".2" /><circle cx="1122" cy="760" r="6" opacity=".15" />
        </g>

        <g className="background-dots" fill="#60a5fa" opacity=".09">
          <circle cx="500" cy="630" r="4" /><circle cx="530" cy="630" r="4" /><circle cx="560" cy="630" r="4" /><circle cx="590" cy="630" r="4" /><circle cx="620" cy="630" r="4" />
          <circle cx="515" cy="660" r="4" /><circle cx="545" cy="660" r="4" /><circle cx="575" cy="660" r="4" /><circle cx="605" cy="660" r="4" />
          <circle cx="530" cy="690" r="4" /><circle cx="560" cy="690" r="4" /><circle cx="590" cy="690" r="4" />
        </g>
      </svg>
    </div>
  );
}
