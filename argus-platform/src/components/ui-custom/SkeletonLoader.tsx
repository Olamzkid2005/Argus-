interface SkeletonLoaderProps {
  className?: string;
}

export default function SkeletonLoader({ className = "" }: SkeletonLoaderProps) {
  return (
    <div
      className={`relative overflow-hidden bg-white/[0.03] ${className}`}
      style={{
        backgroundImage:
          "linear-gradient(110deg, rgba(255,255,255,0) 30%, rgba(255,255,255,0.05) 50%, rgba(255,255,255,0) 70%)",
        backgroundSize: "200% 100%",
        animation: "shimmer 2s ease-in-out infinite",
      }}
    />
  );
}