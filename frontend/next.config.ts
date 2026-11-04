import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // NEXT_DIST_DIR permite un segundo ``next dev`` en la misma carpeta sin chocar con el bloqueo de .next.
  ...(process.env.NEXT_DIST_DIR ? { distDir: process.env.NEXT_DIST_DIR } : {}),
  async redirects() {
    return [
      { source: "/once", destination: "/equipo", permanent: false },
      { source: "/cartera", destination: "/equipo?tab=cartera", permanent: false },
      { source: "/clausulazos", destination: "/clausulas", permanent: false },
      { source: "/equipo", has: [{ type: "query", key: "tab", value: "clausulas" }], destination: "/clausulas", permanent: false },
      { source: "/rivales", destination: "/liga", permanent: false },
      { source: "/intel", destination: "/laboratorio?tab=senales", permanent: false },
      { source: "/calibracion", destination: "/laboratorio?tab=calibracion", permanent: false },
    ];
  },
  async rewrites() {
    // En Vercel el proxy vive en app/api/[...path]/route.ts (NEXT_PUBLIC_API_URL).
    // Reescribir a 127.0.0.1 en producción devolvería 404/502 en la nube.
    if (process.env.VERCEL === "1") {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        // BACKEND_ORIGIN permite un segundo dev contra otro uvicorn (pruebas en paralelo).
        destination: `${process.env.BACKEND_ORIGIN || "http://127.0.0.1:8000"}/api/:path*`,
      },
    ];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
