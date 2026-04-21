/**
 * API Response normalization utilities
 */

import { NextResponse } from "next/server";

export interface ApiResponse<T = unknown> {
  data?: T;
  error?: string;
  message?: string;
}

export interface PaginatedResponse<T = unknown> {
  data: T[];
  meta: {
    total: number;
    page: number;
    limit: number;
    totalPages: number;
    hasMore?: boolean;
  };
}

/**
 * Create success response
 */
export function successResponse<T>(
  data: T,
  status: number = 200
): NextResponse<ApiResponse<T>> {
  return NextResponse.json(
    { data },
    { status }
  );
}

/**
 * Create error response
 */
export function errorResponse(
  error: string,
  status: number = 500
): NextResponse<ApiResponse> {
  return NextResponse.json(
    { error },
    { status }
  );
}

/**
 * Create paginated response
 */
export function paginatedResponse<T>(
  data: T[],
  meta: PaginatedResponse<T>["meta"],
  status: number = 200
): NextResponse<PaginatedResponse<T>> {
  return NextResponse.json(
    { data, meta } as PaginatedResponse<T>,
    { status }
  );
}

/**
 * Create 204 No Content response
 */
export function noContentResponse(): NextResponse {
  return new NextResponse(null, { status: 204 });
}

/**
 * Create 201 Created response
 */
export function createdResponse<T>(
  data: T
): NextResponse<ApiResponse<T>> {
  return NextResponse.json(
    { data, message: "Created successfully" },
    { status: 201 }
  );
}