interface LoadingSkeletonProps {
  width?: string;
  height?: string;
  className?: string;
  lines?: number;
}

export default function LoadingSkeleton({ width = '100%', height = '20px', className = '', lines }: LoadingSkeletonProps) {
  if (lines && lines > 1) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {Array.from({ length: lines }, (_, i) => (
          <div
            key={i}
            className={`loading-skeleton ${className}`.trim()}
            style={{ width: i === lines - 1 ? '60%' : width, height }}
          />
        ))}
      </div>
    );
  }

  return (
    <div
      className={`loading-skeleton ${className}`.trim()}
      style={{ width, height }}
    />
  );
}
