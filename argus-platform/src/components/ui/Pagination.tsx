"use client";

import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";

interface PaginationMeta {
  total: number;
  page: number;
  limit: number;
  totalPages: number;
}

interface UsePaginationProps {
  baseUrl: string;
  initialPage?: number;
  initialLimit?: number;
}

export function usePagination({
  baseUrl,
  initialPage = 1,
  initialLimit = 10,
}: UsePaginationProps) {
  const searchParams = useSearchParams();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<unknown[]>([]);
  const [meta, setMeta] = useState<PaginationMeta>({
    total: 0,
    page: initialPage,
    limit: initialLimit,
    totalPages: 0,
  });

  const page = Number(searchParams.get("page")) || initialPage;
  const limit = Number(searchParams.get("limit")) || initialLimit;

  const fetchData = async (
    pageNum: number = page,
    limitNum: number = limit,
  ) => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${baseUrl}?page=${pageNum}&limit=${limitNum}`,
      );

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      const result = await response.json();
      setData(result.data || []);
      setMeta(
        result.meta || {
          total: result.data?.length || 0,
          page: pageNum,
          limit: limitNum,
          totalPages: Math.ceil((result.data?.length || 0) / limitNum),
        },
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch data");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, limit]);

  const goToPage = (pageNum: number) => {
    const params = new URLSearchParams(searchParams);
    params.set("page", String(pageNum));
    window.history.pushState({}, "", `?${params.toString()}`);
    fetchData(pageNum);
  };

  const nextPage = () => {
    if (meta.page < meta.totalPages) {
      goToPage(meta.page + 1);
    }
  };

  const prevPage = () => {
    if (meta.page > 1) {
      goToPage(meta.page - 1);
    }
  };

  return {
    data,
    meta,
    isLoading,
    error,
    goToPage,
    nextPage,
    prevPage,
    refresh: () => fetchData(),
  };
}

interface PaginationControlsProps {
  meta: PaginationMeta;
  onPageChange: (page: number) => void;
}

export function PaginationControls({
  meta,
  onPageChange,
}: PaginationControlsProps) {
  const pages = Array.from({ length: meta.totalPages }, (_, i) => i + 1);

  // Show max 5 pages around current
  const visiblePages = pages.filter((p) => {
    if (p === 1 || p === meta.totalPages) return true;
    return Math.abs(p - meta.page) <= 2;
  });

  return (
    <div className="flex items-center justify-between mt-4">
      <div className="text-sm text-muted-foreground">
        Showing {(meta.page - 1) * meta.limit + 1} -{" "}
        {Math.min(meta.page * meta.limit, meta.total)} of {meta.total}
      </div>

      <div className="flex items-center gap-1">
        <button
          onClick={() => onPageChange(meta.page - 1)}
          disabled={meta.page === 1}
          className="px-3 py-1 rounded border border-border disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted"
        >
          Previous
        </button>

        {visiblePages.map((p, i) => (
          <span key={p}>
            {i > 0 && visiblePages[i - 1] !== p - 1 && (
              <span className="px-1">...</span>
            )}
            <button
              onClick={() => onPageChange(p)}
              className={`px-3 py-1 rounded border ${
                p === meta.page
                  ? "bg-primary text-primary-foreground"
                  : "border-border hover:bg-muted"
              }`}
            >
              {p}
            </button>
          </span>
        ))}

        <button
          onClick={() => onPageChange(meta.page + 1)}
          disabled={meta.page === meta.totalPages}
          className="px-3 py-1 rounded border border-border disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted"
        >
          Next
        </button>
      </div>
    </div>
  );
}
