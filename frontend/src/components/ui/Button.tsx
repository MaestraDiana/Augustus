import React, { ReactNode } from 'react';

interface ButtonProps {
  children: ReactNode;
  variant?: 'primary' | 'secondary' | 'ghost' | 'destructive';
  size?: 'default' | 'sm' | 'xs';
  onClick?: () => void;
  type?: 'button' | 'submit' | 'reset';
  disabled?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export default function Button({
  children,
  variant = 'primary',
  size = 'default',
  onClick,
  type = 'button',
  disabled = false,
  className = '',
  style,
}: ButtonProps) {
  const classes = `btn btn-${variant} ${size !== 'default' ? `btn-${size}` : ''} ${className}`.trim();

  return (
    <button className={classes} onClick={onClick} type={type} disabled={disabled} style={style}>
      {children}
    </button>
  );
}
