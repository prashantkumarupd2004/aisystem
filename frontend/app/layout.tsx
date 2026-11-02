import "./globals.css";
import type { ReactNode } from "react";

export const metadata = { title: "Instagram Reels Automation" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-100 text-slate-900">{children}</body>
    </html>
  );
}
