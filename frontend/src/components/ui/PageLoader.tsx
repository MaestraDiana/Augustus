interface PageLoaderProps {
  message?: string;
}

export default function PageLoader({ message = 'Loading...' }: PageLoaderProps) {
  return (
    <div style={{ padding: 'var(--space-6)', color: 'var(--text-secondary)' }}>
      {message}
    </div>
  );
}
