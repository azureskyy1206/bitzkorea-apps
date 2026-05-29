import { NextRequest, NextResponse } from "next/server";

function resolveApiBase(): string {
  if (process.env.INTERNAL_API_URL) {
    return process.env.INTERNAL_API_URL.replace(/\/$/, "");
  }
  return "http://api:8000";
}

type RouteCtx = { params: Promise<{ path: string[] }> };

function applyUpstreamCookies(upstream: Response, response: NextResponse): void {
  const setCookies = upstream.headers.getSetCookie?.();
  if (setCookies?.length) {
    for (const cookie of setCookies) {
      response.headers.append("Set-Cookie", cookie);
    }
    return;
  }
  const single = upstream.headers.get("set-cookie");
  if (single) {
    response.headers.set("Set-Cookie", single);
  }
}

async function proxy(req: NextRequest, ctx: RouteCtx) {
  const { path: segments } = await ctx.params;

  const sub = segments.join("/");
  const url = new URL(`${resolveApiBase()}/admin/${sub}`);
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.set(k, v));

  const headers = new Headers();
  const cookie = req.headers.get("cookie");
  if (cookie) {
    headers.set("Cookie", cookie);
  }
  const adminKey = req.headers.get("x-admin-api-key");
  if (adminKey) {
    headers.set("X-Admin-Api-Key", adminKey);
  }

  let body: BodyInit | undefined;
  const method = req.method;

  if (method !== "GET" && method !== "HEAD") {
    const contentType = req.headers.get("content-type") || "";
    if (contentType.includes("multipart/form-data")) {
      body = await req.formData();
    } else {
      const text = await req.text();
      if (text) {
        body = text;
        headers.set("Content-Type", contentType || "application/json");
      }
    }
  }

  let upstream: Response;
  try {
    upstream = await fetch(url.toString(), { method, headers, body });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "upstream fetch failed";
    return NextResponse.json(
      { detail: `API 서버에 연결할 수 없습니다. api 컨테이너가 실행 중인지 확인하세요. (${msg})` },
      { status: 502 },
    );
  }
  const resContentType = upstream.headers.get("content-type") || "application/json";
  const payload = await upstream.arrayBuffer();

  const response = new NextResponse(payload, {
    status: upstream.status,
    headers: { "Content-Type": resContentType },
  });
  applyUpstreamCookies(upstream, response);
  return response;
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
