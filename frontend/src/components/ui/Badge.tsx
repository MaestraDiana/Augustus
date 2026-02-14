import { ReactNode } from 'react';

interface BadgeProps {
  children: ReactNode;
  variant?: 'active' | 'paused' | 'error' | 'idle' | 'identity' | 'tier-1' | 'tier-2' | 'tier-3';
  className?: string;
}

export default function Badge({ children, variant = 'idle', className = '' }: BadgeProps) {
  return (
    <span className={`badge badge-${variant} ${className}`.trim()}>
      {children}
    </span>
  );
}
