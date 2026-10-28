import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      { source: "/once", destination: "/equipo", permanent: false },
      { source: "/cartera", destination: "/equipo?tab=cartera", permanent: false },
      { source: "/clausulazos", destination: "/equipo?tab=clausulas", permanent: false },
      { source: "/rivales", destination: "/liga", permanent: false },
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
        destination: "http://127.0.0.1:8000/api/:path*",
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
