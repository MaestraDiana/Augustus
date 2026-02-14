import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { AGENT_COLORS } from '../../utils/constants';

interface UsageChartProps {
  data: Array<{ date: string; total: number; [key: string]: string | number }>;
  agentKeys?: string[];
  dailyCeiling?: number;
  warningThreshold?: number;
}

const UsageChart: React.FC<UsageChartProps> = ({ data, agentKeys, dailyCeiling = 50, warningThreshold = 35 }) => {
  // If agentKeys are provided, render stacked bars per agent; otherwise single bar for total
  const useStacked = agentKeys && agentKeys.length > 0;

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 20, right: 20, bottom: 40, left: 50 }}>
        <CartesianGrid strokeDasharray="4 4" stroke="var(--border-color)" />
        <XAxis
          dataKey="date"
          tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: 'Inter' }}
          stroke="var(--border-color)"
        />
        <YAxis
          tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: 'JetBrains Mono' }}
          stroke="var(--border-color)"
          tickFormatter={(value) => `$${value}`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: 'var(--bg-raised)',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--text-primary)',
            fontSize: 13,
          }}
          labelStyle={{ color: 'var(--text-primary)', fontWeight: 500 }}
          formatter={(value: number) => `$${value.toFixed(2)}`}
        />
        {dailyCeiling > 0 && (
          <ReferenceLine
            y={dailyCeiling}
            stroke="var(--accent-attention)"
            strokeDasharray="8 4"
            strokeWidth={2}
            label={{
              value: 'Daily Ceiling',
              position: 'right',
              fill: 'var(--accent-attention)',
              fontSize: 11,
            }}
          />
        )}
        {warningThreshold > 0 && (
          <ReferenceLine
            y={warningThreshold}
            stroke="var(--accent-alert)"
            strokeDasharray="2 4"
            strokeWidth={2}
            label={{
              value: 'Warning',
              position: 'right',
              fill: 'var(--accent-alert)',
              fontSize: 11,
            }}
          />
        )}
        {useStacked ? (
          agentKeys.map((key, i) => (
            <Bar
              key={key}
              dataKey={key}
              stackId="a"
              fill={AGENT_COLORS[i % AGENT_COLORS.length]}
              radius={i === agentKeys.length - 1 ? [2, 2, 0, 0] : undefined}
            />
          ))
        ) : (
          <Bar dataKey="total" fill="var(--accent-primary)" radius={[2, 2, 0, 0]} />
        )}
      </BarChart>
    </ResponsiveContainer>
  );
};

export default UsageChart;
