import type { Metadata } from "next";
import { JetBrains_Mono, Outfit } from "next/font/google";
import "./globals.css";

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  weight: ["500", "600"],
});

export const metadata: Metadata = {
  title: "LALIGA Fantasy · Tablero",
  description: "Caja de herramientas de solo lectura: once óptimo, mercado y auditoría de rivales.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`${outfit.variable} ${jetbrains.variable} h-full antialiased`}>
      <body className="min-h-full bg-slate-950 font-sans text-slate-100">{children}</body>
    </html>
  );
}
