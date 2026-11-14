import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import "./inicio.css";
import "./splash.css";
import { SplashIntro, SPLASH_HEAD_SCRIPT } from "@/components/marca/SplashIntro";

const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "LALIGA Fantasy · Hoy",
  description: "Panel de acción: reloj, supervivencia del XI y las acciones del día.",
  robots: { index: false, follow: false },
  applicationName: "LALIGA Fantasy",
  appleWebApp: { capable: true, title: "Fantasy", statusBarStyle: "black-translucent" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#02070A",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`${sans.variable} ${mono.variable} h-full overflow-x-hidden`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: SPLASH_HEAD_SCRIPT }} />
      </head>
      <body className="min-h-full overflow-x-hidden bg-background font-sans text-foreground">
        <SplashIntro />
        {children}
      </body>
    </html>
  );
}
