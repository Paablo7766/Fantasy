import type { Metadata, Viewport } from "next";
import "./globals.css";

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
    <html lang="es" className="h-full overflow-x-hidden">
      <body className="min-h-full overflow-x-hidden bg-background text-foreground">{children}</body>
    </html>
  );
}
