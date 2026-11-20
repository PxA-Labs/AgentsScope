import type { Metadata } from "next";
import "./globals.css";
import { AuthBanner } from "../components/AuthBanner";

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
      <body>
        <AuthBanner />
        {children}
      </body>
    </html>
  );
}
