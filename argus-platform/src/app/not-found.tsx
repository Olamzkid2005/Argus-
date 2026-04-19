import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="text-center">
        <h1 className="mb-4 font-sans text-6xl font-bold text-gray-900">404</h1>
        <p className="mb-4 text-xl text-gray-600">
          This page could not be found
        </p>
        <Link
          href="/"
          className="inline-block rounded bg-blue-600 px-6 py-3 text-white transition hover:bg-blue-700"
        >
          Return home
        </Link>
      </div>
    </div>
  );
}