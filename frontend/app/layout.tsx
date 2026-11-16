import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Summer — Async PDF Processing",
  description: "Upload PDFs, parse to markdown, and summarize asynchronously.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
