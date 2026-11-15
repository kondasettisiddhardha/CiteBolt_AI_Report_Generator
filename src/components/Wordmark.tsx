export interface WordmarkProps {
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function LogoMark({ className = "h-7 w-7 rounded-lg" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="citebolt-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#2dd4bf" />
          <stop offset="100%" stopColor="#0d9488" />
        </linearGradient>
        <linearGradient id="citebolt-bolt" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="100%" stopColor="#ccfbf1" />
        </linearGradient>
        <mask id="citebolt-cut">
          <rect width="64" height="64" fill="#fff" />
          <path d="M38 6 L20 35 H30 L25 58 L46 26 H36 L43 6 Z" fill="#000" stroke="#000" strokeWidth="5" strokeLinejoin="round" />
        </mask>
      </defs>
      <rect width="64" height="64" rx="14" fill="url(#citebolt-bg)" />
      <path d="M45 21 A17 17 0 1 0 45 43" fill="none" stroke="#ffffff" strokeWidth="8" strokeLinecap="round" mask="url(#citebolt-cut)" />
      <path d="M38 6 L20 35 H30 L25 58 L46 26 H36 L43 6 Z" fill="url(#citebolt-bolt)" stroke="#ffffff" strokeWidth="1" strokeLinejoin="round" />
    </svg>
  );
}

export default function Wordmark({ size = "md", className = "" }: WordmarkProps) {
  const sizeMap = {
    sm: "text-xs tracking-[0.12em]",
    md: "text-sm tracking-[0.12em]",
    lg: "text-base tracking-[0.12em]",
  };

  return (
    <span
      className={`inline-flex items-center font-bold uppercase select-none ${sizeMap[size]} ${className}`}
      aria-label="CiteBolt"
    >
      <span className="text-brand-cite" aria-hidden="true">
        CITE
      </span>
      <span className="text-brand-bolt" aria-hidden="true">
        BOLT
      </span>
    </span>
  );
}
