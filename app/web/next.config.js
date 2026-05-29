/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,
  async rewrites() {
    // 브라우저는 항상 same-origin `/api/*`로 보내고, Next 서버가 백엔드로 프록시한다.
    // Docker에서는 웹 컨테이너가 호스트 LAN IP:8000에 못 붙는 경우가 많아 INTERNAL_API_URL(api 서비스명)을 우선한다.
    let backend =
      process.env.INTERNAL_API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      "http://localhost:8000";
    backend = String(backend).trim().replace(/\/+$/, "");
    // `.../api` 로 잘못 설정하면 destination이 `/api/api/...` 가 되어 백엔드에서 404(Not Found)가 난다.
    if (backend.endsWith("/api")) {
      backend = backend.slice(0, -4).replace(/\/+$/, "");
    }
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};
