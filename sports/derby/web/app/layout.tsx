import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Derby Pick 5",
  description: "Derby weekend Pick 5 — race cards, odds, simulation, tickets.",
  // Personal LAN/Tailscale app; never want it indexed if the host ever
  // becomes reachable on the open internet. Belt-and-braces with the
  // X-Robots-Tag header set in next.config.mjs (security-report S2).
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // viewportFit=cover lets the page paint into the iPad's safe-area insets
  // (matters in landscape near the home indicator / camera notch).
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
