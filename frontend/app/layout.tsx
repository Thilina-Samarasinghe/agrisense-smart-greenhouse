import type { Metadata } from "next";

import { Shell } from "@/components/shell";
import { LiveProvider } from "@/lib/live";

import "./globals.css";

export const metadata: Metadata = {
  title: "AgriSense",
  description: "Smart greenhouse simulation and automation platform",
};

// Apply the saved theme before first paint so there is no light/dark flash.
const themeScript = `try{var t=localStorage.getItem("theme");if(t)document.documentElement.setAttribute("data-theme",t)}catch(e){}`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="antialiased">
        <LiveProvider>
          <Shell>{children}</Shell>
        </LiveProvider>
      </body>
    </html>
  );
}
