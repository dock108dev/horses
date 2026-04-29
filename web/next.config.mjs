// Inside Docker the FastAPI service is reachable as `http://api:8000`. For
// local non-Docker dev set API_BASE_URL=http://localhost:8000.
const API_BASE_URL = process.env.API_BASE_URL || "http://api:8000";

// Security-headers defense in depth — the SPA loads no third-party assets
// and uses no inline event handlers, so a tight CSP is achievable without
// hashes/nonces. `unsafe-inline` for style-src is required because the
// React tree uses inline `style={...}` props throughout (and Next.js
// itself injects an inline style block for hydration). CORP same-origin
// (security-report S11) keeps the SPA pages from being embedded as opaque
// resources cross-origin, complementing X-Frame-Options + frame-ancestors.
const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Robots-Tag", value: "noindex, nofollow" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  {
    key: "Permissions-Policy",
    value: "interest-cohort=(), geolocation=(), camera=(), microphone=()",
  },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "connect-src 'self'",
      "font-src 'self' data:",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; "),
  },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Standalone output keeps the production image small.
  output: "standalone",
  // Avoid leaking the framework version in response headers.
  poweredByHeader: false,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_BASE_URL}/api/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: SECURITY_HEADERS,
      },
    ];
  },
};

export default nextConfig;
