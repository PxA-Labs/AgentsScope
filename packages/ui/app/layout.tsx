import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentScope Observability Dashboard",
  description: "Real-time multi-agent telemetry and monitoring dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
