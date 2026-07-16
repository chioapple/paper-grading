import type { SVGProps } from "react";

type IconName =
  | "brand"
  | "document"
  | "clipboard"
  | "download"
  | "globe"
  | "user"
  | "inbox"
  | "chevronLeft"
  | "chevronDown"
  | "plus"
  | "accounts"
  | "settings"
  | "close";

type IconProps = SVGProps<SVGSVGElement> & {
  name: IconName;
};

const paths: Record<IconName, React.ReactNode> = {
  brand: (
    <>
      <path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z" />
      <path d="m4 7.5 8 4.5 8-4.5M12 12v9m3-5 3-1.7" />
    </>
  ),
  document: (
    <>
      <path d="M7 3h7l4 4v14H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
      <path d="M14 3v5h5M9 13h6M9 17h6" />
    </>
  ),
  clipboard: (
    <>
      <path d="M9 5H6a2 2 0 0 0-2 2v13h16V7a2 2 0 0 0-2-2h-3" />
      <path d="M9 3h6v4H9zM8 13l2.5 2.5L16 10" />
    </>
  ),
  download: (
    <>
      <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 19v2h14v-2" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.3 2.5 3.5 5.5 3.5 9S14.3 18.5 12 21c-2.3-2.5-3.5-5.5-3.5-9S9.7 5.5 12 3Z" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 21c.8-4.4 3.3-6.5 7.5-6.5s6.7 2.1 7.5 6.5" />
    </>
  ),
  inbox: (
    <>
      <path d="m5 9 2-5h10l2 5 2 4v7H3v-7l2-4Z" />
      <path d="M3 13h5l1.5 2h5l1.5-2h5" />
      <path className="icon-accent" d="M8 4 6.5 2M12 3V1M16 4l1.5-2" />
    </>
  ),
  chevronLeft: <path d="m14 7-5 5 5 5" />,
  chevronDown: <path d="m7 10 5 5 5-5" />,
  plus: <path d="M12 5v14M5 12h14" />,
  accounts: (
    <>
      <circle cx="12" cy="7" r="3.5" />
      <path d="M5 21c.6-4.3 2.9-6.5 7-6.5s6.4 2.2 7 6.5" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" />
    </>
  ),
  close: <path d="m6 6 12 12M18 6 6 18" />,
};

export function Icon({ name, ...props }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
