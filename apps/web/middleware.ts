import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  const hostname = request.headers.get('host') || '';
  const pathname = request.nextUrl.pathname;

  // Redirect review.curlys.ca root to /review
  if (hostname === 'review.curlys.ca' && pathname === '/') {
    return NextResponse.redirect(new URL('/review', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: '/',
};
