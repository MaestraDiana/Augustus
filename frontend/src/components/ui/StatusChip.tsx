interface StatusChipProps {
  status: 'running' | 'paused' | 'error' | 'idle';
  label: string;
}

export default function StatusChip({ status, label }: StatusChipProps) {
  return (
    <div className="status-chip">
      <span className={`status-dot ${status}`} />
      {label}
    </div>
  );
}
