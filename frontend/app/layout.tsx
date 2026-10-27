import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";

const sans = Plus_Jakarta_Sans({
  variable: "--font-sans-app",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const mono = JetBrains_Mono({
  variable: "--font-mono-app",
  subsets: ["latin"],
  weight: ["500", "600"],
});

export const metadata: Metadata = {
  title: "LALIGA Fantasy · Hoy",
  description: "Panel de acción: reloj, supervivencia del XI y las acciones del día.",
  robots: { index: false, follow: false },
  themeColor: "#111827",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`${sans.variable} ${mono.variable} h-full overflow-x-hidden antialiased`}>
      <body className="min-h-full overflow-x-hidden bg-background font-sans text-foreground">{children}</body>
    </html>
  );
}
