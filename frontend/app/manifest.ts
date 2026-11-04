import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "LALIGA Fantasy",
    short_name: "Fantasy",
    description: "Panel de acción: reloj, supervivencia del XI y las acciones del día.",
    start_url: "/",
    display: "standalone",
    background_color: "#02070A",
    theme_color: "#02070A",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
