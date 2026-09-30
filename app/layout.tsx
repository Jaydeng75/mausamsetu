import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MausamSetu · Forecast Intelligence",
  description: "India-focused probabilistic forecast blending, model comparison, and verification workbench.",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased">{children}</body>
    </html>
  );
}
