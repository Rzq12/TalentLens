/**
 * Authored icon set. One stroke weight (1.5), one cap style, 20px grid.
 * Geometry only — no pictorial illustration, no unicode stand-ins.
 */

export type IconName =
  | "register"
  | "sheet"
  | "run"
  | "person"
  | "seal"
  | "gear"
  | "search"
  | "chevron-down"
  | "chevron-right"
  | "chevron-left"
  | "plus"
  | "trash"
  | "grip"
  | "pause"
  | "stop"
  | "download"
  | "upload"
  | "check"
  | "cross"
  | "dash"
  | "alert"
  | "thread"
  | "zoom-in"
  | "zoom-out"
  | "flag"
  | "clock";

const PATHS: Record<IconName, React.ReactNode> = {
  register: (
    <>
      <path d="M4 3h9l3 3v11H4z" />
      <path d="M13 3v3h3" />
      <path d="M7 9h6M7 12h6" />
    </>
  ),
  sheet: (
    <>
      <path d="M4.5 3h11v14h-11z" />
      <path d="M7.5 3v14" />
      <path d="M10 7h3M10 10h3" />
    </>
  ),
  run: (
    <>
      <path d="M3 10h3l2-5 3 10 2-5h4" />
    </>
  ),
  person: (
    <>
      <circle cx="10" cy="7" r="3" />
      <path d="M4.5 17c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
    </>
  ),
  seal: (
    <>
      <path d="M10 2.5 12 5l3-.5.5 3 2.2 2-2.2 2 .5 3-3-.5-2 2.5-2-2.5-3 .5.5-3L4.3 11.5 6.5 9.5 6 6.5l3 .5z" />
      <path d="M8 10.5l1.5 1.5L13 8.5" />
    </>
  ),
  gear: (
    <>
      <circle cx="10" cy="10" r="2.6" />
      <path d="M10 2.5v2M10 15.5v2M17.5 10h-2M4.5 10h-2M15.3 4.7l-1.4 1.4M6.1 13.9l-1.4 1.4M15.3 15.3l-1.4-1.4M6.1 6.1 4.7 4.7" />
    </>
  ),
  search: (
    <>
      <circle cx="9" cy="9" r="5" />
      <path d="M12.8 12.8 17 17" />
    </>
  ),
  "chevron-down": <path d="m5.5 8 4.5 4.5L14.5 8" />,
  "chevron-right": <path d="m8 5.5 4.5 4.5L8 14.5" />,
  "chevron-left": <path d="m12 5.5-4.5 4.5 4.5 4.5" />,
  plus: <path d="M10 4.5v11M4.5 10h11" />,
  trash: (
    <>
      <path d="M4.5 5.5h11" />
      <path d="M8 5.5V3.5h4v2" />
      <path d="M6 5.5 6.8 17h6.4L14 5.5" />
      <path d="M8.7 8.5v5.5M11.3 8.5v5.5" />
    </>
  ),
  grip: (
    <>
      <path d="M7.5 5h.01M12.5 5h.01M7.5 10h.01M12.5 10h.01M7.5 15h.01M12.5 15h.01" />
    </>
  ),
  pause: <path d="M7.5 4.5v11M12.5 4.5v11" />,
  stop: <path d="M5 5h10v10H5z" />,
  download: (
    <>
      <path d="M10 3v9" />
      <path d="m6.2 8.5 3.8 3.8 3.8-3.8" />
      <path d="M4 16h12" />
    </>
  ),
  upload: (
    <>
      <path d="M10 13V4" />
      <path d="m6.2 7.8 3.8-3.8 3.8 3.8" />
      <path d="M4 16h12" />
    </>
  ),
  check: <path d="m4.5 10.5 3.6 3.6L15.5 6.5" />,
  cross: <path d="m5.5 5.5 9 9M14.5 5.5l-9 9" />,
  dash: <path d="M5 10h10" />,
  alert: (
    <>
      <path d="M10 3.2 18 16.8H2z" />
      <path d="M10 8v3.6M10 14h.01" />
    </>
  ),
  thread: (
    <>
      <circle cx="4.5" cy="5" r="1.6" />
      <circle cx="15.5" cy="15" r="1.6" />
      <path d="M4.5 6.6v4.9c0 1.7 1.4 3 3 3h6.4" />
    </>
  ),
  "zoom-in": (
    <>
      <circle cx="9" cy="9" r="5" />
      <path d="M12.8 12.8 17 17M7 9h4M9 7v4" />
    </>
  ),
  "zoom-out": (
    <>
      <circle cx="9" cy="9" r="5" />
      <path d="M12.8 12.8 17 17M7 9h4" />
    </>
  ),
  flag: (
    <>
      <path d="M5 17V3.5" />
      <path d="M5 4.2h9l-2 3.1 2 3.1H5z" />
    </>
  ),
  clock: (
    <>
      <circle cx="10" cy="10" r="6.5" />
      <path d="M10 6v4.2l2.8 1.7" />
    </>
  ),
};

export function Icon({
  name,
  size = 16,
  className = "",
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 20 20"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={`shrink-0 ${className}`}
    >
      {PATHS[name]}
    </svg>
  );
}
