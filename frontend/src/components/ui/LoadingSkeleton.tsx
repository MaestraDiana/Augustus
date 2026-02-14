interface LoadingSkeletonProps {
  width?: string;
  height?: string;
  className?: string;
}

export default function LoadingSkeleton({ width = '100%', height = '20px', className = '' }: LoadingSkeletonProps) {
  return (
    <div
      className={`loading-skeleton ${className}`.trim()}
      style={{ width, height }}
    />
  );
}
