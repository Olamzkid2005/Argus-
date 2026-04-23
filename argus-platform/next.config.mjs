/** @type {import('next').NextConfig } */
const nextConfig = {
  // Enable production optimizations
  productionBrowserSourceMaps: false,

  // Suppress Node.js deprecation warnings
  onDemandEntries: {
    // Reduce memory footprint during dev
    maxRetentionBoxCount: 2,
  },

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

  // Webpack configuration to handle pg-native
  webpack: (config, { isServer }) => {
    if (!isServer) {
      // pg-native is server-only, never bundle it for the browser
      config.resolve.fallback = {
        ...config.resolve.fallback,
        "pg-native": false,
      };
    }
    return config;
  },
};

export default nextConfig;
