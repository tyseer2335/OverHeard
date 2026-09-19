import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Voxmarket — Voice Market Intelligence",
  description: "Talk to an AI analyst that investigates real customer feedback, backed by evidence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
