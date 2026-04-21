/** @type {import('next').NextConfig} */
const nextConfig = {
  // Enable production optimizations
  productionBrowserSourceMaps: false,

  // Image optimization with CDN support
  images: {
    domains: [],
    remotePatterns: [],
    minimumCacheTTL: 60,
  },

  // Headers for static asset caching and CDN
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=0, must-revalidate",
          },
        ],
      },
      {
        source: "/_next/static/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
      {
        source: "/static/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
    ];
  },

  // Experimental features for performance
  experimental: {
    // Enable if using App Router optimizations
    // serverActions: true,
  },
};

export default nextConfig;
