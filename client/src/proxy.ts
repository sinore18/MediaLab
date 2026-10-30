import { NextResponse, type NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  if (new URL(request.url).pathname === "/transcribe") {
    return NextResponse.rewrite(new URL("/bleeper/transcribe", request.url));
  }
}
